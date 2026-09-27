"""Administration web pages: Google sign-in (mocked), authorization, CSRF and main actions."""

import re
import uuid
from datetime import date

import pytest
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from sqlalchemy import select

from ess.audit import AuditLog
from ess.models import AdminRole, Club, MembershipStatus as S
from ess.services import admin_access, members, memberships
from ess.services.access import SYSTEM
from ess.services.members import MemberData
from ess.web import auth
from ess.web.admin import _safe_back

pytestmark = pytest.mark.db


class FakeGoogle:
    def __init__(self):
        self.userinfo = {}

    async def authorize_redirect(self, request, redirect_uri, **kwargs):
        return RedirectResponse(f"https://accounts.google.test/auth?redirect_uri={redirect_uri}", status_code=302)

    async def authorize_access_token(self, request):
        return {"userinfo": self.userinfo}


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(auth, "_google", lambda: fake)
    return fake


@pytest.fixture
def client(migrated_db):
    from ess.main import create_app

    return TestClient(create_app())


def login(client, google, email="super@example.org", verified=True):
    google.userinfo = {"email": email, "email_verified": verified, "name": "Test Admin"}
    return client.get("/admin/auth/callback", follow_redirects=False)


def csrf(client) -> str:
    html = client.get("/admin").text
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


@pytest.fixture
def data(migrated_db):
    with migrated_db() as session:
        club = Club(id=uuid.uuid4(), name="JS Testovacia", is_unaffiliated=False, uses_candidates=True, active=True)
        session.add(club)
        session.flush()
        m = members.create_member(session, SYSTEM, MemberData("Bohuslava", "Podhradská", email="b@example.org"))
        pending = memberships.add_membership(session, SYSTEM, m.id, club.id, S.PENDING_ACTIVATION, on=date(2026, 1, 1))
        leaver = members.create_member(session, SYSTEM, MemberData("Odišiel", "Zoskupiny"))
        ms = memberships.add_membership(session, SYSTEM, leaver.id, club.id, S.MEMBER, on=date(2026, 1, 1))
        memberships.terminate(session, SYSTEM, ms.id)
        session.commit()
        return {"member_id": m.id, "pending_id": pending.id, "leaver_id": leaver.id}


def test_admin_requires_login(client):
    response = client.get("/admin/members")
    assert response.status_code == 401
    assert "Prihlásiť sa účtom Google" in response.text


def test_login_redirects_to_google(client, google):
    response = client.get("/admin/login", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith("https://accounts.google.test/")


def test_super_admin_login_and_logout(client, google):
    assert login(client, google).headers["location"] == "/admin"
    page = client.get("/admin")
    assert page.status_code == 200 and "systémový administrátor" in page.text
    assert client.post("/admin/logout", data={"csrf_token": csrf(client)}, follow_redirects=False).status_code == 303
    assert client.get("/admin").status_code == 401


def test_unknown_or_unverified_account_is_denied(client, google, migrated_db):
    assert login(client, google, email="stranger@example.org").status_code == 403
    assert login(client, google, verified=False).status_code == 403
    assert client.get("/admin").status_code == 401
    with migrated_db() as session:
        denied = session.scalars(select(AuditLog).where(AuditLog.action == "admin.login_denied")).all()
        assert len(denied) == 1 and denied[0].details is None


def test_revoked_admin_loses_access_immediately(client, google, migrated_db):
    with migrated_db() as session:
        user = admin_access.grant_access(session, SYSTEM, "office@example.org", "Kancelária", AdminRole.ADMIN)
        session.commit()
    login(client, google, email="office@example.org")
    assert client.get("/admin").status_code == 200
    with migrated_db() as session:
        admin_access.revoke_access(session, SYSTEM, user.id)
        session.commit()
    assert client.get("/admin").status_code == 401


def test_member_list_detail_and_search(client, google, data):
    login(client, google)
    listing = client.get("/admin/members", params={"q": "podhradska"})
    assert "Podhradská Bohuslava" in listing.text and "Zoskupiny" not in listing.text
    detail = client.get(f"/admin/members/{data['member_id']}")
    assert "b@example.org" in detail.text and "čaká na aktiváciu" in detail.text
    assert client.get(f"/admin/members/{uuid.uuid4()}").status_code == 200  # "not found" page


def test_activation_requires_csrf_and_works(client, google, data, migrated_db):
    login(client, google)
    url = f"/admin/memberships/{data['pending_id']}/status"
    assert client.post(url, data={"new_status": "member"}).status_code == 401
    response = client.post(url, data={"new_status": "member", "csrf_token": csrf(client), "back": "/admin/activations"},
                           follow_redirects=False)
    assert response.headers["location"] == "/admin/activations"
    page = client.get("/admin/activations")
    assert "Stav členstva bol zmenený." in page.text and "Nič nečaká na aktiváciu." in page.text


def test_invalid_action_shows_message(client, google, data):
    login(client, google)
    client.post(f"/admin/memberships/{data['pending_id']}/status",
                data={"new_status": "suspended", "csrf_token": csrf(client)}, follow_redirects=False)
    assert "Táto zmena stavu nie je povolená." in client.get("/admin").text


def test_awaiting_decision_restore(client, google, data):
    login(client, google)
    assert "Zoskupiny" in client.get("/admin/awaiting").text
    client.post(f"/admin/members/{data['leaver_id']}/restore-unaffiliated", data={"csrf_token": csrf(client)})
    page = client.get("/admin/awaiting")
    assert "Nikto nečaká na rozhodnutie." in page.text


def test_clubs_page(client, google, data):
    login(client, google)
    page = client.get("/admin/clubs")
    assert "JS Testovacia" in page.text and "SSS – nezaradení" in page.text


def test_safe_back():
    assert _safe_back("/admin/members") == "/admin/members"
    assert _safe_back("https://evil.example") == "/admin"
    assert _safe_back("/admin//evil.example") == "/admin"


def test_labels_do_not_collide():
    from ess.models import MembershipStatus
    from ess.services.members import SssStatus
    from ess.web.templates import label

    assert label(MembershipStatus.MEMBER) == "člen"
    assert label(SssStatus.MEMBER) == "člen SSS"
    assert label(None) == ""
