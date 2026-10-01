"""Admin path (R48), new member from a club page, the SSS card choice (R47) and pass links."""

import re
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ess.models import Member, SssCard
from ess.services import ecp_applications as apps
from ess.services import ecp_issuance, payments, sss_cards
from ess.services.access import SYSTEM, Actor, PermissionDenied
from ess.storage import MemoryMediaStore
from ess.wallet import MemoryWalletClient, PassContent, build_pass_object
from tests.test_ecp_application import _club, _form, _member, _photo
from tests.test_web_admin import client, csrf, google, login  # noqa: F401 (fixtures)

ADMIN = Actor(kind="admin", id="admin-1")


def test_pass_has_no_own_website_link():
    """The SSS website link comes from the pass class; the object adds only payment and portal links."""
    obj = build_pass_object(PassContent(object_id="x.y", member_name="Ján", club_name="JS", card_number="1",
                                        member_since=None, birth_date=None, photo_url="p", check_url="c",
                                        portal_url="https://ess/p/k"))
    assert [u["id"] for u in obj["linksModuleData"]["uris"]] == ["portal"]


@pytest.mark.db
def test_admin_under_secret_path(migrated_db, google, monkeypatch):  # noqa: F811
    from ess.config import get_settings
    from ess.main import create_app

    monkeypatch.setenv("ESS_ADMIN_PATH", "sprava-x7Kq2")
    get_settings.cache_clear()
    client = TestClient(create_app())
    assert "/admin" not in client.get("/").text and "/sprava-x7Kq2" not in client.get("/").text
    assert client.get("/admin").status_code == 404 and client.get("/admin/auth/callback").status_code == 404
    page = client.get("/sprava-x7Kq2")
    assert page.status_code == 401 and 'href="/sprava-x7Kq2/login"' in page.text
    google.userinfo = {"email": "super@example.org", "email_verified": True, "name": "Admin"}
    r = client.get("/sprava-x7Kq2/auth/callback", follow_redirects=False)
    assert r.headers["location"] == "/sprava-x7Kq2"
    page = client.get("/sprava-x7Kq2/members").text
    assert 'href="/sprava-x7Kq2/members/new"' in page and 'href="/admin' not in page


def test_admin_path_is_validated(monkeypatch):
    from pydantic import ValidationError

    from ess.config import Settings

    for bad in ("ab", "a/b/c", "static", "x y z q"):
        monkeypatch.setenv("ESS_ADMIN_PATH", bad)
        with pytest.raises(ValidationError):
            Settings()


@pytest.mark.db
def test_admin_new_member_from_club_page(migrated_db, google, client):  # noqa: F811
    with migrated_db() as session:
        club_id = _club(session)
        session.commit()
    login(client, google)
    page = client.get(f"/admin/clubs/{club_id}").text
    assert f'href="/admin/members/new?club={club_id}"' in page
    page = client.get(f"/admin/members/new?club={club_id}").text
    assert f'name="club_id" value="{club_id}"' in page and "<select name=\"club_id\"" not in page
    assert "<select name=\"club_id\"" in client.get("/admin/members/new").text  # from the SSS list: chosen
    r = client.post("/admin/members/new", data={"csrf_token": csrf(client), "first_name": "Nový", "last_name": "Člen",
                                                "club_id": str(club_id), "club_fixed": "1", "status": "member"})
    assert "Člen bol pridaný" in r.text


@pytest.mark.db
def test_card_format_chosen_by_chair_is_not_asked_again(session):
    club_id = _club(session)
    member_id = _member(session, club_id)
    with pytest.raises(PermissionDenied):
        sss_cards.set_format(session, Actor(kind="member", id=str(member_id)), member_id, "png")
    sss_cards.set_format(session, ADMIN, member_id, "png")
    mail = apps.start_public(session, _form(club_id))
    app = apps.verify_email(session, mail.token)
    assert not apps.asks_for_card(session, app.id)
    apps.submit_photo(session, app.id, _photo(), None, True, True, "pdf", MemoryMediaStore())
    assert app.card_format is None and session.get(Member, member_id).card_format == "png"


@pytest.mark.db
def test_card_wanted_in_application_is_sent_after_approval_when_paid(session):
    from ess.services import outbox

    club_id = _club(session)
    member_id = _member(session, club_id)
    year = date.today().year
    payments.mark_paid(session, SYSTEM, member_id, year, "hotovosť")
    mail = apps.start_public(session, _form(club_id))
    app = apps.verify_email(session, mail.token)
    assert apps.asks_for_card(session, app.id)
    store = MemoryMediaStore()
    apps.submit_photo(session, app.id, _photo(), None, True, True, "png", store)
    outbox.discard(session)
    ecp_issuance.approve(session, ADMIN, app.id, store, MemoryWalletClient(), "https://ess")
    assert session.get(Member, member_id).card_format == "png"
    assert session.scalar(select(SssCard.year).where(SssCard.member_id == member_id)) == year
    assert [m.template for m in outbox.take(session)] == ["sss_card"]


@pytest.mark.db
def test_apply_page_describes_ecp_and_card(client):  # noqa: F811
    page = client.get("/ecp/apply").text
    assert "Peňaženka Google" in page and "play.google.com" in page and "preview-ecp.png" in page
    assert "obrázok (PNG)" in page and "preview-card.png" in page
    assert re.search(r"Nie je to plastová karta", page)
