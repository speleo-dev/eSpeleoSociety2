"""Who performs an action and what they may do.

Administrative access (admin / system_admin) is separate from the organisation structure (R17).
The only right derived from a position is: a club chair manages their own club.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess.models import Club, ClubDelegation, PositionHolder

ActorKind = Literal["system_admin", "admin", "member", "system", "public"]


class PermissionDenied(Exception):
    """The actor is not allowed to perform the action."""


class DomainError(Exception):
    """A business rule was violated. `code` is stable and used for UI messages (no personal data)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Actor:
    kind: ActorKind
    id: str  # admin_users.id, members.id or "system"

    @property
    def is_admin(self) -> bool:
        """Administrator or system administrator. `system` covers trusted scripts (import, test data)."""
        return self.kind in ("admin", "system_admin", "system")

    @property
    def is_system_admin(self) -> bool:
        return self.kind in ("system_admin", "system")

    @property
    def audit_type(self) -> str:
        return "admin" if self.kind in ("admin", "system_admin") else self.kind


SYSTEM = Actor(kind="system", id="system")
PUBLIC = Actor(kind="public", id="public")  # anonymous visitor of the public pages


def require_admin(actor: Actor) -> None:
    if not actor.is_admin:
        raise PermissionDenied("admin")


def require_system_admin(actor: Actor) -> None:
    if not actor.is_system_admin:
        raise PermissionDenied("system_admin")


def is_open_on(valid_from: date, valid_to: date | None, on: date) -> bool:
    """`valid_to` is exclusive: the first day the record no longer applies."""
    return valid_from <= on and (valid_to is None or on < valid_to)


def chaired_club_ids(session: Session, member_id: uuid.UUID, on: date | None = None) -> set[uuid.UUID]:
    on = on or date.today()
    rows = session.execute(
        select(PositionHolder.club_id, PositionHolder.valid_from, PositionHolder.valid_to).where(
            PositionHolder.member_id == member_id, PositionHolder.position_code == "club_chair"
        )
    ).all()
    return {club_id for club_id, vf, vt in rows if club_id and is_open_on(vf, vt, on)}


def managed_club_ids(session: Session, member_id: uuid.UUID) -> set[uuid.UUID]:
    """Clubs the member manages: as chair unless delegated (R37), or as the chair's delegate."""
    today = date.today()
    delegations = session.execute(select(ClubDelegation.club_id, ClubDelegation.chair_member_id,
                                         ClubDelegation.delegate_member_id).where(ClubDelegation.ended_at.is_(None))).all()
    chairs = session.execute(select(PositionHolder.club_id, PositionHolder.member_id, PositionHolder.valid_from,
                                    PositionHolder.valid_to).where(
        PositionHolder.position_code == "club_chair",
        PositionHolder.club_id.in_([d[0] for d in delegations]))).all() if delegations else []
    current_chair = {c: m for c, m, vf, vt in chairs if is_open_on(vf, vt, today)}
    # A delegation applies only while its chair is still the chair (a new chair may start on a later date).
    effective = {club_id: delegate for club_id, chair, delegate in delegations if current_chair.get(club_id) == chair}
    as_delegate = {club_id for club_id, delegate in effective.items() if delegate == member_id}
    return (chaired_club_ids(session, member_id) - set(effective)) | as_delegate


def can_manage_club(session: Session, actor: Actor, club: Club) -> bool:
    if actor.is_admin:
        return True
    if actor.kind != "member" or club.is_unaffiliated:
        return False
    return club.id in managed_club_ids(session, uuid.UUID(actor.id))


def require_club_manager(session: Session, actor: Actor, club: Club) -> None:
    if not can_manage_club(session, actor, club):
        raise PermissionDenied("club_manager")
