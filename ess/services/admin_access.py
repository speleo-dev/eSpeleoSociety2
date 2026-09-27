"""Administrative access (R17): Google accounts with the admin or system_admin role.

The main system administrators come from ESS_SUPER_ADMIN_EMAILS and cannot be removed in the app.
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


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def resolve_role(session: Session, google_email: str) -> tuple[AdminRole, str] | None:
    """Return (role, actor id) for a verified Google e-mail, or None if it has no access."""
    email = _normalize_email(google_email)
    if email in get_settings().super_admins:
        return AdminRole.SYSTEM_ADMIN, f"super:{pii.blind_index(_BIDX_EMAIL, email).hex()[:16]}"
    user = session.scalar(
        select(AdminUser).where(AdminUser.google_email_bidx == pii.blind_index(_BIDX_EMAIL, email))
    )
    if user is None or not user.active:
        return None
    return user.role, str(user.id)


def grant_access(session: Session, actor: Actor, google_email: str, display_name: str, role: AdminRole) -> AdminUser:
    require_system_admin(actor)
    email = _normalize_email(google_email)
    if "@" not in email:
        raise DomainError("invalid_email")
    if email in get_settings().super_admins:
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
