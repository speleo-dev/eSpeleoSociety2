"""Membership fees, payment references and PAYMe links (R35, R36; docs/data-model-payments.md).

- A fee (`fees`) is assessed for a member and year when first needed; the amount is fixed then.
- A member pays for themselves with their own reference (link in the eCP), or a club chair pays for
  several members with one bulk reference.
- A fee is paid when its reference is paid in full, or when an administrator marks it as paid.
"""

import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess import audit
from ess.models import (
    Club,
    Fee,
    Member,
    Membership,
    MembershipStatus,
    PaymentReference,
    PaymentReferenceItem,
    PaymentReferenceKind,
    PaymentReferenceStatus,
)
from ess.services import members, settings
from ess.services.access import Actor, DomainError, PermissionDenied, can_manage_club, require_admin, require_club_manager

K = PaymentReferenceKind
RS = PaymentReferenceStatus
UNFINISHED = (RS.OPEN.value, RS.PARTIAL.value)

# R35: 12 random characters, A-Z without I and O, digits 2-9 (easy to read and retype).
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 12
PAYME_URL = "https://payme.sk"


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _now() -> datetime:
    return datetime.now(UTC)


def _money(value: str | None) -> Decimal:
    try:
        return Decimal(value or "0").quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")


def payment_years(session: Session, today: date | None = None) -> list[int]:
    """This year; the next year too during the payment period (`renewal_window_days` before year end, R27)."""
    today = today or date.today()
    window = settings.get_int(session, "renewal_window_days")
    next_year_opens = date(today.year, 12, 31).toordinal() - window
    return [today.year, today.year + 1] if today.toordinal() >= next_year_opens else [today.year]


# --- fees ---------------------------------------------------------------------------------------------


def _payable_member(session: Session, member_id: uuid.UUID) -> Member:
    member = session.get(Member, member_id)
    if member is None:
        raise DomainError("member_not_found")
    if member.expelled_at or member.sss_ended_at:
        raise DomainError("member_not_in_sss")
    return member


def get_fee(session: Session, member_id: uuid.UUID, year: int) -> Fee | None:
    return session.scalar(select(Fee).where(Fee.member_id == member_id, Fee.year == year))


def assess_fee(session: Session, member: Member, year: int) -> Fee:
    """The fee of the year; created with the current full or reduced amount when missing."""
    fee = get_fee(session, member.id, year)
    if fee is None:
        key = "reduced_fee_amount" if member.reduced_fee else "fee_amount"
        fee = Fee(id=uuid.uuid4(), member_id=member.id, year=year, reduced=bool(member.reduced_fee),
                  amount=_money(settings.get_setting(session, key)))
        session.add(fee)
        session.flush()
    return fee


def _can_pay_for(session: Session, actor: Actor, member_id: uuid.UUID) -> bool:
    if actor.is_admin or (actor.kind == "member" and actor.id == str(member_id)):
        return True
    clubs = session.scalars(select(Club).join(Membership, Membership.club_id == Club.id).where(
        Membership.member_id == member_id, Membership.valid_to.is_(None))).all()
    return any(can_manage_club(session, actor, c) for c in clubs)


# --- references ---------------------------------------------------------------------------------------


def _new_reference(session: Session, actor: Actor, kind: K, year: int, fees: list[Fee],
                   club_id: uuid.UUID | None = None) -> PaymentReference:
    while True:  # 32^12 codes: a collision is practically impossible, but must not break the insert
        code = new_code()
        if session.scalar(select(PaymentReference.id).where(PaymentReference.code == code)) is None:
            break
    reference = PaymentReference(id=uuid.uuid4(), code=code, kind=kind.value, year=year, club_id=club_id,
                                 created_by=actor.id, expected_amount=sum((f.amount for f in fees), Decimal("0")),
                                 paid_amount=Decimal("0"), status=RS.OPEN.value)
    session.add(reference)
    for fee in fees:
        session.add(PaymentReferenceItem(id=uuid.uuid4(), reference_id=reference.id, fee_id=fee.id, amount=fee.amount))
    session.flush()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="payment_reference.create",
                 entity_type="payment_reference", entity_id=str(reference.id),
                 details={"kind": kind.value, "year": year, "members": len(fees)})
    return reference


def _member_reference_of(session: Session, fee: Fee) -> PaymentReference | None:
    return session.scalar(
        select(PaymentReference).join(PaymentReferenceItem, PaymentReferenceItem.reference_id == PaymentReference.id)
        .where(PaymentReferenceItem.fee_id == fee.id, PaymentReference.kind == K.MEMBER.value,
               PaymentReference.status.in_(UNFINISHED)))


