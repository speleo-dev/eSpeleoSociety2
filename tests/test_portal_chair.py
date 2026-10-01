"""Phase 5: the chair (or delegate) manages the club on the portal."""

import re
from datetime import date

import pytest
from sqlalchemy import select

from ess.models import EcpPass, Membership, Task
from ess.services import delegations, memberships, portal_auth, positions, settings
from ess.services.access import SYSTEM
from tests.test_ecp_application import _club, _member
from tests.test_payments import EXAMPLE_IBAN
from tests.test_web_admin import client  # noqa: F401 (fixture)

pytestmark = pytest.mark.db


@pytest.fixture
def club(migrated_db, client):
    with migrated_db() as session:
        club_id = _club(session)
        chair = _member(session, club_id, first_name="Predseda", card_number="1")
        positions.assign_position(session, SYSTEM, "club_chair", chair, club_id)
        helper = _member(session, club_id, first_name="Pomocník", card_number="2")
        plain = _member(session, club_id, first_name="Bežný", card_number="3")
        for m in (chair, helper, plain):
            session.add(EcpPass(member_id=m, wallet_object_id=f"i.{m}", state="active"))
        settings.set_setting(session, SYSTEM, "payment_iban", EXAMPLE_IBAN)
        tokens = {name: portal_auth.open_session(session, m, "email_code").token
                  for name, m in (("chair", chair), ("helper", helper), ("plain", plain))}
        session.commit()
    return {"id": club_id, "chair": chair, "helper": helper, "plain": plain, "tokens": tokens}


def _as(client, club, who) -> str:
    client.cookies.set("ess_member", club["tokens"][who])
    page = client.get("/portal").text
    return re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)


def test_chair_adds_candidate_and_proposes_member(migrated_db, client, club):
    token = _as(client, club, "chair")
    base = f"/portal/clubs/{club['id']}"
    r = client.post(f"{base}/members/new", data={"csrf_token": token, "first_name": "Nový", "last_name": "Čakateľ",
                                                 "status": "candidate"})
    assert "Čakateľ bol pridaný" in r.text and "Navrhnúť za člena" in r.text
    member_id = r.url.path.rsplit("/", 1)[1]
    with migrated_db() as session:
        ms = session.scalar(select(Membership).where(Membership.member_id == member_id, Membership.valid_to.is_(None)))
    r = client.post(f"{base}/memberships/{ms.id}/status", data={"csrf_token": token, "new_status": "pending_activation"})
    assert "Stav členstva bol zmenený" in r.text
    with migrated_db() as session:
        assert session.scalar(select(Task).where(Task.task_type == "member_activation")) is not None
    # a chair cannot activate
    with migrated_db() as session:
        ms = session.scalar(select(Membership).where(Membership.member_id == member_id, Membership.valid_to.is_(None)))
    r = client.post(f"{base}/memberships/{ms.id}/status", data={"csrf_token": token, "new_status": "member"})
    assert "Na túto akciu nemáte oprávnenie" in r.text

    r = client.post(f"{base}/members/{member_id}/edit", data={"csrf_token": token, "first_name": "Nový",
                                                              "last_name": "Upravený"})
    assert "Údaje boli uložené" in r.text and "Nový Upravený" in r.text


def test_suspend_terminate_and_card(migrated_db, client, club):
    token = _as(client, club, "chair")
    base = f"/portal/clubs/{club['id']}"
    with migrated_db() as session:
        ms = memberships.open_memberships(session, club["plain"])[0]
    r = client.post(f"{base}/memberships/{ms.id}/status", data={"csrf_token": token, "new_status": "suspended"})
    assert "Obnoviť členstvo" in r.text
    r = client.post(f"{base}/members/{club['helper']}/card", data={"csrf_token": token,
                                                                    "year": str(date.today().year),
                                                                    "card_format": "pdf"})
    assert r.headers["content-type"] == "application/pdf"
    with migrated_db() as session:
        ms = memberships.open_memberships(session, club["plain"])[0]
    r = client.post(f"{base}/memberships/{ms.id}/terminate", data={"csrf_token": token})
    assert "Členstvo v skupine bolo ukončené" in r.text


def test_only_manager_and_own_club(migrated_db, client, club):
    base = f"/portal/clubs/{club['id']}"
    token = _as(client, club, "plain")
    assert client.get(f"{base}/members/new").status_code == 403
    assert client.get(f"{base}/payments").status_code == 403
    with migrated_db() as session:
        other = _club(session, "JS Iná")
        stranger = _member(session, other, first_name="Cudzí", card_number="9")
        session.commit()
    token = _as(client, club, "chair")
    assert client.get(f"{base}/members/{stranger}").status_code == 403  # not in the club
    with migrated_db() as session:
        delegations.delegate(session, SYSTEM, club["id"], club["helper"])
        session.commit()
    assert client.get(f"{base}/members/new").status_code == 403  # represented chair only reads
    token = _as(client, club, "helper")
    assert client.get(f"{base}/members/new").status_code == 200
    assert token


