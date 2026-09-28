"""Memberships in clubs: creation, status changes, activation, termination, primary club.

History is never deleted: a status change closes the current record (valid_to, end_reason) and opens
a new one. `valid_to` is exclusive (the first day the record no longer applies).
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess import audit
from ess.models import Club, Member, Membership, MembershipEndReason, MembershipStatus, TaskStatus, TaskType
from ess.services import members as members_service
from ess.services import tasks
from ess.services.access import Actor, DomainError, PermissionDenied, require_admin, require_club_manager

S = MembershipStatus

# (from, to) -> who may do it: "manager" = admin or chair of the club, "admin" = admin only.
_TRANSITIONS: dict[tuple[MembershipStatus, MembershipStatus], str] = {
    (S.CANDIDATE, S.PENDING_ACTIVATION): "manager",  # chair proposes promotion
    (S.CANDIDATE, S.MEMBER): "admin",
    (S.PENDING_ACTIVATION, S.MEMBER): "admin",  # activation (R14)
    (S.PENDING_ACTIVATION, S.CANDIDATE): "manager",  # proposal withdrawn
    (S.MEMBER, S.SUSPENDED): "manager",
    (S.SUSPENDED, S.MEMBER): "manager",  # chair restores a suspended membership himself
}


def _get_club(session: Session, club_id: uuid.UUID) -> Club:
    club = session.get(Club, club_id)
    if club is None:
        raise DomainError("club_not_found")
    return club


def _get_member(session: Session, member_id: uuid.UUID) -> Member:
    member = session.get(Member, member_id)
    if member is None:
        raise DomainError("member_not_found")
    return member


def open_memberships(session: Session, member_id: uuid.UUID) -> list[Membership]:
    return list(
        session.scalars(
            select(Membership)
            .where(Membership.member_id == member_id, Membership.valid_to.is_(None))
            .order_by(Membership.valid_from, Membership.created_at)
        )
    )


def _audit(session: Session, actor: Actor, action: str, membership: Membership, **details) -> None:
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action=action,
                 entity_type="membership", entity_id=str(membership.id),
                 details={"member_id": str(membership.member_id), "club_id": str(membership.club_id), **details})


def add_membership(
    session: Session,
    actor: Actor,
    member_id: uuid.UUID,
    club_id: uuid.UUID,
    status: MembershipStatus,
    on: date | None = None,
) -> Membership:
    """Add a member to a club.

    Chairs may add a candidate or propose a member (`pending_activation`); only admins may add `member`
    directly. The first open membership becomes the primary one.
    """
    on = on or date.today()
    club = _get_club(session, club_id)
    member = _get_member(session, member_id)
    require_club_manager(session, actor, club)

    if member.expelled_at:
        raise DomainError("member_expelled")
    if not club.active:
        raise DomainError("club_inactive")
    if status == S.SUSPENDED:
        raise DomainError("invalid_status")
    if status == S.CANDIDATE and not club.uses_candidates:
        raise DomainError("club_without_candidates")
    if status == S.MEMBER and not actor.is_admin:
        raise PermissionDenied("activation")

    current = open_memberships(session, member_id)
    if any(m.club_id == club_id for m in current):
        raise DomainError("already_in_club")

    if member.sss_ended_at:
        # Rejoining SSS: the earlier decision stays in the audit log and membership history.
        member.sss_ended_at = None
        member.sss_ended_note = None
        audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="member.sss_rejoin",
                     entity_type="member", entity_id=str(member_id))

    membership = Membership(
        id=uuid.uuid4(),
        member_id=member_id,
        club_id=club_id,
        status=status,
        is_primary=not any(m.is_primary for m in current),
        valid_from=on,
        created_by=actor.id,
    )
    if status == S.MEMBER:
        membership.activated_by = actor.id
        membership.activated_at = datetime.now(timezone.utc)
    session.add(membership)
    session.flush()
    _audit(session, actor, "membership.add", membership, status=status.value)
    # Back in a club: the presidium no longer needs to decide about SSS membership.
    tasks.close_tasks(session, actor, TaskType.SSS_DECISION, TaskStatus.DONE, "rejoined", member_id=member_id)
    if status == S.PENDING_ACTIVATION:
        tasks.open_task(session, actor, TaskType.MEMBER_ACTIVATION, member_id, membership.id, club_id)
    return membership


def add_new_member_to_club(
    session: Session,
    actor: Actor,
    data: "members_service.MemberData",
    club_id: uuid.UUID,
    status: MembershipStatus,
    on: date | None = None,
) -> Membership:
    """Create a member and add them to a club in one step (used by club chairs and admins)."""
    club = _get_club(session, club_id)
    require_club_manager(session, actor, club)
    member = members_service._create(session, actor, data)
    return add_membership(session, actor, member.id, club_id, status, on)


def change_status(
    session: Session,
    actor: Actor,
    membership_id: uuid.UUID,
    new_status: MembershipStatus,
    on: date | None = None,
    _task_resolution: tuple[str, str] | None = None,
) -> Membership:
    """Change the status of an open membership (closes the record and opens a new one).

    `_task_resolution` = (resolution, note) is used by the task list to record a rejection.
    """
    on = on or date.today()
    current = session.get(Membership, membership_id)
    if current is None or current.valid_to is not None:
        raise DomainError("membership_not_open")
    rule = _TRANSITIONS.get((current.status, new_status))
    if rule is None:
        raise DomainError("invalid_transition")
    club = _get_club(session, current.club_id)
    require_club_manager(session, actor, club)
    if rule == "admin":
        require_admin(actor)
    if _get_member(session, current.member_id).expelled_at:
        raise DomainError("member_expelled")

    was_primary = current.is_primary
    current.valid_to = on
    current.end_reason = MembershipEndReason.STATUS_CHANGE
    current.is_primary = False
    session.flush()  # free the "one open primary" slot before opening the new record

    new = Membership(
        id=uuid.uuid4(),
        member_id=current.member_id,
        club_id=current.club_id,
        status=new_status,
        is_primary=was_primary,
        valid_from=on,
        created_by=actor.id,
        activated_by=current.activated_by,
        activated_at=current.activated_at,
    )
    if new_status == S.MEMBER and current.status in (S.CANDIDATE, S.PENDING_ACTIVATION):
        new.activated_by = actor.id
        new.activated_at = datetime.now(timezone.utc)
    session.add(new)
    session.flush()
    _audit(session, actor, "membership.status", new, old_status=current.status.value, new_status=new_status.value)

    if current.status == S.PENDING_ACTIVATION:
        if new_status == S.MEMBER:
            tasks.close_tasks(session, actor, TaskType.MEMBER_ACTIVATION, TaskStatus.DONE, "activated",
                              membership_id=current.id)
        elif _task_resolution:
            tasks.close_tasks(session, actor, TaskType.MEMBER_ACTIVATION, TaskStatus.REJECTED, _task_resolution[0],
                              membership_id=current.id, note=_task_resolution[1])
        else:
            tasks.close_tasks(session, actor, TaskType.MEMBER_ACTIVATION, TaskStatus.CANCELLED, "withdrawn",
                              membership_id=current.id)
    if new_status == S.PENDING_ACTIVATION:
        tasks.open_task(session, actor, TaskType.MEMBER_ACTIVATION, new.member_id, new.id, new.club_id,
                        context={"from_status": current.status.value})
    return new


def activate(session: Session, actor: Actor, membership_id: uuid.UUID, on: date | None = None) -> Membership:
    """Activate a proposed member (R14) - administrators only."""
    require_admin(actor)
    return change_status(session, actor, membership_id, S.MEMBER, on)


def terminate(
    session: Session,
    actor: Actor,
    membership_id: uuid.UUID,
    on: date | None = None,
    _task_resolution: tuple[str, str] | None = None,
) -> None:
    """End a membership in a club (applies to this club only).

    If it was primary, the oldest remaining membership becomes primary. If no club membership remains,
    a task asks the presidium to decide about SSS membership.
    """
    on = on or date.today()
    membership = session.get(Membership, membership_id)
    if membership is None or membership.valid_to is not None:
        raise DomainError("membership_not_open")
    require_club_manager(session, actor, _get_club(session, membership.club_id))

    was_primary = membership.is_primary
    membership.valid_to = on
    membership.end_reason = MembershipEndReason.TERMINATED
    membership.is_primary = False
    session.flush()
    _audit(session, actor, "membership.terminate", membership)

    if membership.status == S.PENDING_ACTIVATION:
        if _task_resolution:
            tasks.close_tasks(session, actor, TaskType.MEMBER_ACTIVATION, TaskStatus.REJECTED, _task_resolution[0],
                              membership_id=membership.id, note=_task_resolution[1])
        else:
            tasks.close_tasks(session, actor, TaskType.MEMBER_ACTIVATION, TaskStatus.CANCELLED, "terminated",
                              membership_id=membership.id)

    remaining = open_memberships(session, membership.member_id)
    if was_primary and remaining:
        remaining[0].is_primary = True
        session.flush()
        _audit(session, actor, "membership.primary_auto", remaining[0])
    member = _get_member(session, membership.member_id)
    if not remaining and not member.expelled_at and not member.sss_ended_at:
        tasks.open_task(session, actor, TaskType.SSS_DECISION, membership.member_id, club_id=membership.club_id)


def set_primary(session: Session, actor: Actor, membership_id: uuid.UUID) -> None:
    require_admin(actor)
    target = session.get(Membership, membership_id)
    if target is None or target.valid_to is not None:
        raise DomainError("membership_not_open")
    for m in open_memberships(session, target.member_id):
        m.is_primary = False
    session.flush()
    target.is_primary = True
    session.flush()
    _audit(session, actor, "membership.primary", target)