def member_reference(session: Session, actor: Actor, member_id: uuid.UUID, year: int) -> PaymentReference:
    """The member's own reference for the year (the same one until paid or cancelled)."""
    member = _payable_member(session, member_id)
    if not _can_pay_for(session, actor, member_id):
        raise PermissionDenied("member_payment")
    fee = assess_fee(session, member, year)
    if fee.paid_at is not None:
        raise DomainError("fee_already_paid")
    return _member_reference_of(session, fee) or _new_reference(session, actor, K.MEMBER, year, [fee])


def remaining(reference: PaymentReference) -> Decimal:
    return max(reference.expected_amount - reference.paid_amount, Decimal("0"))


def payme_url(session: Session, reference: PaymentReference) -> str:
    """PAYMe link (payment link standard v1) for the remaining amount; the reference goes to PI."""
    iban = (settings.get_setting(session, "payment_iban") or "").replace(" ", "")
    if not iban:
        raise DomainError("payment_account_not_configured")
    params = {
        "V": "1",
        "IBAN": iban,
        "AM": f"{remaining(reference):.2f}",
        "CC": (settings.get_setting(session, "fee_currency") or "EUR").upper(),
        "PI": reference.code,
        "MSG": f"Clenske SSS {reference.year}",
        "CN": settings.get_setting(session, "payment_account_name") or "",
    }
    return f"{PAYME_URL}?{urlencode(params)}"


# --- bulk payment of a club chair ---------------------------------------------------------------------


@dataclass
class BulkCandidate:
    member_id: uuid.UUID
    name: str
    amount: Decimal
    reduced: bool

    def sort_key(self) -> str:
        return self.name.casefold()


def _in_unfinished_bulk(session: Session, fee_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not fee_ids:
        return set()
    return set(session.scalars(
        select(PaymentReferenceItem.fee_id).join(PaymentReference, PaymentReference.id == PaymentReferenceItem.reference_id)
        .where(PaymentReferenceItem.fee_id.in_(fee_ids), PaymentReference.kind == K.BULK.value,
               PaymentReference.status.in_(UNFINISHED))))


def bulk_candidates(session: Session, actor: Actor, club_id: uuid.UUID, year: int) -> list[BulkCandidate]:
    """Members of the club (status "member") whose fee is unpaid and not in another open bulk payment."""
    club = session.get(Club, club_id)
    if club is None:
        raise DomainError("club_not_found")
    require_club_manager(session, actor, club)
    rows = session.scalars(select(Member).join(Membership, Membership.member_id == Member.id).where(
        Membership.club_id == club_id, Membership.valid_to.is_(None), Membership.status == MembershipStatus.MEMBER,
        Member.expelled_at.is_(None), Member.sss_ended_at.is_(None))).all()
    fees = {f.member_id: f for f in session.scalars(select(Fee).where(
        Fee.year == year, Fee.member_id.in_([m.id for m in rows])))} if rows else {}
    busy = _in_unfinished_bulk(session, [f.id for f in fees.values()])
    reduced_amount = _money(settings.get_setting(session, "reduced_fee_amount"))
    full_amount = _money(settings.get_setting(session, "fee_amount"))
    result = []
    for member in rows:
        fee = fees.get(member.id)
        if fee is not None and (fee.paid_at is not None or fee.id in busy):
            continue
        amount = fee.amount if fee else (reduced_amount if member.reduced_fee else full_amount)
        reduced = fee.reduced if fee else bool(member.reduced_fee)
        result.append(BulkCandidate(member.id, members.read_member(member).full_name(), amount, reduced))
    return sorted(result, key=BulkCandidate.sort_key)


def create_bulk(session: Session, actor: Actor, club_id: uuid.UUID, year: int,
                member_ids: list[uuid.UUID]) -> PaymentReference:
    """One reference for the selected members; only members offered by `bulk_candidates`."""
    offered = {c.member_id for c in bulk_candidates(session, actor, club_id, year)}
    chosen = list(dict.fromkeys(member_ids))
    if not chosen:
        raise DomainError("no_members_selected")
    if any(m not in offered for m in chosen):
        raise DomainError("member_not_payable")
    fees = [assess_fee(session, session.get(Member, m), year) for m in chosen]
    return _new_reference(session, actor, K.BULK, year, fees, club_id=club_id)


def cancel_reference(session: Session, actor: Actor, reference_id: uuid.UUID) -> None:
    """A chair (or administrator) cancels an unpaid bulk payment, e.g. to choose other members."""
    reference = session.get(PaymentReference, reference_id, with_for_update=True)
    if reference is None or reference.status != RS.OPEN.value:
        raise DomainError("reference_not_open")
    if reference.kind == K.BULK.value:
        require_club_manager(session, actor, session.get(Club, reference.club_id))
    else:
        require_admin(actor)
    _cancel(session, actor, reference, "cancelled")


def _cancel(session: Session, actor: Actor, reference: PaymentReference, reason: str) -> None:
    reference.status = RS.CANCELLED.value
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="payment_reference.cancel",
                 entity_type="payment_reference", entity_id=str(reference.id), details={"reason": reason})


