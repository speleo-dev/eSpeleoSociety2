"""Business rules of phase 1 (need a PostgreSQL test database: ESS_TEST_DATABASE_URL)."""

import uuid
from datetime import date

import pytest
from sqlalchemy import select

from ess.audit import AuditLog
from ess.models import AdminRole, Club, Member, Membership, MembershipEndReason, MembershipStatus as S
from ess.services import admin_access, members, memberships, positions, settings
from ess.services.access import SYSTEM, Actor, DomainError, PermissionDenied
from ess.services.members import MemberData

pytestmark = pytest.mark.db

ADMIN = Actor(kind="admin", id="admin-1")
SYS_ADMIN = Actor(kind="system_admin", id="sysadmin-1")
D0 = date(2026, 1, 1)


def _club(session, name, uses_candidates=True) -> Club:
    club = Club(id=uuid.uuid4(), name=name, is_unaffiliated=False, uses_candidates=uses_candidates, active=True)
    session.add(club)
    session.flush()
    return club


def _member(session, first="Ján", last="Novák", **kw) -> Member:
    return members.create_member(session, ADMIN, MemberData(first_name=first, last_name=last, **kw))


def _active_member_in(session, club, **kw) -> Member:
    m = _member(session, **kw)
    memberships.add_membership(session, ADMIN, m.id, club.id, S.MEMBER, on=D0)
    return m


def _chair_of(session, club) -> Actor:
    chair = _active_member_in(session, club, first="Predseda", last=club.name)
    positions.assign_position(session, ADMIN, "club_chair", chair.id, club.id, valid_from=D0)
    return Actor(kind="member", id=str(chair.id))


def _open(session, member_id):
    return memberships.open_memberships(session, member_id)


# --- members -------------------------------------------------------------------------------------

def test_personal_data_is_encrypted_and_readable(session):
    m = _member(session, first="Bohuslava", last="Podhradská", email="b@example.org", birth_date=date(1970, 5, 1),
                title_before="Ing.", title_after="PhD.")
    session.commit()
    raw = session.execute(select(Member.first_name_enc, Member.last_name_enc, Member.email_enc)).one()
    assert all(b"Bohuslava" not in bytes(v) and b"Podhrad" not in bytes(v) for v in raw)
    data = members.read_member(session.get(Member, m.id))
    assert data.full_name() == "Ing. Bohuslava Podhradská, PhD."
    assert data.birth_date == date(1970, 5, 1)


def test_lookup_ignores_case_and_diacritics(session):
    m = _member(session, first="Štefan", last="Kováč", birth_date=date(1965, 3, 3))
    assert [x.id for x in members.find_by_lookup(session, "stefan", "KOVAC", 1965)] == [m.id]
    assert members.find_by_lookup(session, "stefan", "kovac", 1966) == []


def test_email_and_card_number_are_unique(session):
    _member(session, email="a@example.org", card_number="1234")
    with pytest.raises(DomainError, match="email_in_use"):
        _member(session, first="Iný", email=" a@example.org")
    with pytest.raises(DomainError, match="card_number_in_use"):
        _member(session, first="Iný", card_number="1234")


def test_audit_contains_field_names_not_values(session):
    m = _member(session, email="old@example.org")
    data = members.read_member(m)
    data.email = "new@example.org"
    members.update_member(session, ADMIN, m.id, data)
    entry = session.scalars(select(AuditLog).where(AuditLog.action == "member.update")).one()
    assert entry.details == {"fields": ["email"]}
    assert "example.org" not in str(entry.details)


def test_chair_edits_only_members_of_own_club(session):
    club, other = _club(session, "JS Demänová"), _club(session, "JS Plavecký")
    chair = _chair_of(session, club)
    own, foreign = _active_member_in(session, club, first="A"), _active_member_in(session, other, first="B")
    members.update_member(session, chair, own.id, members.read_member(own))
    with pytest.raises(PermissionDenied):
        members.update_member(session, chair, foreign.id, members.read_member(foreign))
    data = members.read_member(own)
    data.reduced_fee = True
    with pytest.raises(PermissionDenied):
        members.update_member(session, chair, own.id, data)


def test_create_member_requires_admin(session):
    with pytest.raises(PermissionDenied):
        members.create_member(session, Actor(kind="member", id=str(uuid.uuid4())), MemberData("A", "B"))


# --- memberships ---------------------------------------------------------------------------------

