"""Administrative access (R17, R50): administrators granted in the app, superadmins from the server config.

Superadmins (system_admin) come only from ESS_SUPER_ADMIN_EMAILS and are changed on the server. In the app a
superadmin grants and revokes the administrator role; older grants stored as system_admin act as admin.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess import audit
from ess.config import get_settings
from ess.models import AdminRole, AdminUser
from ess.security import pii
from ess.services.access import Actor, DomainError, require_system_admin

_CTX_EMAIL = "admin_users.google_email"
_CTX_NAME = "admin_users.display_name"
_BIDX_EMAIL = "admin_users.google_email"


def normalize_email(email: str) -> str:
    """Canonical form for comparing Google account e-mails.

    Gmail ignores dots and "+tags" in the local part and treats googlemail.com as gmail.com, so
    "Jan.Novak+x@googlemail.com" and "jannovak@gmail.com" are the same account. Stray "<>" and spaces
    from copy-pasted configuration are removed.
    """
    email = email.strip().strip("<>").strip().lower()
    local, _, domain = email.partition("@")
    if domain in ("gmail.com", "googlemail.com"):
        local = local.split("+", 1)[0].replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}" if domain else local


def super_admin_emails() -> frozenset[str]:
    """Main system administrators from ESS_SUPER_ADMIN_EMAILS, in canonical form."""
    raw = get_settings().super_admin_emails
    return frozenset(normalize_email(e) for e in raw.split(",") if e.strip())


def resolve_role(session: Session, google_email: str) -> tuple[AdminRole, str] | None:
    """Return (role, actor id) for a verified Google e-mail, or None if it has no access."""
    email = normalize_email(google_email)
    if email in super_admin_emails():
        return AdminRole.SYSTEM_ADMIN, f"super:{pii.blind_index(_BIDX_EMAIL, email).hex()[:16]}"
    user = session.scalar(
        select(AdminUser).where(AdminUser.google_email_bidx == pii.blind_index(_BIDX_EMAIL, email))
    )
    if user is None or not user.active:
        return None
    return AdminRole.ADMIN, str(user.id)  # superadmins only from the server config (R50)


def resolve_member(session: Session, member_id: uuid.UUID) -> tuple[AdminRole, str] | None:
    """Administrator role of a member signed in with the eCP (R51), or None."""
    user = session.scalar(select(AdminUser).where(AdminUser.member_id == member_id, AdminUser.active))
    return (AdminRole.ADMIN, str(user.id)) if user is not None else None


def grant_member_access(session: Session, actor: Actor, member_id: uuid.UUID) -> AdminUser:
    """The superadmin makes a member an administrator who signs in with the eCP (R51)."""
    from ess.models import Member
    from ess.services import members

    require_system_admin(actor)
    member = session.get(Member, member_id)
    if member is None or member.expelled_at:
        raise DomainError("member_not_found")
    user = session.scalar(select(AdminUser).where(AdminUser.member_id == member_id))
    if user is None:
        user = AdminUser(id=uuid.uuid4(), member_id=member_id)
        session.add(user)
    user.display_name_enc = pii.encrypt(members.read_member(member).full_name(), _CTX_NAME)
    user.role = AdminRole.ADMIN
    user.active = True
    user.granted_by = actor.id
    session.flush()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="admin_access.grant",
                 entity_type="admin_user", entity_id=str(user.id), details={"role": "admin", "via": "ecp"})
    return user


def member_access(session: Session, member_id: uuid.UUID) -> AdminUser | None:
    return session.scalar(select(AdminUser).where(AdminUser.member_id == member_id))


def grant_access(session: Session, actor: Actor, google_email: str, display_name: str, role: AdminRole) -> AdminUser:
    require_system_admin(actor)
    if role != AdminRole.ADMIN:
        raise DomainError("super_admin_is_configured")  # superadmins only on the server (R50)
    email = normalize_email(google_email)
    if "@" not in email:
        raise DomainError("invalid_email")
    if email in super_admin_emails():
        raise DomainError("super_admin_is_configured")
    index = pii.blind_index(_BIDX_EMAIL, email)
    user = session.scalar(select(AdminUser).where(AdminUser.google_email_bidx == index))
    if user is None:
        user = AdminUser(id=uuid.uuid4(), google_email_bidx=index)
        session.add(user)
    user.google_email_enc = pii.encrypt(email, _CTX_EMAIL)
    user.display_name_enc = pii.encrypt(display_name.strip(), _CTX_NAME)
    user.role = role
    user.active = True
    user.granted_by = actor.id
    session.flush()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="admin_access.grant",
                 entity_type="admin_user", entity_id=str(user.id), details={"role": role.value})
    return user


def revoke_access(session: Session, actor: Actor, admin_user_id: uuid.UUID) -> None:
    require_system_admin(actor)
    user = session.get(AdminUser, admin_user_id)
    if user is None:
        raise DomainError("admin_user_not_found")
    if str(user.id) == actor.id:
        raise DomainError("cannot_revoke_self")
    user.active = False
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="admin_access.revoke",
                 entity_type="admin_user", entity_id=str(user.id))


def list_users(session: Session) -> list[dict]:
    """Admin users with decrypted e-mail and name (for the access management page)."""
    rows = []
    for user in session.scalars(select(AdminUser)):
        rows.append({
            "id": user.id,
            "email": pii.decrypt(user.google_email_enc, _CTX_EMAIL) if user.google_email_enc else None,
            "member_id": user.member_id,
            "name": pii.decrypt(user.display_name_enc, _CTX_NAME),
            "role": AdminRole.ADMIN,  # older system_admin grants act as admin (R50)
            "active": user.active,
            "granted_at": user.granted_at,
        })
    return sorted(rows, key=lambda r: (not r["active"], r["name"] or ""))
