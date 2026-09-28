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


def act(request: Request, session: Session, back: str, action, success: str) -> RedirectResponse:
    """Run a service call in one transaction and redirect back with a message (POST-redirect-GET)."""
    try:
        action()
        session.commit()
        request.session["flash"] = {"kind": "ok", "text": success}
    except (DomainError, PermissionDenied) as exc:
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
