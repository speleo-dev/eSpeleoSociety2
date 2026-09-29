"""Bank statements: camt.053 parser, matching payments to references, payment tasks (R35, R36)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from ess.banking import StatementError, camt053
from ess.models import BankTransaction, Task
from ess.services import bank_statements, outbox, payments, settings
from ess.services.access import SYSTEM, Actor, DomainError, PermissionDenied
from tests.test_ecp_application import _club, _member
from tests.test_payments import EXAMPLE_IBAN, YEAR
from tests.test_web_admin import client, csrf, google, login  # noqa: F401 (fixtures)

NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"


def _entry(ref: str, amount: str, e2e: str = "NOTPROVIDED", message: str = "", sign: str = "CRDT",
           name: str = "Ján Platiteľ") -> str:
    return f"""<Ntry><NtryRef>{ref}</NtryRef><Amt Ccy="EUR">{amount}</Amt><CdtDbtInd>{sign}</CdtDbtInd>
      <Sts>BOOK</Sts><BookgDt><Dt>2026-09-30</Dt></BookgDt><AcctSvcrRef>{ref}</AcctSvcrRef>
      <NtryDtls><TxDtls><Refs><EndToEndId>{e2e}</EndToEndId></Refs>
        <RltdPties><Dbtr><Nm>{name}</Nm></Dbtr><DbtrAcct><Id><IBAN>SK0000000000000000000000</IBAN></Id></DbtrAcct></RltdPties>
        <RmtInf><Ustrd>{message}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>"""


def _statement(*entries: str) -> bytes:
    return (f'<?xml version="1.0" encoding="UTF-8"?><Document xmlns="{NS}"><BkToCstmrStmt><GrpHdr><MsgId>1</MsgId>'
            f'</GrpHdr><Stmt><Id>1</Id>{"".join(entries)}</Stmt></BkToCstmrStmt></Document>').encode()


def test_camt053_incoming_payments_only():
    txs = camt053.parse(_statement(_entry("A1", "15.00", "97PQQPTDHRC3", "Clenske SSS"),
                                   _entry("A2", "3.50", sign="DBIT")))
    [tx] = txs
    assert tx.bank_ref == "A1" and tx.amount == Decimal("15.00") and tx.currency == "EUR"
    assert tx.booked_on == date(2026, 9, 30) and tx.payer_reference == "97PQQPTDHRC3"
    assert tx.payer_name == "Ján Platiteľ" and tx.message == "Clenske SSS"
    assert camt053.parse(_statement(_entry("A3", "1")))[0].payer_reference is None  # NOTPROVIDED


def test_camt053_rejects_invalid_and_dtd():
    with pytest.raises(StatementError):
        camt053.parse(b"not xml")
    with pytest.raises(StatementError):
        camt053.parse(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><Document>&a;</Document>')


def _ref(session):
    settings.set_setting(session, SYSTEM, "payment_iban", EXAMPLE_IBAN)
    club_id = _club(session)
    member_id = _member(session, club_id)
    return member_id, payments.member_reference(session, SYSTEM, member_id, YEAR)


def _import(session, *entries):
    return bank_statements.import_statement(session, SYSTEM, "camt053", _statement(*entries))


@pytest.mark.db
def test_full_partial_and_duplicate_payments(session):
    member_id, ref = _ref(session)
    with pytest.raises(PermissionDenied):
        bank_statements.import_statement(session, Actor(kind="member", id=str(member_id)), "camt053", b"")
    result = _import(session, _entry("B1", "10.00", ref.code))
    assert result.counts == {"partial": 1}
    [mail] = outbox.take(session)
    assert mail.template == "payment_partial" and mail.context["remaining"] == Decimal("5.00")
    assert "AM=5.00" in mail.context["payme_url"]
    with pytest.raises(DomainError):  # the same file again
        _import(session, _entry("B1", "10.00", ref.code))

    result = _import(session, _entry("B1", "10.00", ref.code), _entry("B2", "5.00", message=f"clenske {ref.code}"))
    assert result.duplicates == 1 and result.counts == {"paid": 1}  # code found in the message
    assert payments.get_fee(session, member_id, YEAR).paid_at is not None
    tx = session.scalar(select(BankTransaction).where(BankTransaction.bank_ref == "B2"))
    assert b"Platite" not in tx.payer_name_enc and tx.payment_reference_id == ref.id


@pytest.mark.db
def test_unknown_reference_task_and_manual_assignment(session):
    member_id, ref = _ref(session)
    result = _import(session, _entry("C1", "15.00", "UNKNOWN12345", name="Mama Člena"))
    assert result.counts == {"unknown_reference": 1}
    task = session.scalar(select(Task).where(Task.task_type == "payment_unmatched"))
    assert task.member_id is None and task.context["amount"] == "15.00" and "Mama" not in str(task.context)
    view = bank_statements.view(session, task.bank_transaction_id)
    assert view.payer_name == "Mama Člena"

    with pytest.raises(DomainError):
        bank_statements.assign(session, SYSTEM, task.id, "NEEXISTUJE12")
    assert bank_statements.assign(session, SYSTEM, task.id, ref.code.lower()) == "paid"
    assert task.status == "done" and task.resolution == "assigned"
    assert payments.get_fee(session, member_id, YEAR).paid_at is not None
    assert session.get(BankTransaction, task.bank_transaction_id).result == "manual"


@pytest.mark.db
def test_overpayment_task_and_resolution(session):
    member_id, ref = _ref(session)
    _import(session, _entry("D1", "20.00", ref.code))
    task = session.scalar(select(Task).where(Task.task_type == "payment_overpaid"))
    assert task.member_id == member_id and task.context["overpaid"] == "5.00" and task.context["code"] == ref.code
    assert payments.get_fee(session, member_id, YEAR).paid_at is not None
    with pytest.raises(DomainError):
        bank_statements.resolve(session, SYSTEM, task.id, " ")
    with pytest.raises(DomainError):
        bank_statements.assign(session, SYSTEM, task.id, ref.code)  # only for unknown references
    bank_statements.resolve(session, SYSTEM, task.id, "vrátené na účet")
    assert task.status == "done" and task.resolution_note == "vrátené na účet"


@pytest.mark.db
def test_web_upload_and_task_actions(migrated_db, google, client):
    from ess.mail import MemoryMailer, get_mailer

    mailer = MemoryMailer()
    client.app.dependency_overrides[get_mailer] = lambda: mailer
    with migrated_db() as session:
        member_id, ref = _ref(session)
        code = ref.code
        session.commit()
    login(client, google)
    token = csrf(client)
    files = {"file": ("vypis.xml", _statement(_entry("E1", "7.00", code), _entry("E2", "1.00", "XXXXXXXXXXXX")),
                      "text/xml")}
    r = client.post("/admin/statements", data={"csrf_token": token, "format": "camt053"}, files=files)
    assert "Výpis bol spracovaný" in r.text and "Čiastočne zaplatené: 1" in r.text
    assert mailer.sent[0].subject == f"Neúplná platba členského SSS na rok {YEAR}" and "8,00 €" in mailer.sent[0].text
    r = client.post("/admin/statements", data={"csrf_token": token, "format": "camt053"}, files=files)
    assert "už bol nahratý" in r.text

    page = client.get("/admin/tasks").text
    assert "Nespárovaná platba" in page and "Platiteľ: Ján Platiteľ" in page
    with migrated_db() as session:
        task_id = session.scalar(select(Task.id).where(Task.task_type == "payment_unmatched"))
    r = client.post(f"/admin/tasks/{task_id}/resolve-payment", data={"csrf_token": token, "note": "vrátené"})
    assert "Požiadavka bola vybavená" in r.text
