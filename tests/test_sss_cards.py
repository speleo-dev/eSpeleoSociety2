"""Kartička SSS: PDF, yearly code, verification page with only membership and the paid year."""

import re
from datetime import date

import pytest
from sqlalchemy import select

from ess.cards import CardContent, render_card_pdf
from ess.mail import MemoryMailer, get_mailer
from ess.models import MembershipStatus, SssCard
from ess.services import members, sss_cards
from ess.services.access import SYSTEM, Actor, DomainError, PermissionDenied
from tests.test_ecp_application import _club, _member

YEAR = date.today().year


def test_pdf_renders_slovak_text():
    pdf = render_card_pdf(CardContent("Ing. Ľubomír Šťastný, PhD.", "Jaskyniarska skupina Demänová", "1234", YEAR,
                                      "https://ess.example/k/abc"))
    assert pdf.startswith(b"%PDF") and b"DejaVu" in pdf and len(pdf) < 200_000


def _code(issued) -> str:
    return issued.content.verify_url.rsplit("/", 1)[1]


@pytest.mark.db
def test_one_card_per_year_again_and_replacement(session):
    club_id = _club(session)
    member_id = _member(session, club_id)
    with pytest.raises(PermissionDenied):
        sss_cards.issue(session, Actor(kind="member", id="x"), member_id, YEAR, "https://ess")
    with pytest.raises(DomainError):
        sss_cards.issue(session, SYSTEM, member_id, YEAR + 2, "https://ess")
    first = sss_cards.issue(session, SYSTEM, member_id, YEAR, "https://ess/")
    code = _code(first)
    assert first.content.verify_url == f"https://ess/k/{code}" and first.content.club_name == "JS Žiadosť"
    assert first.card.code_hash == sss_cards.hash_code(code) and code.encode() not in first.card.code_enc
    assert sss_cards.verify(session, code).outcome == sss_cards.CardOutcome.VALID

    with pytest.raises(DomainError) as exc:  # a second card of the same year only as a replacement
        sss_cards.issue(session, SYSTEM, member_id, YEAR, "https://ess")
    assert exc.value.code == "card_already_issued"
    assert _code(sss_cards.again(session, SYSTEM, first.card.id, "https://ess")) == code  # same QR

    with pytest.raises(DomainError):
        sss_cards.replace(session, SYSTEM, first.card.id, "whatever", "https://ess")
    new = sss_cards.replace(session, SYSTEM, first.card.id, "stolen", "https://ess")
    assert sss_cards.verify(session, code).outcome == sss_cards.CardOutcome.STOLEN
    assert sss_cards.verify(session, _code(new)).outcome == sss_cards.CardOutcome.VALID
    with pytest.raises(DomainError):
        sss_cards.again(session, SYSTEM, first.card.id, "https://ess")  # the old card is gone

    last_year = sss_cards.issue(session, SYSTEM, member_id, YEAR - 1, "https://ess")
    assert sss_cards.verify(session, _code(last_year)).outcome == sss_cards.CardOutcome.OTHER_YEAR
    members.expel_member(session, SYSTEM, member_id, "test")
    assert sss_cards.verify(session, _code(new)).outcome == sss_cards.CardOutcome.INVALID
    with pytest.raises(DomainError):
        sss_cards.issue(session, SYSTEM, member_id, YEAR + 1, "https://ess")


@pytest.mark.db
def test_web_download_email_and_public_page(migrated_db, monkeypatch):
    from fastapi.testclient import TestClient

    from ess.config import get_settings
    from ess.main import create_app
    from ess.web import auth
    from tests.test_web_admin import FakeGoogle

    monkeypatch.setenv("ESS_GOOGLE_CLIENT_ID", "123-test.apps.googleusercontent.com")
    monkeypatch.setenv("ESS_GOOGLE_CLIENT_SECRET", "test-secret")
    get_settings.cache_clear()
    google = FakeGoogle()
    monkeypatch.setattr(auth, "_google", lambda: google)
    mailer = MemoryMailer()
    app = create_app()
    app.dependency_overrides[get_mailer] = lambda: mailer
    client = TestClient(app)
    with migrated_db() as s:
        member_id = _member(s, _club(s))
        s.commit()
    google.userinfo = {"email": "super@example.org", "email_verified": True, "name": "Admin"}
    client.get("/admin/auth/callback")
    page = client.get(f"/admin/members/{member_id}").text
    assert "Vydať kartičku SSS" in page
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    response = client.post(f"/admin/members/{member_id}/card", data={"csrf_token": csrf, "year": YEAR})
    assert response.headers["content-type"] == "application/pdf" and response.content.startswith(b"%PDF")
    page = client.post(f"/admin/members/{member_id}/card",
                       data={"csrf_token": csrf, "year": YEAR, "delivery": "email"}).text
    assert "Na tento rok už kartička vydaná je" in page and mailer.sent == []
    with migrated_db() as s:
        card = s.scalar(select(SssCard))
        code = _code(sss_cards.again(s, SYSTEM, card.id, "https://ess"))
    page = client.post(f"/admin/cards/{card.id}/again",
                       data={"csrf_token": csrf, "member_id": str(member_id), "delivery": "email"}).text
    assert "odoslaná e-mailom" in page
    [mail] = mailer.sent
    assert mail.attachments[0][0] == f"karticka-sss-{YEAR}.pdf"
    public = client.get(f"/k/{code}")
    assert "Člen Slovenskej speleologickej spoločnosti" in public.text
    assert f"Členské zaplatené na rok {YEAR}" in public.text and "Ján" not in public.text
    assert public.headers["cache-control"] == "no-store"
    assert "nepodarilo overiť" in client.get("/k/nonsense").text
    response = client.post(f"/admin/cards/{card.id}/replace",
                           data={"csrf_token": csrf, "member_id": str(member_id), "reason": "lost"})
    assert response.headers["content-type"] == "application/pdf"
    assert "nahlásená ako stratená" in client.get(f"/k/{code}").text
    assert "nahlásená ako stratená" in client.get(f"/admin/members/{member_id}").text
