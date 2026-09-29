"""Uploaded bank statements: incoming payments are matched to payment references (R35, R36).

- Matched by the payer reference, or by a reference code written into the message.
- Full payment: fees paid (eCP and card follow, see payments). Partial payment: e-mail to the payer with
  the rest. Overpayment and unknown reference: a task ("Požiadavka") for the administrator.
- The same file and the same bank transaction are never processed twice.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess import audit
from ess.banking import ParsedTransaction, parse
from ess.models import BankStatement, BankTransaction, Member, PaymentReference, Task, TaskStatus, TaskType
from ess.security import pii
from ess.services import members, outbox, payments
from ess.services.access import Actor, DomainError, require_admin

_CTX = "bank_transactions."
_CODE_IN_TEXT = re.compile(r"\b[" + payments.CODE_ALPHABET + r"]{12}\b")
PAYMENT_TASKS = (TaskType.PAYMENT_UNMATCHED, TaskType.PAYMENT_OVERPAID)


@dataclass
class ImportResult:
    counts: dict[str, int] = field(default_factory=dict)  # result -> number of payments
    duplicates: int = 0  # already imported from another statement

    def add(self, result: str) -> None:
        self.counts[result] = self.counts.get(result, 0) + 1


def _reference_for(session: Session, tx: ParsedTransaction) -> PaymentReference | None:
    if tx.payer_reference:
        reference = payments.find_reference(session, tx.payer_reference)
        if reference is not None:
            return reference
    for candidate in _CODE_IN_TEXT.findall((tx.message or "").upper()):
        reference = payments.find_reference(session, candidate)
        if reference is not None:
            return reference
    return None


def _open_task(session: Session, actor: Actor, task_type: TaskType, transaction: BankTransaction,
               reference: PaymentReference | None, **context) -> None:
    member_id = club_id = None
    if reference is not None:
        club_id = reference.club_id
        if reference.kind == payments.K.MEMBER.value:
            member_id = reference.items[0].fee.member_id
    task = Task(id=uuid.uuid4(), task_type=task_type.value, status=TaskStatus.OPEN.value, member_id=member_id,
                club_id=club_id, bank_transaction_id=transaction.id, requested_by=actor.id,
                context={"amount": str(transaction.amount), "currency": transaction.currency,
                         "booked_on": transaction.booked_on.isoformat(),
                         **({"code": reference.code, "year": reference.year} if reference else {}), **context})
    session.add(task)
    session.flush()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="task.open",
                 entity_type="task", entity_id=str(task.id), details={"type": task_type.value})


def _payer_of(session: Session, reference: PaymentReference) -> Member | None:
    """Who gets the e-mail about a partial payment: the member, or the chair who created a bulk payment."""
    if reference.kind == payments.K.MEMBER.value:
        return session.get(Member, reference.items[0].fee.member_id)
    try:
        return session.get(Member, uuid.UUID(reference.created_by or ""))
    except ValueError:  # created by an administrator
        return None


def _notify_partial(session: Session, reference: PaymentReference, received: Decimal) -> None:
    payer = _payer_of(session, reference)
    data = members.read_member(payer) if payer is not None else None
    if data is None or not data.email:
        return
    try:
        link = payments.payme_url(session, reference)
    except DomainError:
        link = None
    outbox.queue(session, outbox.QueuedMail(
        to=data.email, subject=f"Neúplná platba členského SSS na rok {reference.year}", template="payment_partial",
        context={"first_name": data.first_name, "year": reference.year, "received": received,
                 "paid": reference.paid_amount, "remaining": payments.remaining(reference), "code": reference.code,
                 "payme_url": link, "bulk": reference.kind == payments.K.BULK.value}))


def _apply(session: Session, actor: Actor, transaction: BankTransaction, reference: PaymentReference) -> str:
    outcome = payments.apply_payment(session, actor, reference, transaction.amount)
    transaction.payment_reference_id = reference.id
    if outcome.result == "partial":
        _notify_partial(session, reference, transaction.amount)
    elif outcome.result == "overpaid":
        _open_task(session, actor, TaskType.PAYMENT_OVERPAID, transaction, reference,
                   overpaid=str(outcome.overpaid))
    return outcome.result


def import_statement(session: Session, actor: Actor, file_format: str, data: bytes) -> ImportResult:
    require_admin(actor)
    file_hash = hashlib.sha256(data).digest()
    if session.scalar(select(BankStatement.id).where(BankStatement.file_hash == file_hash)):
        raise DomainError("statement_already_imported")
    parsed = parse(file_format, data)
    statement = BankStatement(id=uuid.uuid4(), file_hash=file_hash, file_format=file_format, uploaded_by=actor.id)
    session.add(statement)
    session.flush()
    result = ImportResult()
    known = set(session.scalars(select(BankTransaction.bank_ref).where(
        BankTransaction.bank_ref.in_([t.bank_ref for t in parsed])))) if parsed else set()
    for tx in parsed:
        if tx.bank_ref in known or tx.amount <= 0:
            result.duplicates += tx.bank_ref in known
            continue
        known.add(tx.bank_ref)
        transaction = BankTransaction(
            id=uuid.uuid4(), statement_id=statement.id, bank_ref=tx.bank_ref, booked_on=tx.booked_on,
            amount=tx.amount.quantize(Decimal("0.01")), currency=tx.currency.upper(),
            payer_reference=(tx.payer_reference or "")[:140] or None,
            payer_name_enc=pii.encrypt(tx.payer_name, _CTX + "payer_name"),
            payer_iban_enc=pii.encrypt(tx.payer_iban, _CTX + "payer_iban"),
            message_enc=pii.encrypt(tx.message, _CTX + "message"), result="unknown_reference")
        session.add(transaction)
        session.flush()
        reference = _reference_for(session, tx) if transaction.currency == "EUR" else None
        if reference is None:
            _open_task(session, actor, TaskType.PAYMENT_UNMATCHED, transaction, None)
        else:
            transaction.result = _apply(session, actor, transaction, reference)
        result.add(transaction.result)
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="bank_statement.import",
                 entity_type="bank_statement", entity_id=str(statement.id),
                 details={"format": file_format, **result.counts, "duplicates": result.duplicates})
    return result


# --- tasks: manual matching ---------------------------------------------------------------------------


@dataclass
class TransactionView:
    """A bank payment for the administrator (decrypted, in memory only)."""

    transaction: BankTransaction
    payer_name: str | None
    payer_iban: str | None
    message: str | None


def view(session: Session, transaction_id: uuid.UUID) -> TransactionView | None:
    tx = session.get(BankTransaction, transaction_id)
    if tx is None:
        return None
    return TransactionView(tx, pii.decrypt(tx.payer_name_enc, _CTX + "payer_name"),
                           pii.decrypt(tx.payer_iban_enc, _CTX + "payer_iban"),
                           pii.decrypt(tx.message_enc, _CTX + "message"))


def _open_payment_task(session: Session, task_id: uuid.UUID) -> Task:
    task = session.get(Task, task_id, with_for_update=True)
    if task is None or task.status != TaskStatus.OPEN.value or task.task_type not in {t.value for t in PAYMENT_TASKS}:
        raise DomainError("task_not_open")
    return task


def _close(session: Session, actor: Actor, task: Task, resolution: str, note: str | None) -> None:
    task.status, task.resolution = TaskStatus.DONE.value, resolution
    task.resolution_note = (note or "").strip()[:500] or None
    task.resolved_by, task.resolved_at = actor.id, datetime.now(UTC)
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="task.close",
                 entity_type="task", entity_id=str(task.id), details={"type": task.task_type, "resolution": resolution})


def assign(session: Session, actor: Actor, task_id: uuid.UUID, code: str) -> str:
    """Unknown reference: the administrator finds the right reference (e.g. from the payer's name)."""
    require_admin(actor)
    task = _open_payment_task(session, task_id)
    if task.task_type != TaskType.PAYMENT_UNMATCHED.value:
        raise DomainError("task_not_open")
    reference = payments.find_reference(session, code)
    if reference is None:
        raise DomainError("reference_not_found")
    transaction = session.get(BankTransaction, task.bank_transaction_id)
    _close(session, actor, task, "assigned", reference.code)
    session.flush()
    result = _apply(session, actor, transaction, reference)
    transaction.result = "manual"
    return result


def resolve(session: Session, actor: Actor, task_id: uuid.UUID, note: str) -> None:
    """Handled outside the system (refunded, kept as a gift, not a membership fee); a note is required."""
    require_admin(actor)
    if not " ".join(note.split()):
        raise DomainError("note_required")
    task = _open_payment_task(session, task_id)
    if task.task_type == TaskType.PAYMENT_UNMATCHED.value:
        session.get(BankTransaction, task.bank_transaction_id).result = "ignored"
    _close(session, actor, task, "resolved", note)