def open_bulk_references(session: Session, club_id: uuid.UUID) -> list[PaymentReference]:
    return list(session.scalars(select(PaymentReference).where(
        PaymentReference.club_id == club_id, PaymentReference.kind == K.BULK.value,
        PaymentReference.status.in_(UNFINISHED)).order_by(PaymentReference.created_at)))


# --- paying -------------------------------------------------------------------------------------------


def _set_paid(session: Session, actor: Actor, fee: Fee, reference: PaymentReference | None) -> None:
    fee.paid_at = _now()
    fee.payment_reference_id = reference.id if reference else None
    # The member's own link is no longer needed (e.g. paid in a bulk payment or marked manually).
    own = _member_reference_of(session, fee)
    if own is not None and own is not reference:
        _cancel(session, actor, own, "paid_otherwise")
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="fee.paid",
                 entity_type="fee", entity_id=str(fee.id),
                 details={"year": fee.year, "reference_id": str(reference.id) if reference else None})
    _after_paid(session, fee)


def _after_paid(session: Session, fee: Fee) -> None:
    """R33, R36: the eCP shows the paid year and its sticker; a member with a card gets the year's card."""
    from ess.services import ecp_content, sss_cards

    ecp_content.mark_stale(session, fee.member_id)
    sss_cards.issue_after_payment(session, fee.member_id, fee.year)


def mark_paid(session: Session, actor: Actor, member_id: uuid.UUID, year: int, note: str) -> Fee:
    """An administrator marks the fee as paid (e.g. paid in cash); a note is required (R36)."""
    require_admin(actor)
    note = " ".join(note.split())
    if not note:
        raise DomainError("note_required")
    member = _payable_member(session, member_id)
    fee = assess_fee(session, member, year)
    if fee.paid_at is not None:
        raise DomainError("fee_already_paid")
    fee.paid_manually_by, fee.note = actor.id, note[:500]
    _set_paid(session, actor, fee, None)
    return fee


@dataclass
class PaymentOutcome:
    result: str  # paid, partial, overpaid
    remaining: Decimal = Decimal("0")  # still to pay (partial)
    overpaid: Decimal = Decimal("0")  # to refund or keep as a gift (overpaid)
    paid_fee_ids: list[uuid.UUID] = field(default_factory=list)


def apply_payment(session: Session, actor: Actor, reference: PaymentReference, amount: Decimal) -> PaymentOutcome:
    """Add a received amount to the reference. Full payment pays all its fees (R36)."""
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if reference.status in (RS.PAID.value, RS.CANCELLED.value):
        # Paid again, or a cancelled link was used: nothing is owed on it.
        reference.paid_amount += amount
        return PaymentOutcome("overpaid", overpaid=amount)
    reference.paid_amount += amount
    if reference.paid_amount < reference.expected_amount:
        reference.status = RS.PARTIAL.value
        if reference.kind == K.MEMBER.value:  # the link in the eCP asks for the rest
            from ess.services import ecp_content

            ecp_content.mark_stale(session, reference.items[0].fee.member_id)
        audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="payment_reference.partial",
                     entity_type="payment_reference", entity_id=str(reference.id))
        return PaymentOutcome("partial", remaining=remaining(reference))
    reference.status = RS.PAID.value
    overpaid = reference.paid_amount - reference.expected_amount
    paid = []
    for item in reference.items:
        if item.fee.paid_at is not None:  # already paid otherwise (own link, manually)
            overpaid += item.amount
        else:
            _set_paid(session, actor, item.fee, reference)
            paid.append(item.fee_id)
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="payment_reference.paid",
                 entity_type="payment_reference", entity_id=str(reference.id))
    return PaymentOutcome("overpaid" if overpaid > 0 else "paid", overpaid=overpaid, paid_fee_ids=paid)