def test_bulk_payment_on_portal(migrated_db, client, club):
    token = _as(client, club, "chair")
    base = f"/portal/clubs/{club['id']}"
    page = client.get(f"{base}/payments").text
    assert "Zaplatilo <strong>0</strong> z 3" in page and "sa otvorí po zverejnení ročnej známky" in page
    year = re.search(r"Členské (\d{4})", page).group(1)
    with migrated_db() as session:  # the year's sticker opens the bulk payment (R45)
        settings.set_setting(session, SYSTEM, f"sticker_url_{year}", "https://storage.example/s.png")
        session.commit()
    page = client.get(f"{base}/payments").text
    assert "Pomocník" in page
    r = client.post(f"{base}/payments", data={"csrf_token": token, "year": re.search(r'name="year" value="(\d+)"', page).group(1),
                                              "member_id": [str(club["helper"]), str(club["plain"])]})
    assert "Hromadná platba" in r.text and "30,00 €" in r.text and "payme.sk" in r.text
    r = client.post(r.url.path + "/cancel", data={"csrf_token": token})
    assert "Platobný odkaz bol zrušený" in r.text


# --- menu for members and chairs (R52) -----------------------------------------------------------------


def test_member_menu_pages(migrated_db, client, club):
    _as(client, club, "plain")
    with migrated_db() as session:
        other = _club(session, "JS Cudzia")
        session.commit()
    home = client.get("/portal").text
    for link in ('href="/portal/members"', 'href="/portal/clubs"', 'href="/portal/board"',
                 'href="/portal/documents"', 'href="/portal/notifications"'):
        assert link in home
    assert ">Domov<" not in home and "Administrácia" not in home and "menu-toggle" in home
    r = client.get("/portal/members", follow_redirects=False)
    assert r.headers["location"] == f"/portal/clubs/{club['id']}"  # one club: straight to it
    page = client.get("/portal/clubs").text
    assert "JS Cudzia" in page and "moja" in page
    page = client.get(f"/portal/clubs/{other}").text
    assert "Členov skupiny vidia len jej členovia" in page and "Pomocník" not in page
    page = client.get(f"/portal/clubs/{club['id']}").text
    assert "Pomocník" in page and "Upraviť údaje skupiny" not in page
    assert client.get(f"/portal/clubs/{club['id']}/edit").status_code == 403
    for path in ("/portal/board", "/portal/documents", "/portal/notifications"):
        assert client.get(path).status_code == 200, path
    assert "Predseda skupiny" not in client.get("/portal/board").text  # chairs are listed with the clubs
    assert "Predseda" in client.get("/portal/clubs").text


def test_chair_edits_club_contacts(migrated_db, client, club):
    token = _as(client, club, "chair")
    base = f"/portal/clubs/{club['id']}"
    assert "Upraviť údaje skupiny" in client.get(base).text
    r = client.post(f"{base}/edit", data={"csrf_token": token, "city": "Liptovský Mikuláš", "email": "zly",
                                          "country": "SK"})
    assert r.status_code == 400
    r = client.post(f"{base}/edit", data={"csrf_token": token, "city": "Liptovský Mikuláš",
                                          "email": "js@example.org", "country": "SK", "web": "https://js.example.org"})
    assert "Údaje skupiny boli uložené" in r.text and "Liptovský Mikuláš" in r.text and "js@example.org" in r.text


def test_role_badge_in_header(migrated_db, client, club):
    _as(client, club, "chair")
    assert 'role-badge role-chair">Predseda<' in client.get("/portal").text
    _as(client, club, "plain")
    assert 'role-badge role-member">Člen<' in client.get("/portal").text


def test_member_icons_by_role(migrated_db, client, club):
    """R54: chair icon first; reduced fee and eCP icons for the chair, not for ordinary members."""
    _as(client, club, "chair")
    page = client.get(f"/portal/clubs/{club['id']}").text
    assert 'title="predseda skupiny"' in page and 'title="vydaný eCP (Google Wallet)"' in page
    _as(client, club, "plain")
    page = client.get(f"/portal/clubs/{club['id']}").text
    assert 'title="predseda skupiny"' in page and "vydaný eCP" not in page
