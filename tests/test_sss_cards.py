"""Kartička SSS: PDF, yearly code, verification page with only membership and the paid year."""

import re
from datetime import date

import pytest
from sqlalchemy import select

from ess.cards import CardContent, render_card_pdf
from ess.mail import MemoryMailer, get_mailer
from ess.models import MembershipStatus, SssCard
from ess.services import members, settings, sss_cards
from ess.services.access import SYSTEM, Actor, DomainError, PermissionDenied
from tests.test_ecp_application import _club, _member

YEAR = date.today().year


def test_png_card():
    import io

    from PIL import Image

    from ess.cards import PNG_SIZE, render_card

    data, mime, name = render_card(CardContent("Ján Vzorový", "JS Demänová", None, YEAR, "https://e/k/x"), "png")
    assert mime == "image/png" and name == f"karticka-sss-{YEAR}.png"
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == PNG_SIZE


@pytest.mark.db
def test_allowed_years_follow_payment_period(session):
    settings.set_setting(session, SYSTEM, "renewal_window_days", "60")
    assert sss_cards.allowed_years(session, date(2026, 6, 1)) == [2026]
    assert sss_cards.allowed_years(session, date(2026, 11, 5)) == [2026, 2027]


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
        sss_cards.issue(session, Actor(kind="member", id=str(member_id)), member_id, YEAR, "https://ess")
    with pytest.raises(DomainError):
        sss_cards.issue(session, SYSTEM, member_id, YEAR + 2, "https://ess")
    first = sss_cards.issue(session, SYSTEM, member_id, YEAR, "https://ess/", "png")
    assert first.card_format == "png"
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
    with pytest.raises(DomainError) as exc:  # replaced or not, the year's card was issued – no second first card
        sss_cards.issue(session, SYSTEM, member_id, YEAR, "https://ess")
    assert exc.value.code == "card_already_issued"

    old = sss_cards.SssCard(member_id=member_id, year=YEAR - 1, code_hash=sss_cards.hash_code("old"),
                            code_enc=None)
    session.add(old)
    session.flush()
    assert sss_cards.verify(session, "old").outcome == sss_cards.CardOutcome.OTHER_YEAR
    members.expel_member(session, SYSTEM, member_id, "test")
    assert sss_cards.verify(session, _code(new)).outcome == sss_cards.CardOutcome.INVALID


@pytest.mark.db
def test_club_chair_issues_the_first_card_only(session):
    from ess.services import positions

    club_id = _club(session)
    chair_id = _member(session, club_id, first_name="Predseda", card_number="9")
    positions.assign_position(session, SYSTEM, "club_chair", chair_id, club_id=club_id)
    member_id = _member(session, club_id, first_name="Karol", card_number="8")
    chair = Actor(kind="member", id=str(chair_id))
    issued = sss_cards.issue(session, chair, member_id, YEAR, "https://ess")
    with pytest.raises(PermissionDenied):
        sss_cards.replace(session, chair, issued.card.id, "lost", "https://ess")
    stranger = _member(session, _club(session, "JS Iná"), first_name="Cudzí", card_number="7")
    with pytest.raises(PermissionDenied):
        sss_cards.issue(session, chair, stranger, YEAR, "https://ess")


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
    from tests.test_web_admin import login as _login

    _login(client, google)  # administrator (R50)
    page = client.get(f"/admin/members/{member_id}").text
    assert "Vydať kartičku SSS" in page
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    response = client.post(f"/admin/members/{member_id}/card", data={"csrf_token": csrf, "year": YEAR})
    assert response.headers["content-type"] == "application/pdf" and response.content.startswith(b"%PDF")
    assert "Vydať kartičku SSS" not in client.get(f"/admin/members/{member_id}").text  # issued once
    page = client.post(f"/admin/members/{member_id}/card",
                       data={"csrf_token": csrf, "year": YEAR, "delivery": "email"}).text
    assert "Na tento rok už kartička vydaná bola" in page and mailer.sent == []
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
                           data={"csrf_token": csrf, "member_id": str(member_id), "reason": "lost", "card_format": "png"})
    assert response.headers["content-type"] == "image/png"
    assert "nahlásená ako stratená" in client.get(f"/k/{code}").text
    assert "nahlásená ako stratená" in client.get(f"/admin/members/{member_id}").text


@pytest.mark.db
def test_web_new_member_with_card(migrated_db, monkeypatch):
    from fastapi.testclient import TestClient

    from ess.config import get_settings
    from ess.main import create_app
    from ess.models import Member
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
        club_id = _club(s)
        s.commit()
    from tests.test_web_admin import login as _login

    _login(client, google)  # administrator (R50)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/admin/members/new").text).group(1)
    page = client.post("/admin/members/new", data={
        "csrf_token": csrf, "first_name": "Nový", "last_name": "Člen", "email": "novy@example.org",
        "club_id": str(club_id), "status": "member", "issue_card": "on", "card_year": str(YEAR),
        "card_format": "png"}).text
    assert "Kartička SSS mu bola poslaná e-mailom" in page
    [mail] = mailer.sent
    assert mail.attachments[0][0].endswith(".png")
    with migrated_db() as s:
        assert s.scalar(select(Member.card_format)) == "png"