def find_reference(session: Session, code: str) -> PaymentReference | None:
    code = "".join(code.split()).upper()
    if len(code) != CODE_LENGTH:
        return None
    return session.scalar(select(PaymentReference).where(PaymentReference.code == code))


def member_fees(session: Session, member_id: uuid.UUID) -> list[Fee]:
    return list(session.scalars(select(Fee).where(Fee.member_id == member_id).order_by(Fee.year.desc())))


@dataclass
class ReferenceLine:
    member_id: uuid.UUID
    name: str
    amount: Decimal
    fee_paid_at: datetime | None


def reference_lines(session: Session, reference: PaymentReference) -> list[ReferenceLine]:
    """Members of a reference with names, for the administration (in memory only)."""
    lines = []
    for item in reference.items:
        member = session.get(Member, item.fee.member_id)
        lines.append(ReferenceLine(member.id, members.read_member(member).full_name(), item.amount, item.fee.paid_at))
    return sorted(lines, key=lambda line: line.name.casefold())


# --- overview -----------------------------------------------------------------------------------------


@dataclass
class FeeRow:
    """One member's fee of a year for the overview (decrypted, in memory only)."""

    member_id: uuid.UUID
    last_name: str
    first_name: str
    card_number: str | None
    club_id: uuid.UUID | None  # primary club
    club_name: str
    amount: Decimal
    reduced: bool
    paid_at: datetime | None
    method: str | None  # member (own link), bulk, manual; None = unpaid


def overview(session: Session, actor: Actor, year: int, club_id: uuid.UUID | None = None) -> list[FeeRow]:
    """Who should pay (members of SSS with status "member") and who paid the fee of the year.

    An administrator sees everybody; a club manager only members of the club.
    """
    if club_id is None:
        require_admin(actor)
    else:
        club = session.get(Club, club_id)
        if club is None:
            raise DomainError("club_not_found")
        require_club_manager(session, actor, club)
    clubs = {c.id: c.name for c in session.scalars(select(Club))}
    open_ms: dict[uuid.UUID, list[Membership]] = {}
    for m in session.scalars(select(Membership).where(Membership.valid_to.is_(None))):
        open_ms.setdefault(m.member_id, []).append(m)
    fees = {f.member_id: f for f in session.scalars(select(Fee).where(Fee.year == year))}
    ref_ids = [f.payment_reference_id for f in fees.values() if f.payment_reference_id]
    kinds = dict(session.execute(select(PaymentReference.id, PaymentReference.kind).where(
        PaymentReference.id.in_(ref_ids))).all()) if ref_ids else {}
    full = _money(settings.get_setting(session, "fee_amount"))
    reduced_amount = _money(settings.get_setting(session, "reduced_fee_amount"))
    rows = []
    for member in session.scalars(select(Member)):
        memberships = open_ms.get(member.id, [])
        fee = fees.get(member.id)
        paid = fee is not None and fee.paid_at is not None
        active = (not member.expelled_at and not member.sss_ended_at
                  and any(m.status == MembershipStatus.MEMBER for m in memberships))
        if not (active or paid):
            continue
        if club_id is not None and not any(m.club_id == club_id for m in memberships):
            continue
        primary = next((m.club_id for m in memberships if m.is_primary), None)
        data = members.read_member(member)
        method = None
        if paid:
            method = "manual" if fee.payment_reference_id is None else kinds.get(fee.payment_reference_id, "member")
        rows.append(FeeRow(
            member.id, data.last_name, data.first_name, data.card_number, primary, clubs.get(primary, ""),
            fee.amount if fee else (reduced_amount if member.reduced_fee else full),
            fee.reduced if fee else bool(member.reduced_fee), fee.paid_at if paid else None, method))
    return sorted(rows, key=lambda r: (r.club_name.casefold(), r.last_name.casefold(), r.first_name.casefold()))


@dataclass
class ClubSummary:
    club_id: uuid.UUID | None
    club_name: str
    members: int = 0
    paid: int = 0
    paid_amount: Decimal = Decimal("0")

    @property
    def unpaid(self) -> int:
        return self.members - self.paid


def summarize(rows: list[FeeRow]) -> list[ClubSummary]:
    by_club: dict[uuid.UUID | None, ClubSummary] = {}
    for row in rows:
        summary = by_club.setdefault(row.club_id, ClubSummary(row.club_id, row.club_name or "bez skupiny"))
        summary.members += 1
        if row.paid_at:
            summary.paid += 1
            summary.paid_amount += row.amount
    return sorted(by_club.values(), key=lambda s: s.club_name.casefold())