def test_chair_adds_candidate_and_proposes_member_but_cannot_activate(session):
    club = _club(session, "JS Demänová")
    chair = _chair_of(session, club)
    cand = memberships.add_new_member_to_club(session, chair, MemberData("Čakateľ", "X"), club.id, S.CANDIDATE)
    proposed = memberships.change_status(session, chair, cand.id, S.PENDING_ACTIVATION)
    with pytest.raises(PermissionDenied):
        memberships.activate(session, chair, proposed.id)
    with pytest.raises(PermissionDenied):
        memberships.add_new_member_to_club(session, chair, MemberData("Priamo", "Člen"), club.id, S.MEMBER)
    activated = memberships.activate(session, ADMIN, proposed.id)
    assert activated.status == S.MEMBER and activated.activated_by == ADMIN.id


def test_chair_cannot_manage_other_or_unaffiliated_club(session):
    club, other = _club(session, "JS A"), _club(session, "JS B")
    chair = _chair_of(session, club)
    unaffiliated = session.scalars(select(Club).where(Club.is_unaffiliated)).one()
    for target in (other, unaffiliated):
        with pytest.raises(PermissionDenied):
            memberships.add_new_member_to_club(session, chair, MemberData("X", "Y"), target.id, S.PENDING_ACTIVATION)


def test_candidate_not_allowed_in_club_without_candidates(session):
    club = _club(session, "JS Bez čakateľov", uses_candidates=False)
    m = _member(session)
    with pytest.raises(DomainError, match="club_without_candidates"):
        memberships.add_membership(session, ADMIN, m.id, club.id, S.CANDIDATE)


def test_status_change_keeps_history(session):
    club = _club(session, "JS A")
    chair = _chair_of(session, club)
    m = _active_member_in(session, club)
    first = _open(session, m.id)[0]
    suspended = memberships.change_status(session, chair, first.id, S.SUSPENDED, on=date(2026, 3, 1))
    restored = memberships.change_status(session, chair, suspended.id, S.MEMBER, on=date(2026, 4, 1))
    history = session.scalars(
        select(Membership).where(Membership.member_id == m.id).order_by(Membership.valid_from)
    ).all()
    assert [(h.status, h.valid_to, h.end_reason) for h in history] == [
        (S.MEMBER, date(2026, 3, 1), MembershipEndReason.STATUS_CHANGE),
        (S.SUSPENDED, date(2026, 4, 1), MembershipEndReason.STATUS_CHANGE),
        (S.MEMBER, None, None),
    ]
    assert restored.is_primary


def test_invalid_transition(session):
    club = _club(session, "JS A")
    m = _active_member_in(session, club)
    with pytest.raises(DomainError, match="invalid_transition"):
        memberships.change_status(session, ADMIN, _open(session, m.id)[0].id, S.CANDIDATE)


def test_primary_membership_moves_on_termination(session):
    a, b = _club(session, "JS A"), _club(session, "JS B")
    m = _active_member_in(session, a)
    second = memberships.add_membership(session, ADMIN, m.id, b.id, S.MEMBER, on=date(2026, 2, 1))
    assert not second.is_primary
    with pytest.raises(DomainError, match="already_in_club"):
        memberships.add_membership(session, ADMIN, m.id, a.id, S.MEMBER)
    primary = next(x for x in _open(session, m.id) if x.is_primary)
    memberships.terminate(session, ADMIN, primary.id, on=date(2026, 6, 1))
    remaining = _open(session, m.id)
    assert [(x.club_id, x.is_primary) for x in remaining] == [(b.id, True)]


def test_expelled_member_cannot_rejoin(session):
    club = _club(session, "JS A")
    m = _active_member_in(session, club)
    positions.assign_position(session, ADMIN, "board_member", m.id, valid_from=D0)
    with pytest.raises(PermissionDenied):
        members.expel_member(session, _chair_of(session, club), m.id, "Uznesenie VZ")
    members.expel_member(session, ADMIN, m.id, "Uznesenie VZ 2026/5", on=date(2026, 5, 1))
    assert _open(session, m.id) == []
    assert positions.current_holders(session, "board_member") == []
    with pytest.raises(DomainError, match="member_expelled"):
        memberships.add_membership(session, ADMIN, m.id, club.id, S.MEMBER)


# --- organisation structure ----------------------------------------------------------------------

def test_new_club_chair_replaces_old_one(session):
    club = _club(session, "JS A")
    old_chair = _chair_of(session, club)
    new = _active_member_in(session, club, first="Nový")
    member = _active_member_in(session, club, first="Bežný")
    positions.assign_position(session, ADMIN, "club_chair", new.id, club.id, valid_from=date(2026, 3, 1))
    holders = positions.current_holders(session, "club_chair", club.id, on=date(2026, 3, 1))
    assert [h.member_id for h in holders] == [new.id]
    # Old chair keeps rights until the change date, then loses them.
    with pytest.raises(PermissionDenied):
        members.update_member(session, old_chair, member.id, members.read_member(member))


