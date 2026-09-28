"""Clubs (skupiny): creation and changes by administrators."""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess import audit
from ess.models import Club
from ess.services.access import Actor, DomainError, require_admin


def _check_name(session: Session, name: str, club_id: uuid.UUID | None = None) -> str:
    name = " ".join(name.split())
    if not name:
        raise DomainError("name_required")
    query = select(Club.id).where(Club.name == name)
    if club_id:
        query = query.where(Club.id != club_id)
    if session.scalar(query):
        raise DomainError("club_name_in_use")
    return name


def _check_code(session: Session, code: str | None, club_id: uuid.UUID | None = None) -> str | None:
    code = (code or "").strip().upper()
    if not code:
        return None
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,19}", code):
        raise DomainError("invalid_club_code")
    query = select(Club.id).where(Club.code == code)
    if club_id:
        query = query.where(Club.id != club_id)
    if session.scalar(query):
        raise DomainError("club_code_in_use")
    return code


def create_club(
    session: Session, actor: Actor, name: str, short_name: str, uses_candidates: bool, code: str | None = None
) -> Club:
    require_admin(actor)
    club = Club(id=uuid.uuid4(), name=_check_name(session, name), code=_check_code(session, code),
                short_name=short_name.strip() or None,
                is_unaffiliated=False, uses_candidates=uses_candidates, active=True)
    session.add(club)
    session.flush()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="club.create",
                 entity_type="club", entity_id=str(club.id))
    return club


def update_club(
    session: Session, actor: Actor, club_id: uuid.UUID, name: str, short_name: str, uses_candidates: bool, active: bool,
    code: str | None = None,
) -> Club:
    require_admin(actor)
    club = session.get(Club, club_id)
    if club is None:
        raise DomainError("club_not_found")
    if club.is_unaffiliated and not active:
        raise DomainError("unaffiliated_club_cannot_be_deactivated")
    before = (club.name, club.short_name, club.uses_candidates, club.active, club.code)
    club.name = _check_name(session, name, club_id)
    if code is not None and not club.is_unaffiliated:
        club.code = _check_code(session, code, club_id)
    club.short_name = short_name.strip() or None
    club.uses_candidates = False if club.is_unaffiliated else uses_candidates
    club.active = active
    after = (club.name, club.short_name, club.uses_candidates, club.active, club.code)
    changed = [f for f, b, a in zip(("name", "short_name", "uses_candidates", "active", "code"), before, after) if b != a]
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="club.update",
                 entity_type="club", entity_id=str(club.id), details={"fields": changed})
    return club
