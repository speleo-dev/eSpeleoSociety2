"""Club chair delegation (R37).

- The chair (or an administrator) hands over managing the club to one member whose primary club it is
  (status "member"). While delegated, the chair only reads the club and can take the management back.
- The delegate can give the management back to the chair ("Zrušiť administráciu klubu").
- The delegation ends by itself when the club gets a new chair, or when the delegate is no longer a member
  of the club with it as the primary club (checked on every flush, like the eCP state).
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from ess import audit
from ess.models import Club, ClubDelegation, Member, Membership, MembershipStatus, PositionHolder
from ess.services.access import SYSTEM, Actor, DomainError, PermissionDenied, is_open_on

_KEY = "delegation_clubs"


def current(session: Session, club_id: uuid.UUID) -> ClubDelegation | None:
    return session.scalar(select(ClubDelegation).where(ClubDelegation.club_id == club_id,
                                                       ClubDelegation.ended_at.is_(None)))


def current_chair_id(session: Session, club_id: uuid.UUID, on: date | None = None) -> uuid.UUID | None:
    on = on or date.today()
    rows = session.execute(select(PositionHolder.member_id, PositionHolder.valid_from, PositionHolder.valid_to).where(
        PositionHolder.club_id == club_id, PositionHolder.position_code == "club_chair")).all()
    return next((m for m, vf, vt in rows if is_open_on(vf, vt, on)), None)


def is_eligible(session: Session, club_id: uuid.UUID, member_id: uuid.UUID) -> bool:
    """A member of the club (not a candidate or suspended) with the club as the primary one."""
    return session.scalar(select(Membership.id).join(Member, Member.id == Membership.member_id).where(
        Membership.club_id == club_id, Membership.member_id == member_id, Membership.valid_to.is_(None),
        Membership.is_primary, Membership.status == MembershipStatus.MEMBER, Member.expelled_at.is_(None),
        Member.sss_ended_at.is_(None))) is not None


def eligible_ids(session: Session, club_id: uuid.UUID) -> list[uuid.UUID]:
    chair = current_chair_id(session, club_id)
    return [m for m in session.scalars(select(Membership.member_id).where(
        Membership.club_id == club_id, Membership.valid_to.is_(None), Membership.is_primary,
        Membership.status == MembershipStatus.MEMBER)) if m != chair and is_eligible(session, club_id, m)]


def _is_chair(session: Session, actor: Actor, club_id: uuid.UUID) -> bool:
    return actor.kind == "member" and str(current_chair_id(session, club_id)) == actor.id


def _end(session: Session, actor: Actor, delegation: ClubDelegation, reason: str) -> None:
    delegation.ended_at, delegation.ended_by, delegation.end_reason = datetime.now(UTC), actor.id, reason
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="club_delegation.end",
                 entity_type="club_delegation", entity_id=str(delegation.id), details={"reason": reason})


def delegate(session: Session, actor: Actor, club_id: uuid.UUID, member_id: uuid.UUID) -> ClubDelegation:
    """The chair (not while delegated) or an administrator (also replaces a current delegate)."""
    club = session.get(Club, club_id)
    if club is None:
        raise DomainError("club_not_found")
    if club.is_unaffiliated:
        raise DomainError("unaffiliated_club_has_no_chair")
    chair_id = current_chair_id(session, club_id)
    if chair_id is None:
        raise DomainError("club_has_no_chair")
    existing = current(session, club_id)
    if not actor.is_admin:
        if not _is_chair(session, actor, club_id):
            raise PermissionDenied("club_chair")
        if existing is not None:
            raise DomainError("club_already_delegated")  # take the management back first
    if member_id == chair_id or not is_eligible(session, club_id, member_id):
        raise DomainError("delegate_not_eligible")
    if existing is not None:
        _end(session, actor, existing, "replaced")
        session.flush()
    delegation = ClubDelegation(id=uuid.uuid4(), club_id=club_id, chair_member_id=chair_id,
                                delegate_member_id=member_id, created_by=actor.id)
    session.add(delegation)
    session.flush()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="club_delegation.start",
                 entity_type="club_delegation", entity_id=str(delegation.id), details={"club_id": str(club_id)})
    return delegation


def take_back(session: Session, actor: Actor, club_id: uuid.UUID) -> None:
    """"Prevziať správu": the chair (or an administrator) ends the delegation."""
    if not actor.is_admin and not _is_chair(session, actor, club_id):
        raise PermissionDenied("club_chair")
    delegation = current(session, club_id)
    if delegation is None:
        raise DomainError("club_not_delegated")
    _end(session, actor, delegation, "taken_back")


def resign(session: Session, actor: Actor, club_id: uuid.UUID) -> None:
    """"Zrušiť administráciu klubu": the delegate gives the management back to the chair."""
    delegation = current(session, club_id)
    if delegation is None or actor.kind != "member" or str(delegation.delegate_member_id) != actor.id:
        raise DomainError("club_not_delegated")
    _end(session, actor, delegation, "resigned")


def end_if_invalid(session: Session, club_id: uuid.UUID) -> None:
    delegation = current(session, club_id)
    if delegation is None:
        return
    if current_chair_id(session, club_id) != delegation.chair_member_id:
        _end(session, SYSTEM, delegation, "chair_changed")
    elif not is_eligible(session, club_id, delegation.delegate_member_id):
        _end(session, SYSTEM, delegation, "delegate_left")


@event.listens_for(Session, "after_flush")
def _collect(session: Session, _flush_context) -> None:
    info = session.info.setdefault(_KEY, (set(), set()))
    clubs, members = info
    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, Membership):
            clubs.add(obj.club_id)
        elif isinstance(obj, PositionHolder) and obj.position_code == "club_chair":
            clubs.add(obj.club_id)
        elif isinstance(obj, Member):  # expelled or SSS membership ended
            members.add(obj.id)


@event.listens_for(Session, "after_flush_postexec")
def _apply(session: Session, _flush_context) -> None:
    clubs, members = session.info.pop(_KEY, (set(), set()))
    if members:
        clubs |= set(session.scalars(select(ClubDelegation.club_id).where(
            ClubDelegation.ended_at.is_(None), ClubDelegation.delegate_member_id.in_(members))))
    for club_id in clubs:
        if club_id is not None:
            end_if_invalid(session, club_id)
