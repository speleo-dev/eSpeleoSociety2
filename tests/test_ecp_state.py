"""eCP state follows SSS membership (R25) and is pushed to Google Wallet after the commit."""

import re

import pytest
from sqlalchemy import select

from ess.models import EcpPass, MembershipStatus
from ess.services import ecp_state, members, memberships
from ess.services.access import SYSTEM
from ess.storage import MemoryMediaStore
from ess.wallet import WalletError
from tests.test_ecp_application import _club
from tests.test_ecp_verification import _issued

pytestmark = pytest.mark.db


def _membership(session, member_id):
    return memberships.open_memberships(session, member_id)[0]


def test_suspension_and_restoration(session):
    wallet, ecp_pass, member_id = _issued(session)
    memberships.change_status(session, SYSTEM, _membership(session, member_id).id, MembershipStatus.SUSPENDED)
    session.flush()
    assert ecp_pass.state == "inactive" and ecp_pass.wallet_state == "active"
    memberships.change_status(session, SYSTEM, _membership(session, member_id).id, MembershipStatus.MEMBER)
    session.flush()
    assert ecp_pass.state == "active"


def test_active_while_member_in_another_club(session):
    wallet, ecp_pass, member_id = _issued(session)
    other = _club(session, "JS Druhá")
    memberships.add_membership(session, SYSTEM, member_id, other, MembershipStatus.MEMBER)
    memberships.change_status(session, SYSTEM, _membership(session, member_id).id, MembershipStatus.SUSPENDED)
    session.flush()
    assert ecp_pass.state == "active"


def test_leaving_sss_revokes_for_good(session):
    wallet, ecp_pass, member_id = _issued(session)
    memberships.terminate(session, SYSTEM, _membership(session, member_id).id)
    session.flush()
    assert ecp_pass.state == "active"  # a club decides only for itself; the administrator decides about SSS (R30)
    members.end_sss_membership(session, SYSTEM, member_id, "rozhodnutie")
    session.flush()
    assert ecp_pass.state == "revoked" and ecp_pass.revoked_at
    members.restore_to_unaffiliated(session, SYSTEM, member_id)
    session.flush()
    assert ecp_pass.state == "revoked"  # final; a new eCP needs a new application


def test_expulsion_revokes(session):
    wallet, ecp_pass, member_id = _issued(session)
    members.expel_member(session, SYSTEM, member_id, "porušenie kódexu")
    session.flush()
    assert ecp_pass.state == "revoked"


def test_push_pending_updates_wallet_and_removes_personal_data(session):
    wallet, ecp_pass, member_id = _issued(session)
    store = MemoryMediaStore()
    store.put(ecp_pass.photo, b"jpeg", "image/jpeg")
    obj = wallet.objects[ecp_pass.wallet_object_id]
    memberships.change_status(session, SYSTEM, _membership(session, member_id).id, MembershipStatus.SUSPENDED)
    session.flush()
    assert ecp_state.has_pending(session)
    assert ecp_state.push_pending(session, wallet, store) == 1
    assert obj["state"] == "INACTIVE" and ecp_pass.wallet_state == "inactive"
    assert not ecp_state.has_pending(session)

    members.expel_member(session, SYSTEM, member_id, "test")
    session.flush()

    class Broken(type(wallet)):
        def patch_object(self, object_id, fields):
            raise WalletError("patch: HTTP 503")

    broken = Broken()
    broken.objects = wallet.objects
    assert ecp_state.push_pending(session, broken, store) == 0 and ecp_state.has_pending(session)  # retried later
    assert ecp_state.push_pending(session, wallet, store) == 1
    assert obj["state"] == "EXPIRED" and obj["textModulesData"] == [] and obj["imageModulesData"] == []
    assert "Neplatný" in obj["header"]["defaultValue"]["value"]
    assert ecp_pass.photo is None and store.objects == {}


def test_web_action_pushes_state(migrated_db, monkeypatch):
    from ess.config import get_settings
    from ess.main import create_app
    from ess.storage import get_media_store
    from ess.wallet import get_wallet
    from ess.web import auth
    from fastapi.testclient import TestClient
    from tests.test_web_admin import FakeGoogle

    with migrated_db() as s:
        wallet, ecp_pass, member_id = _issued(s)
        membership_id = _membership(s, member_id).id
        object_id = ecp_pass.wallet_object_id
        s.commit()
    monkeypatch.setenv("ESS_GOOGLE_CLIENT_ID", "123-test.apps.googleusercontent.com")
    monkeypatch.setenv("ESS_GOOGLE_CLIENT_SECRET", "test-secret")
    get_settings.cache_clear()
    google = FakeGoogle()
    monkeypatch.setattr(auth, "_google", lambda: google)
    app = create_app()
    app.dependency_overrides.update({get_wallet: lambda: wallet, get_media_store: lambda: MemoryMediaStore()})
    client = TestClient(app)
    google.userinfo = {"email": "super@example.org", "email_verified": True, "name": "Admin"}
    client.get("/admin/auth/callback")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/admin").text).group(1)
    client.post(f"/admin/memberships/{membership_id}/status",
                data={"csrf_token": csrf, "new_status": "suspended", "back": f"/admin/members/{member_id}"})
    assert wallet.objects[object_id]["state"] == "INACTIVE"
    page = client.get(f"/admin/members/{member_id}").text
    assert "neaktívny" in page and "nebola odoslaná" not in page
    with migrated_db() as s:
        assert s.scalar(select(EcpPass.wallet_state)) == "inactive"
