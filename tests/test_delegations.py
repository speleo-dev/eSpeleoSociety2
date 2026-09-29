"""Club chair delegation (R37): the delegate manages the club, the chair can take it back."""

import pytest
from sqlalchemy import select

from ess.models import ClubDelegation, Member, MembershipStatus as S
from ess.services import delegations, members, memberships, positions
from ess.services.access import SYSTEM, Actor, DomainError, PermissionDenied, can_manage_club
from ess.services.members import MemberData
from tests.test_ecp_application import _club, _member
from tests.test_web_admin import client, csrf, google, login  # noqa: F401 (fixtures)

pytestmark = pytest.mark.db


def _setup(session):
    club_id = _club(session)
    chair = _member(session, club_id, first_name="Predseda", card_number="1")
    positions.assign_position(session, SYSTEM, "club_chair", chair, club_id)
    helper = _member(session, club_id, first_name="Pomocník", card_number="2")
    return club_id, chair, helper


def _club_obj(session, club_id):
    from ess.models import Club

    return session.get(Club, club_id)


def _as(member_id) -> Actor:
    return Actor(kind="member", id=str(member_id))


def test_chair_delegates_and_takes_back(session):
    club_id, chair, helper = _setup(session)
    club = _club_obj(session, club_id)
    candidate = _member(session, club_id, S.CANDIDATE, first_name="Čakateľ", card_number="3")
    with pytest.raises(DomainError):
        delegations.delegate(session, _as(chair), club_id, candidate)  # only a member, not a candidate
    with pytest.raises(PermissionDenied):
        delegations.delegate(session, _as(helper), club_id, helper)  # only the chair

    delegations.delegate(session, _as(chair), club_id, helper)
    assert can_manage_club(session, _as(helper), club) and not can_manage_club(session, _as(chair), club)
    with pytest.raises(PermissionDenied):  # the chair cannot change the club now
        memberships.add_new_member_to_club(session, _as(chair), MemberData("Nový", "X"), club_id, S.CANDIDATE)
    memberships.add_new_member_to_club(session, _as(helper), MemberData("Nový", "X"), club_id, S.CANDIDATE)
    with pytest.raises(DomainError):
        delegations.delegate(session, _as(chair), club_id, helper)  # take back first

    delegations.take_back(session, _as(chair), club_id)
    assert can_manage_club(session, _as(chair), club) and not can_manage_club(session, _as(helper), club)
    delegations.delegate(session, _as(chair), club_id, helper)  # the same member again


def test_delegate_resigns(session):
    club_id, chair, helper = _setup(session)
    delegations.delegate(session, SYSTEM, club_id, helper)  # an administrator may set the delegate
    with pytest.raises(DomainError):
        delegations.resign(session, _as(chair), club_id)
    delegations.resign(session, _as(helper), club_id)
    assert delegations.current(session, club_id) is None
    assert can_manage_club(session, _as(chair), _club_obj(session, club_id))


def _own(session, member_id, club_id):
    return next(m for m in memberships.open_memberships(session, member_id) if m.club_id == club_id)


def test_ends_when_primary_club_changes(session):
    club_id, chair, helper = _setup(session)
    delegations.delegate(session, SYSTEM, club_id, helper)
    other = _club(session, "JS Iná")
    memberships.set_primary(session, SYSTEM, memberships.add_membership(session, SYSTEM, helper, other, S.MEMBER).id)
    session.flush()
    delegation = session.scalars(select(ClubDelegation)).one()
    assert delegation.ended_at and delegation.end_reason == "delegate_left" and delegation.ended_by == "system"
    with pytest.raises(DomainError):
        delegations.delegate(session, SYSTEM, club_id, helper)  # the club is no longer the primary one


def test_ends_when_delegate_is_suspended(session):
    club_id, chair, helper = _setup(session)
    delegations.delegate(session, SYSTEM, club_id, helper)
    memberships.change_status(session, SYSTEM, _own(session, helper, club_id).id, S.SUSPENDED)
    session.flush()
    assert delegations.current(session, club_id) is None


def test_ends_when_chair_changes(session):
    club_id, chair, helper = _setup(session)
    delegations.delegate(session, SYSTEM, club_id, helper)
    new_chair = _member(session, club_id, first_name="Nový predseda", card_number="9")
    positions.assign_position(session, SYSTEM, "club_chair", new_chair, club_id)
    session.flush()
    assert delegations.current(session, club_id) is None
    assert can_manage_club(session, _as(new_chair), _club_obj(session, club_id))
    assert not can_manage_club(session, _as(helper), _club_obj(session, club_id))
    assert set(delegations.eligible_ids(session, club_id)) == {chair, helper}  # not the new chair


def test_delegate_edits_member_of_club(session):
    club_id, chair, helper = _setup(session)
    delegations.delegate(session, SYSTEM, club_id, helper)
    members.update_member(session, _as(helper), chair, members.read_member(session.get(Member, chair)))
    with pytest.raises(PermissionDenied):
        members.update_member(session, _as(chair), helper, members.read_member(session.get(Member, helper)))


def test_admin_club_page_sets_and_ends_delegation(migrated_db, google, client):
    with migrated_db() as session:
        club_id, chair, helper = _setup(session)
        session.commit()
    login(client, google)
    token = csrf(client)
    page = client.get(f"/admin/clubs/{club_id}").text
    assert "Zastupovanie predsedu" in page and f'value="{helper}"' in page
    r = client.post(f"/admin/clubs/{club_id}/delegation", data={"csrf_token": token, "member_id": str(helper)})
    assert "Zástupca predsedu bol určený" in r.text and "Skupinu spravuje zástupca predsedu" in r.text
    r = client.post(f"/admin/clubs/{club_id}/delegation/end", data={"csrf_token": token})
    assert "skupinu spravuje predseda" in r.text
    r = client.post(f"/admin/clubs/{club_id}/delegation", data={"csrf_token": token, "member_id": str(chair)})
    assert "nie predseda" in r.text
