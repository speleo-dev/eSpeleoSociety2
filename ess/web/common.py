"""Helpers shared by administration pages."""

from datetime import date
from typing import Annotated

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ess.db import get_session
from ess.services import tasks
from ess.services.access import DomainError, PermissionDenied
from ess.web.auth import AdminContext, current_admin
from ess.web.templates import ERRORS, templates

Admin = Annotated[AdminContext, Depends(current_admin)]
Db = Annotated[Session, Depends(get_session)]


def render(request: Request, name: str, admin: AdminContext, session: Session | None = None,
           status_code: int = 200, **context):
    flash = request.session.pop("flash", None)
    open_tasks = tasks.count_open(session) if session is not None else None
    return templates.TemplateResponse(
        request, name, {"admin": admin, "flash": flash, "open_tasks": open_tasks, **context}, status_code=status_code
    )


def error_text(exc: Exception) -> str:
    code = exc.code if isinstance(exc, DomainError) else str(exc)
    return ERRORS.get(code, "Akciu nebolo možné vykonať.")


def dependency(request: Request, provider):
    """Resolve a provider honouring app.dependency_overrides (used outside FastAPI's injection)."""
    return request.app.dependency_overrides.get(provider, provider)()


def push_ecp_changes(request: Request, session: Session) -> None:
    """After a commit: send changed eCP states to Google Wallet (R25). Failures are retried next time."""
    from ess.services import ecp_state
    from ess.storage import get_media_store
    from ess.wallet import get_wallet

    if ecp_state.has_pending(session):
        ecp_state.push_pending(session, dependency(request, get_wallet), dependency(request, get_media_store))


def base_url(request: Request) -> str:
    from ess.config import get_settings

    return (get_settings().public_base_url or str(request.base_url)).rstrip("/")


def after_commit(request: Request, session: Session) -> bool:
    """Send queued e-mails and changed eCP states. Returns False if some e-mail could not be sent."""
    from ess.mail import get_mailer
    from ess.services import outbox
    from ess.web.mailing import render_mail, send

    ok = True
    mailer = dependency(request, get_mailer)
    for item in outbox.take(session):
        context = dict(item.context)
        if "link_path" in context:
            context["link"] = base_url(request) + context.pop("link_path")
        ok = send(mailer, render_mail(item.to, item.subject, item.template, **context)) and ok
    push_ecp_changes(request, session)
    return ok


def act(request: Request, session: Session, back: str, action, success: str) -> RedirectResponse:
    """Run a service call in one transaction and redirect back with a message (POST-redirect-GET)."""
    from ess.services import outbox

    try:
        action()
        session.commit()
        request.session["flash"] = {"kind": "ok", "text": success}
        if not after_commit(request, session):
            request.session["flash"] = {"kind": "error", "text": success + " E-mail sa však nepodarilo odoslať."}
    except (DomainError, PermissionDenied) as exc:
        outbox.discard(session)
        session.rollback()
        request.session["flash"] = {"kind": "error", "text": error_text(exc)}
    return RedirectResponse(safe_back(back), status_code=303)


def safe_back(back: str) -> str:
    """Only allow redirects inside the administration (no open redirect)."""
    return back if back.startswith("/admin") and "//" not in back else "/admin"


def parse_date(value: str | None) -> date | None:
    """HTML <input type=date> value (YYYY-MM-DD) or empty."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise DomainError("invalid_date") from None


def forbidden(request: Request, admin: AdminContext, session: Session):
    return render(request, "admin/forbidden.html", admin, session, status_code=403)
