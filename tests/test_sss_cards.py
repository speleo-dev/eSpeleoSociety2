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


@pytest.mark.db
def test_issue_verify_and_replace(session):
    club_id = _club(session)
    member_id = _member(session, club_id)
    with pytest.raises(PermissionDenied):
        sss_cards.issue(session, Actor(kind="member", id="x"), member_id, YEAR, "https://ess")
    with pytest.raises(DomainError):
        sss_cards.issue(session, SYSTEM, member_id, YEAR + 2, "https://ess")
    first = sss_cards.issue(session, SYSTEM, member_id, YEAR, "https://ess/")
    assert first.content.verify_url == f"https://ess/k/{first.code}" and first.content.club_name == "JS Žiadosť"
    assert first.card.code_hash == sss_cards.hash_code(first.code)
    check = sss_cards.verify(session, first.code)
    assert check.outcome == sss_cards.CardOutcome.VALID and check.year == YEAR
    second = sss_cards.issue(session, SYSTEM, member_id, YEAR, "https://ess")
    assert sss_cards.verify(session, first.code).outcome == sss_cards.CardOutcome.INVALID  # replaced
    assert sss_cards.verify(session, second.code).outcome == sss_cards.CardOutcome.VALID
    last_year = sss_cards.issue(session, SYSTEM, member_id, YEAR - 1, "https://ess")
    assert sss_cards.verify(session, last_year.code).outcome == sss_cards.CardOutcome.OTHER_YEAR
    members.expel_member(session, SYSTEM, member_id, "test")
    assert sss_cards.verify(session, second.code).outcome == sss_cards.CardOutcome.INVALID
    with pytest.raises(DomainError):
        sss_cards.issue(session, SYSTEM, member_id, YEAR, "https://ess")


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
    assert "odoslaná e-mailom" in page and f"vydaná na rok {YEAR}" in page
    [mail] = mailer.sent
    assert mail.attachments[0][0] == f"karticka-sss-{YEAR}.pdf"
    with migrated_db() as s:
        assert len(s.scalars(select(SssCard).where(SssCard.revoked_at.is_(None))).all()) == 1

    card = sss_cards.issue  # the code is only inside the PDF; issue one directly for the public page
    with migrated_db() as s:
        issued = card(s, SYSTEM, member_id, YEAR, "https://ess")
        s.commit()
    public = client.get(f"/k/{issued.code}")
    assert "Člen Slovenskej speleologickej spoločnosti" in public.text
    assert f"Členské zaplatené na rok {YEAR}" in public.text and "Ján" not in public.text
    assert public.headers["cache-control"] == "no-store"
    assert "nepodarilo overiť" in client.get("/k/nonsense").text
