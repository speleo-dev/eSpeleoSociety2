"""Member portal login (R38).

The link in the eCP (`/p/<portal_key>`) says which member logs in. On a new device a 6-digit code is sent
to the member's e-mail; it works only in the browser that asked for it (`browser` = random value kept in
that browser's session). A successful login creates a member session for 90 days (the cookie holds the
token, the database its hash). Only members with an active eCP may log in.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ess import audit
from ess.models import EcpPass, EcpPassState, Member, MemberLoginCode, MemberSession
from ess.services import members, outbox
from ess.services.access import Actor, DomainError, require_admin

CODE_VALID = timedelta(minutes=10)
CODE_ATTEMPTS = 5
CODES_PER_HOUR = 5
SESSION_VALID = timedelta(days=90)


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(*parts: str) -> bytes:
    return hashlib.sha256("|".join(parts).encode()).digest()


def new_portal_key() -> str:
    return secrets.token_urlsafe(24)


def pass_for_key(session: Session, key: str) -> EcpPass | None:
    """The pass of the portal link, only while it is active."""
    if not key or len(key) > 43:
        return None
    ecp_pass = session.scalar(select(EcpPass).where(EcpPass.portal_key == key))
    return ecp_pass if ecp_pass is not None and ecp_pass.state == EcpPassState.ACTIVE.value else None


def may_log_in(session: Session, member_id: uuid.UUID) -> bool:
    return session.scalar(select(EcpPass.id).where(EcpPass.member_id == member_id,
                                                   EcpPass.state == EcpPassState.ACTIVE.value)) is not None


# --- e-mail code --------------------------------------------------------------------------------------


def send_code(session: Session, key: str, browser: str) -> None:
    """Queue an e-mail with a new code. Raises DomainError when not possible (no e-mail, too many codes)."""
    ecp_pass = pass_for_key(session, key)
    if ecp_pass is None:
        raise DomainError("portal_not_available")
    member = session.get(Member, ecp_pass.member_id)
    data = members.read_member(member)
    if not data.email:
        raise DomainError("portal_needs_email")
    recent = session.scalar(select(func.count()).select_from(MemberLoginCode).where(
        MemberLoginCode.member_id == member.id, MemberLoginCode.created_at > _now() - timedelta(hours=1)))
    if recent >= CODES_PER_HOUR:
        raise DomainError("too_many_codes")
    code = f"{secrets.randbelow(1_000_000):06d}"
    row = MemberLoginCode(id=uuid.uuid4(), member_id=member.id, browser_hash=_hash("browser", browser),
                          expires_at=_now() + CODE_VALID, attempts=0)
    row.code_hash = _hash(str(row.id), code)
    session.add(row)
    audit.record(session, actor_type="public", actor_id=None, action="portal.code_sent",
                 entity_type="member", entity_id=str(member.id))
    outbox.queue(session, outbox.QueuedMail(to=data.email, subject="Kód na prihlásenie do portálu eSS",
                                            template="portal_code",
                                            context={"first_name": data.first_name, "code": code}))


@dataclass
class NewSession:
    token: str  # goes to the cookie only
    member_id: uuid.UUID
    expires_at: datetime


def _open_session(session: Session, member_id: uuid.UUID, method: str) -> NewSession:
    token = secrets.token_urlsafe(32)
    expires = _now() + SESSION_VALID
    session.add(MemberSession(id=uuid.uuid4(), member_id=member_id, token_hash=_hash("session", token),
                              method=method, expires_at=expires))
    audit.record(session, actor_type="member", actor_id=str(member_id), action="portal.login",
                 entity_type="member", entity_id=str(member_id), details={"method": method})
    return NewSession(token, member_id, expires)


def verify_code(session: Session, key: str, browser: str, code: str) -> NewSession | str:
    """Check the code of the newest valid request from this browser. Returns the new session, or an error
    code ("code_wrong", "code_expired", "portal_not_available") – not raised, so a failed attempt is saved."""
    ecp_pass = pass_for_key(session, key)
    if ecp_pass is None:
        return "portal_not_available"
    row = session.scalar(select(MemberLoginCode).where(
        MemberLoginCode.member_id == ecp_pass.member_id, MemberLoginCode.browser_hash == _hash("browser", browser),
        MemberLoginCode.used_at.is_(None), MemberLoginCode.expires_at > _now(),
    ).order_by(MemberLoginCode.created_at.desc()).limit(1).with_for_update())
    if row is None or row.attempts >= CODE_ATTEMPTS:
        return "code_expired"
    code = "".join(code.split())
    if not secrets.compare_digest(row.code_hash, _hash(str(row.id), code)):
        row.attempts += 1
        return "code_wrong" if row.attempts < CODE_ATTEMPTS else "code_expired"
    row.used_at = _now()
    return _open_session(session, ecp_pass.member_id, "email_code")


# --- sessions -----------------------------------------------------------------------------------------


def current_member(session: Session, token: str | None) -> Member | None:
    """The member of a valid session cookie; the eCP must still be active."""
    if not token or len(token) > 64:
        return None
    row = session.scalar(select(MemberSession).where(
        MemberSession.token_hash == _hash("session", token), MemberSession.revoked_at.is_(None),
        MemberSession.expires_at > _now()))
    if row is None or not may_log_in(session, row.member_id):
        return None
    return session.get(Member, row.member_id)


def log_out(session: Session, token: str | None) -> None:
    if not token:
        return
    row = session.scalar(select(MemberSession).where(MemberSession.token_hash == _hash("session", token)))
    if row is not None and row.revoked_at is None:
        row.revoked_at = _now()
        audit.record(session, actor_type="member", actor_id=str(row.member_id), action="portal.logout",
                     entity_type="member", entity_id=str(row.member_id))


def log_out_everywhere(session: Session, actor: Actor, member_id: uuid.UUID) -> int:
    """An administrator ends all sessions of the member (e.g. lost phone)."""
    require_admin(actor)
    rows = session.scalars(select(MemberSession).where(MemberSession.member_id == member_id,
                                                       MemberSession.revoked_at.is_(None))).all()
    for row in rows:
        row.revoked_at = _now()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="portal.logout_all",
                 entity_type="member", entity_id=str(member_id), details={"sessions": len(rows)})
    return len(rows)


def active_sessions(session: Session, member_id: uuid.UUID) -> int:
    return session.scalar(select(func.count()).select_from(MemberSession).where(
        MemberSession.member_id == member_id, MemberSession.revoked_at.is_(None),
        MemberSession.expires_at > _now())) or 0

