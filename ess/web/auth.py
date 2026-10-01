"""Administrative sign-in with a Google account (OpenID Connect).

The session cookie (signed, not encrypted) stores only the verified e-mail and a CSRF token. The role is
resolved from the database on every request, so revoking access takes effect immediately.
"""

import secrets
from dataclasses import dataclass

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ess import audit
from ess.config import get_settings
from ess.db import get_session
from ess.models import AdminRole
from ess.services import admin_access
from ess.services.access import Actor
from ess.web.paths import A

router = APIRouter()  # mounted under the admin path (R48)
oauth = OAuth()
_registered = False


def _google():
    global _registered
    if not _registered:
        settings = get_settings()
        if not settings.google_client_id or not settings.google_client_secret:
            raise RuntimeError("ESS_GOOGLE_CLIENT_ID / ESS_GOOGLE_CLIENT_SECRET are not set")
        oauth.register(
            name="google",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
        _registered = True
    return oauth.google


class LoginRequired(Exception):
    """Raised by `current_admin` when nobody is signed in; handled by a redirect to the login page."""


@dataclass(frozen=True)
class AdminContext:
    actor: Actor
    display_name: str
    role: AdminRole
    csrf_token: str
    via_ecp: bool = False  # signed in with the eCP on the portal (R51), not with Google
    ecp_admin_available: bool = False  # Google session, but the portal member is an administrator too

    @property
    def is_system_admin(self) -> bool:
        return self.role == AdminRole.SYSTEM_ADMIN

    @property
    def is_admin(self) -> bool:
        """Administrator of the register (members, clubs, fees, requests); not the superadmin (R50)."""
        return self.role == AdminRole.ADMIN


class NotAllowed(Exception):
    """The signed-in administrator's role may not open the page (e.g. a superadmin and the fees, R50)."""

    def __init__(self, admin: "AdminContext"):
        super().__init__("not_allowed")
        self.admin = admin


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def current_register_admin(request: Request, session: Session = Depends(get_session)) -> "AdminContext":
    """Pages that change or show the register (members, clubs, fees, requests): the administrator only (R50)."""
    admin = current_admin(request, session)
    if not admin.is_admin:
        raise NotAllowed(admin)
    return admin


def _admin_from_ecp(request: Request, session: Session) -> AdminContext | None:
    """A member signed in on the portal (eCP) who has the administrator role (R51)."""
    from ess.services import members, portal_auth

    token = request.cookies.get("ess_member")
    if not token:
        return None
    member = portal_auth.current_member(session, token)
    resolved = admin_access.resolve_member(session, member.id) if member is not None else None
    if resolved is None:
        return None
    role, actor_id = resolved
    return AdminContext(actor=Actor(kind=role.value, id=actor_id), display_name=members.read_member(member).full_name(),
                        role=role, csrf_token=csrf_token(request), via_ecp=True)


def current_admin(request: Request, session: Session = Depends(get_session)) -> AdminContext:
    email = request.session.get("admin_email")
    if not email:
        admin = _admin_from_ecp(request, session)
        if admin is None:
            raise LoginRequired()
        return admin
    resolved = admin_access.resolve_role(session, email)
    if resolved is None:
        request.session.clear()
        raise LoginRequired()
    role, actor_id = resolved
    return AdminContext(
        actor=Actor(kind=role.value, id=actor_id),
        display_name=request.session.get("admin_name", ""),
        role=role,
        csrf_token=csrf_token(request),
        ecp_admin_available=_admin_from_ecp(request, session) is not None,
    )


async def verify_csrf(request: Request) -> None:
    """Dependency for POST handlers: the form must carry the session's CSRF token."""
    form = await request.form()
    expected = request.session.get("csrf")
    if not expected or not secrets.compare_digest(str(form.get("csrf_token", "")), expected):
        raise LoginRequired()


def _redirect_uri(request: Request) -> str:
    base = get_settings().public_base_url
    if base:
        return base.rstrip("/") + f"{A}/auth/callback"
    return str(request.url_for("admin_auth_callback"))


def google_config_ok() -> bool:
    """Catch the most common setup mistake (wrong value in ESS_GOOGLE_CLIENT_ID) before Google does."""
    settings = get_settings()
    client_id = (settings.google_client_id or "").strip()
    return client_id.endswith(".apps.googleusercontent.com") and " " not in client_id and bool(
        settings.google_client_secret
    )


@router.get("/login")
async def admin_login(request: Request):
    if not google_config_ok():
        from ess.web.templates import templates

        return templates.TemplateResponse(request, "admin/login_failed.html", {"reason": "config"}, status_code=500)
    return await _google().authorize_redirect(request, _redirect_uri(request), prompt="select_account")


@router.get("/auth/callback", name="admin_auth_callback")
async def admin_auth_callback(request: Request, session: Session = Depends(get_session)):
    from ess.web.templates import templates

    try:
        token = await _google().authorize_access_token(request)
    except OAuthError:
        return templates.TemplateResponse(request, "admin/login_failed.html", {"reason": "google"}, status_code=400)
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").strip().lower()
    if not email or not info.get("email_verified"):
        return templates.TemplateResponse(request, "admin/login_failed.html", {"reason": "unverified"}, status_code=403)
    resolved = admin_access.resolve_role(session, email)
    if resolved is None:
        # No personal data in the audit - only the fact that an unknown account tried to sign in.
        audit.record(session, actor_type="public", actor_id=None, action="admin.login_denied")
        session.commit()
        # The e-mail is shown only to the person who just signed in with it (never logged).
        return templates.TemplateResponse(
            request, "admin/login_failed.html", {"reason": "no_access", "email": email}, status_code=403
        )
    role, actor_id = resolved
    request.session.clear()
    request.session["admin_email"] = email
    request.session["admin_name"] = info.get("name") or email
    csrf_token(request)
    audit.record(session, actor_type="admin", actor_id=actor_id, action="admin.login", details={"role": role.value})
    session.commit()
    return RedirectResponse(str(A), status_code=303)


@router.get("/ecp")
def admin_via_ecp(request: Request):
    """Use the administrator role of the portal member (eCP) instead of the Google sign-in (R53)."""
    request.session.pop("admin_email", None)
    request.session.pop("admin_name", None)
    return RedirectResponse(str(A), status_code=303)


@router.post("/logout")
async def admin_logout(request: Request, _: None = Depends(verify_csrf)):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
