"""Portal: a club and its members (R37) – members see contacts, the chair and the delegate see everything."""

import re

import pytest

from ess.models import MembershipStatus as S
from ess.services import delegations, portal, portal_auth, positions
from ess.services.access import SYSTEM, DomainError
from tests.test_ecp_application import _club, _member
from tests.test_web_admin import client  # noqa: F401 (fixture)

pytestmark = pytest.mark.db


def _setup(session):
    club_id = _club(session)
    chair = _member(session, club_id, first_name="Predseda", card_number="1", phone="0900 111 222")
    positions.assign_position(session, SYSTEM, "club_chair", chair, club_id)
    helper = _member(session, club_id, first_name="Pomocník", card_number="2")
    plain = _member(session, club_id, first_name="Bežný", card_number="3")
    _member(session, club_id, S.CANDIDATE, first_name="Čakateľ", card_number="4")
    return club_id, chair, helper, plain


def _m(session, member_id):
    return session.get(portal.Member, member_id)


def test_views_by_role(session):
    club_id, chair, helper, plain = _setup(session)
    view = portal.club_view(session, _m(session, plain), club_id)
    assert not view.full and [r.data.first_name for r in view.rows] == ["Bežný", "Pomocník", "Predseda"]
    full = portal.club_view(session, _m(session, chair), club_id)
    assert full.full and full.can_manage and len(full.rows) == 4  # the candidate too
    assert [r.data.first_name for r in full.delegate_options] == ["Bežný", "Pomocník"]

    delegations.delegate(session, SYSTEM, club_id, helper)
    chair_view = portal.club_view(session, _m(session, chair), club_id)
    assert chair_view.full and not chair_view.can_manage and chair_view.delegate_name
    delegate_view = portal.club_view(session, _m(session, helper), club_id)
    assert delegate_view.is_delegate and delegate_view.can_manage

    other = _club(session, "JS Iná")
    with pytest.raises(DomainError):
        portal.club_view(session, _m(session, plain), other)  # not a member of that club


def test_web_delegation_buttons(migrated_db, client):
    with migrated_db() as session:
        club_id, chair, helper, plain = _setup(session)
        chair_login = portal_auth.open_session(session, chair, "email_code")
        helper_login = portal_auth.open_session(session, helper, "email_code")
        plain_login = portal_auth.open_session(session, plain, "email_code")
        session.commit()
    # no eCP: no access to the portal at all
    client.cookies.set("ess_member", chair_login.token)
    assert client.get(f"/portal/clubs/{club_id}", follow_redirects=False).status_code == 303
    with migrated_db() as session:
        from ess.models import EcpPass

        for m in (chair, helper, plain):
            session.add(EcpPass(member_id=m, wallet_object_id=f"i.{m}", state="active"))
        session.commit()

    page = client.get(f"/portal/clubs/{club_id}").text
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    assert "Preniesť správu" in page and "Č. preukazu" in page
    r = client.post(f"/portal/clubs/{club_id}/delegate", data={"csrf_token": token, "member_id": str(helper)})
    assert "Prevziať správu" in r.text

    client.cookies.set("ess_member", helper_login.token)
    page = client.get(f"/portal/clubs/{club_id}").text
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    assert "Zrušiť administráciu klubu" in page
    r = client.post(f"/portal/clubs/{club_id}/resign", data={"csrf_token": token})
    assert "práva má znova predseda" in r.text

    client.cookies.set("ess_member", plain_login.token)
    page = client.get(f"/portal/clubs/{club_id}").text
    assert "Čakateľ" not in page and "Č. preukazu" not in page and "0900 111 222" in page
    assert "Preniesť správu" not in page
