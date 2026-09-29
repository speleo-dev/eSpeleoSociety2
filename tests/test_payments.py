"""Phase 3: fees, payment references, PAYMe link, bulk payment, manual and bank payments (R35, R36)."""

import re
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from ess.models import Fee, MembershipStatus, PaymentReference
from ess.services import payments, positions, settings
from ess.services.access import SYSTEM, Actor, DomainError, PermissionDenied
from tests.test_ecp_application import _club, _member
from tests.test_web_admin import client, csrf, google, login  # noqa: F401 (fixtures)

YEAR = 2027
EXAMPLE_IBAN = "SK3112000000198742637541"  # public example IBAN, not a real account


def test_code_format():
    codes = {payments.new_code() for _ in range(200)}
    assert len(codes) == 200
    assert all(re.fullmatch(r"[A-HJ-NP-Z2-9]{12}", c) for c in codes)


@pytest.mark.db
def test_iban_setting_is_validated(session):
    settings.set_setting(session, SYSTEM, "payment_iban", "sk31 1200 0000 1987 4263 7541")
    assert settings.get_setting(session, "payment_iban") == EXAMPLE_IBAN
    with pytest.raises(DomainError):
        settings.set_setting(session, SYSTEM, "payment_iban", "SK3112000000198742637542")  # wrong check digits


@pytest.mark.db
def test_member_reference_is_stable_and_payme_link(session):
    club_id = _club(session)
    member_id = _member(session, club_id)
    with pytest.raises(PermissionDenied):
        payments.member_reference(session, Actor(kind="member", id="00000000-0000-0000-0000-000000000000"),
                                  member_id, YEAR)
    ref = payments.member_reference(session, Actor(kind="member", id=str(member_id)), member_id, YEAR)
    assert payments.member_reference(session, SYSTEM, member_id, YEAR).id == ref.id
    assert ref.expected_amount == Decimal("15.00") and ref.kind == "member"

    with pytest.raises(DomainError) as exc:
        payments.payme_url(session, ref)
    assert exc.value.code == "payment_account_not_configured"
    settings.set_setting(session, SYSTEM, "payment_iban", EXAMPLE_IBAN)
    url = payments.payme_url(session, ref)
    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://payme.sk?")
    assert query["IBAN"] == [EXAMPLE_IBAN] and query["AM"] == ["15.00"] and query["CC"] == ["EUR"]
    assert query["PI"] == [ref.code] and query["MSG"] == [f"Clenske SSS {YEAR}"]


@pytest.mark.db
def test_fee_amount_is_fixed_when_assessed(session):
    club_id = _club(session)
    member_id = _member(session, club_id, reduced_fee=True)
    ref = payments.member_reference(session, SYSTEM, member_id, YEAR)
    assert ref.expected_amount == Decimal("7.00")
    settings.set_setting(session, SYSTEM, "reduced_fee_amount", "8")
    assert payments.get_fee(session, member_id, YEAR).amount == Decimal("7.00")
    assert payments.get_fee(session, member_id, YEAR).reduced


@pytest.mark.db
def test_partial_then_full_payment(session):
    club_id = _club(session)
    member_id = _member(session, club_id)
    ref = payments.member_reference(session, SYSTEM, member_id, YEAR)
    out = payments.apply_payment(session, SYSTEM, ref, Decimal("10"))
    assert out.result == "partial" and out.remaining == Decimal("5.00") and ref.status == "partial"
    assert payments.get_fee(session, member_id, YEAR).paid_at is None
    settings.set_setting(session, SYSTEM, "payment_iban", EXAMPLE_IBAN)
    assert "AM=5.00" in payments.payme_url(session, ref)  # the same reference for the rest
    assert payments.member_reference(session, SYSTEM, member_id, YEAR).id == ref.id

    out = payments.apply_payment(session, SYSTEM, ref, Decimal("5"))
    fee = payments.get_fee(session, member_id, YEAR)
    assert out.result == "paid" and ref.status == "paid" and fee.paid_at and fee.payment_reference_id == ref.id
    assert out.paid_fee_ids == [fee.id] and session.info["paid_fees"] == [fee.id]
    with pytest.raises(DomainError):
        payments.member_reference(session, SYSTEM, member_id, YEAR)

    again = payments.apply_payment(session, SYSTEM, ref, Decimal("15"))  # paid twice
    assert again.result == "overpaid" and again.overpaid == Decimal("15.00")


