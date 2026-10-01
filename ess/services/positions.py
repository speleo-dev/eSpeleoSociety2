"""Organisation structure: who holds which position and when. Changes are made by administrators only."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess import audit
from ess.models import Club, Member, Membership, MembershipStatus, OrgPosition, PositionHolder
from ess.services.access import Actor, DomainError, PermissionDenied, is_open_on


def _is_active_member(session: Session, member_id: uuid.UUID, club_id: uuid.UUID | None = None) -> bool:
    query = select(Membership.id).where(
        Membership.member_id == member_id,
        Membership.valid_to.is_(None),
        Membership.status == MembershipStatus.MEMBER,
    )
    if club_id is not None:
        query = query.where(Membership.club_id == club_id)
    return session.scalar(query.limit(1)) is not None


def assign_position(
    session: Session,
    actor: Actor,
    position_code: str,
    member_id: uuid.UUID,
    club_id: uuid.UUID | None = None,
    valid_from: date | None = None,
) -> PositionHolder:
    """Assign a position. For single positions the previous holder's term ends on `valid_from`.

    A new club chair is entered only after the club's documents are delivered; until then the old
    chair keeps the rights.
    """
    valid_from = valid_from or date.today()
    position = session.get(OrgPosition, position_code)
    if position is None:
        raise DomainError("position_not_found")
    require_position_rights(actor, position.is_club_bound)
    member = session.get(Member, member_id)
    if member is None:
        raise DomainError("member_not_found")
    if member.expelled_at:
        raise DomainError("member_expelled")

    if position.is_club_bound:
        club = session.get(Club, club_id) if club_id else None
        if club is None:
            raise DomainError("club_required")
        if club.is_unaffiliated:
            raise DomainError("unaffiliated_club_has_no_chair")
        if not _is_active_member(session, member_id, club_id):
            raise DomainError("chair_must_be_club_member")
    else:
        if club_id is not None:
            raise DomainError("club_not_allowed")
        if not _is_active_member(session, member_id):
            raise DomainError("holder_must_be_member")

    if position.is_single:
        query = select(PositionHolder).where(
            PositionHolder.position_code == position_code, PositionHolder.valid_to.is_(None)
        )
        if position.is_club_bound:
            query = query.where(PositionHolder.club_id == club_id)
        for previous in session.scalars(query):
            previous.valid_to = valid_from
            audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="position.end",
                         entity_type="position_holder", entity_id=str(previous.id),
                         details={"position": position_code})
        session.flush()

    holder = PositionHolder(
        id=uuid.uuid4(), position_code=position_code, member_id=member_id, club_id=club_id, valid_from=valid_from
    )
    session.add(holder)
    session.flush()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="position.assign",
                 entity_type="position_holder", entity_id=str(holder.id),
                 details={"position": position_code, "member_id": str(member_id),
                          "club_id": str(club_id) if club_id else None})
    return holder


def require_position_rights(actor: Actor, club_bound: bool) -> None:
    """R50: positions of the SSS board (Výbor) – superadmin only; the club chair – administrator or superadmin."""
    if not (actor.is_staff if club_bound else actor.is_system_admin):
        raise PermissionDenied("positions")


def end_position(session: Session, actor: Actor, holder_id: uuid.UUID, on: date | None = None) -> None:
    holder = session.get(PositionHolder, holder_id)
    if holder is None or holder.valid_to is not None:
        raise DomainError("position_not_open")
    require_position_rights(actor, holder.club_id is not None)
    holder.valid_to = on or date.today()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="position.end",
                 entity_type="position_holder", entity_id=str(holder.id),
                 details={"position": holder.position_code})


def current_holders(
    session: Session, position_code: str, club_id: uuid.UUID | None = None, on: date | None = None
) -> list[PositionHolder]:
    on = on or date.today()
    query = select(PositionHolder).where(PositionHolder.position_code == position_code)
    if club_id is not None:
        query = query.where(PositionHolder.club_id == club_id)
    return [h for h in session.scalars(query) if is_open_on(h.valid_from, h.valid_to, on)]