def test_position_rules(session):
    club, other = _club(session, "JS A"), _club(session, "JS B")
    outsider = _active_member_in(session, other)
    unaffiliated = session.scalars(select(Club).where(Club.is_unaffiliated)).one()
    with pytest.raises(DomainError, match="chair_must_be_club_member"):
        positions.assign_position(session, ADMIN, "club_chair", outsider.id, club.id)
    with pytest.raises(DomainError, match="unaffiliated_club_has_no_chair"):
        positions.assign_position(session, ADMIN, "club_chair", outsider.id, unaffiliated.id)
    with pytest.raises(PermissionDenied):
        positions.assign_position(session, Actor(kind="member", id=str(outsider.id)), "sss_chair", outsider.id)
    positions.assign_position(session, ADMIN, "sss_chair", outsider.id, valid_from=D0)
    second = _active_member_in(session, club)
    positions.assign_position(session, ADMIN, "sss_chair", second.id, valid_from=date(2026, 6, 1))
    assert [h.member_id for h in positions.current_holders(session, "sss_chair", on=date(2026, 6, 1))] == [second.id]


# --- administrative access and settings ----------------------------------------------------------

def test_admin_access(session):
    assert admin_access.resolve_role(session, "Super@Example.org")[0] == AdminRole.SYSTEM_ADMIN
    assert admin_access.resolve_role(session, "nobody@example.org") is None
    with pytest.raises(PermissionDenied):
        admin_access.grant_access(session, ADMIN, "office@example.org", "Kancelária", AdminRole.ADMIN)
    user = admin_access.grant_access(session, SYS_ADMIN, "Office@example.org", "Kancelária", AdminRole.ADMIN)
    assert admin_access.resolve_role(session, "office@example.org") == (AdminRole.ADMIN, str(user.id))
    admin_access.revoke_access(session, SYS_ADMIN, user.id)
    assert admin_access.resolve_role(session, "office@example.org") is None


def test_settings(session):
    assert settings.get_setting(session, "fee_amount") == "15.00"
    with pytest.raises(PermissionDenied):
        settings.set_setting(session, ADMIN, "fee_amount", "20")
    assert settings.get_setting(session, "reduced_fee_amount") == "7.00"
    assert settings.get_setting(session, "reduced_fee_age") == "62"
    settings.set_setting(session, SYS_ADMIN, "reduced_fee_amount", "7.50")
    assert settings.get_setting(session, "reduced_fee_amount") == "7.50"
    with pytest.raises(DomainError, match="invalid_value"):
        settings.set_setting(session, SYS_ADMIN, "fee_amount", "-1")


def test_age_reduced_fee(session):
    turns_62_in_2026 = _member(session, first="A", birth_date=date(1964, 12, 31))
    turned_62_in_2025 = _member(session, first="B", birth_date=date(1963, 1, 1))
    no_birth_date = _member(session, first="C")
    assert members.apply_age_reduced_fee(session, SYSTEM, fee_year=2026, age=62) == 1
    assert turned_62_in_2025.reduced_fee and not turns_62_in_2026.reduced_fee and not no_birth_date.reduced_fee
    assert members.apply_age_reduced_fee(session, SYSTEM, fee_year=2027, age=62) == 1
    assert turns_62_in_2026.reduced_fee


# --- SSS membership after leaving clubs ----------------------------------------------------------

def test_leaving_last_club_waits_for_presidium_decision(session):
    club = _club(session, "JS A")
    chair = _chair_of(session, club)
    m = _active_member_in(session, club)
    memberships.terminate(session, chair, _open(session, m.id)[0].id)
    assert members.sss_status(session, m) == members.SssStatus.AWAITING_DECISION
    assert [x.id for x in members.awaiting_decision(session)] == [m.id]

    with pytest.raises(PermissionDenied):
        members.end_sss_membership(session, chair, m.id, "Nechce byť jaskyniarom")
    members.end_sss_membership(session, ADMIN, m.id, "Rozhodnutie predsedníctva")
    assert members.sss_status(session, m) == members.SssStatus.ENDED
    assert members.awaiting_decision(session) == []

    # Later the member asks to be restored among the unaffiliated.
    restored = members.restore_to_unaffiliated(session, ADMIN, m.id)
    assert restored.status == S.MEMBER and restored.is_primary
    assert members.sss_status(session, m) == members.SssStatus.MEMBER
    assert m.sss_ended_at is None