@pytest.mark.db
def test_bulk_payment_candidates_and_overpayment(session):
    club_id = _club(session)
    chair_id = _member(session, club_id, first_name="Predseda", card_number="1")
    positions.assign_position(session, SYSTEM, "club_chair", chair_id, club_id)
    chair = Actor(kind="member", id=str(chair_id))
    a = _member(session, club_id, first_name="Anna", card_number="2")
    b = _member(session, club_id, first_name="Boris", card_number="3", reduced_fee=True)
    _member(session, club_id, MembershipStatus.CANDIDATE, first_name="Čakateľ", card_number="4")
    payments.mark_paid(session, SYSTEM, chair_id, YEAR, "hotovosť na schôdzi")

    other = _club(session, "JS Iná")
    with pytest.raises(PermissionDenied):
        payments.bulk_candidates(session, chair, other, YEAR)
    offered = payments.bulk_candidates(session, chair, club_id, YEAR)
    assert [c.member_id for c in offered] == [a, b]  # sorted by name; no candidate, no paid member
    assert [c.amount for c in offered] == [Decimal("15.00"), Decimal("7.00")]

    own = payments.member_reference(session, SYSTEM, a, YEAR)  # Anna also has her own link
    bulk = payments.create_bulk(session, chair, club_id, YEAR, [a, b])
    assert bulk.kind == "bulk" and bulk.expected_amount == Decimal("22.00") and bulk.club_id == club_id
    assert payments.bulk_candidates(session, chair, club_id, YEAR) == []  # already in an open bulk payment
    with pytest.raises(DomainError):
        payments.create_bulk(session, chair, club_id, YEAR, [a])

    payments.apply_payment(session, SYSTEM, own, Decimal("15"))  # Anna paid herself first
    out = payments.apply_payment(session, SYSTEM, bulk, Decimal("22"))
    assert out.result == "overpaid" and out.overpaid == Decimal("15.00")  # refund or gift (task)
    assert all(payments.get_fee(session, m, YEAR).paid_at for m in (a, b))


@pytest.mark.db
def test_manual_payment_cancels_own_link(session):
    club_id = _club(session)
    member_id = _member(session, club_id)
    ref = payments.member_reference(session, SYSTEM, member_id, YEAR)
    with pytest.raises(PermissionDenied):
        payments.mark_paid(session, Actor(kind="member", id=str(member_id)), member_id, YEAR, "x")
    with pytest.raises(DomainError):
        payments.mark_paid(session, SYSTEM, member_id, YEAR, "  ")
    fee = payments.mark_paid(session, SYSTEM, member_id, YEAR, "zaplatil v hotovosti")
    assert fee.paid_manually_by == "system" and fee.payment_reference_id is None
    assert ref.status == "cancelled"
    assert payments.apply_payment(session, SYSTEM, ref, Decimal("15")).result == "overpaid"
    with pytest.raises(DomainError):
        payments.mark_paid(session, SYSTEM, member_id, YEAR, "znova")


@pytest.mark.db
def test_find_reference_and_cancel_bulk(session):
    club_id = _club(session)
    a = _member(session, club_id)
    bulk = payments.create_bulk(session, SYSTEM, club_id, YEAR, [a])
    assert payments.find_reference(session, " " + bulk.code.lower()[:6] + " " + bulk.code[6:]).id == bulk.id
    assert payments.find_reference(session, "SHORT") is None
    payments.cancel_reference(session, SYSTEM, bulk.id)
    assert bulk.status == "cancelled"
    assert [c.member_id for c in payments.bulk_candidates(session, SYSTEM, club_id, YEAR)] == [a]
    assert session.scalar(select(Fee).where(Fee.member_id == a)).paid_at is None
    assert session.scalar(select(PaymentReference).where(PaymentReference.id == bulk.id)).status == "cancelled"


@pytest.mark.db
def test_admin_pages_member_link_manual_payment_and_bulk(migrated_db, google, client):
    with migrated_db() as session:
        club_id = _club(session)
        a = _member(session, club_id, first_name="Anna", card_number="2")
        b = _member(session, club_id, first_name="Boris", card_number="3")
        session.commit()
    login(client, google)
    token = csrf(client)
    this_year = date.today().year

    # no IBAN yet: the link page explains what is missing
    r = client.post(f"/admin/members/{a}/payment-link", data={"csrf_token": token, "year": this_year},
                    follow_redirects=False)
    page = client.get(r.headers["location"]).text
    assert "Nie je nastavený IBAN" in page and "15,00 €" in page
    client.post("/admin/settings", data={"csrf_token": token, "payment_iban": EXAMPLE_IBAN})
    page = client.get(r.headers["location"]).text
    assert "https://payme.sk?V=1&amp;IBAN=" + EXAMPLE_IBAN in page

    r = client.post(f"/admin/members/{a}/fee-paid", data={"csrf_token": token, "year": this_year, "note": "hotovosť"})
    assert "označené ako zaplatené" in r.text and "ručne: hotovosť" in r.text

    page = client.get(f"/admin/clubs/{club_id}/bulk-payment").text
    assert "Boris" in page and "Anna" not in page
    r = client.post(f"/admin/clubs/{club_id}/bulk-payment",
                    data={"csrf_token": token, "year": this_year, "member_id": [str(b)]}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/payments/")
    page = client.get(r.headers["location"]).text
    assert "Hromadná platba" in page and "Boris" in page and "Zrušiť platobný odkaz" in page