def test_ending_sss_membership_ends_clubs_and_positions(session):
    club = _club(session, "JS A")
    m = _active_member_in(session, club)
    positions.assign_position(session, ADMIN, "board_member", m.id, valid_from=D0)
    members.end_sss_membership(session, ADMIN, m.id, "", on=date(2026, 6, 1))
    assert _open(session, m.id) == []
    assert positions.current_holders(session, "board_member", on=date(2026, 6, 1)) == []


def test_expelled_member_cannot_be_restored(session):
    m = _active_member_in(session, _club(session, "JS A"))
    members.expel_member(session, ADMIN, m.id, "Uznesenie VZ")
    with pytest.raises(DomainError, match="member_expelled"):
        members.restore_to_unaffiliated(session, ADMIN, m.id)
    assert members.sss_status(session, m) == members.SssStatus.EXPELLED



# --- tasks ("Požiadavky") -------------------------------------------------------------------------

def _open_tasks(session, member_id):
    from ess.models import Task

    return sorted((t.task_type, t.status) for t in session.scalars(select(Task).where(Task.member_id == member_id)))


def test_activation_task_lifecycle(session):
    from ess.services import tasks as tasks_service

    club = _club(session, "JS A")
    chair = _chair_of(session, club)
    new = memberships.add_new_member_to_club(session, chair, MemberData("Nový", "Člen"), club.id, S.PENDING_ACTIVATION)
    assert _open_tasks(session, new.member_id) == [("member_activation", "open")]
    task = tasks_service.list_tasks(session)[0].task
    assert task.requested_by == chair.id and task.club_id == club.id
    tasks_service.activate(session, ADMIN, task.id)
    assert _open_tasks(session, new.member_id) == [("member_activation", "done")]
    assert task.resolution == "activated" and task.resolved_by == ADMIN.id


def test_activation_from_member_page_also_closes_task(session):
    club = _club(session, "JS A")
    m = _member(session)
    pending = memberships.add_membership(session, ADMIN, m.id, club.id, S.PENDING_ACTIVATION)
    memberships.activate(session, ADMIN, pending.id)
    assert _open_tasks(session, m.id) == [("member_activation", "done")]


def test_rejected_candidate_promotion_returns_to_candidate(session):
    from ess.services import tasks as tasks_service

    club = _club(session, "JS A")
    chair = _chair_of(session, club)
    cand = memberships.add_new_member_to_club(session, chair, MemberData("Čakateľ", "X"), club.id, S.CANDIDATE)
    memberships.change_status(session, chair, cand.id, S.PENDING_ACTIVATION)
    task = tasks_service.list_tasks(session)[0].task
    assert task.context == {"from_status": "candidate"}
    with pytest.raises(DomainError, match="reason_required"):
        tasks_service.reject_activation(session, ADMIN, task.id, "")
    tasks_service.reject_activation(session, ADMIN, task.id, "Neabsolvoval skúšku")
    assert [m.status for m in _open(session, cand.member_id)] == [S.CANDIDATE]
    assert (task.status, task.resolution, task.resolution_note) == ("rejected", "rejected", "Neabsolvoval skúšku")


def test_rejected_new_member_proposal_ends_membership(session):
    from ess.services import tasks as tasks_service

    club = _club(session, "JS A")
    chair = _chair_of(session, club)
    new = memberships.add_new_member_to_club(session, chair, MemberData("Nový", "Y"), club.id, S.PENDING_ACTIVATION)
    task = tasks_service.list_tasks(session)[0].task
    tasks_service.reject_activation(session, ADMIN, task.id, "Nesplnené podmienky")
    assert _open(session, new.member_id) == []
    # A rejected proposal is not a member who left SSS - but the member has no club, so the presidium decides.
    assert ("sss_decision", "open") in _open_tasks(session, new.member_id)


def test_leaving_last_club_opens_decision_task_and_rejoin_closes_it(session):
    a, b = _club(session, "JS A"), _club(session, "JS B")
    m = _active_member_in(session, a)
    memberships.terminate(session, ADMIN, _open(session, m.id)[0].id)
    assert _open_tasks(session, m.id) == [("sss_decision", "open")]
    memberships.add_membership(session, ADMIN, m.id, b.id, S.MEMBER)
    assert _open_tasks(session, m.id) == [("sss_decision", "done")]


def test_expulsion_cancels_open_tasks(session):
    club = _club(session, "JS A")
    m = _member(session)
    memberships.add_membership(session, ADMIN, m.id, club.id, S.PENDING_ACTIVATION)
    members.expel_member(session, ADMIN, m.id, "Uznesenie VZ")
    assert _open_tasks(session, m.id) == [("member_activation", "cancelled")]
