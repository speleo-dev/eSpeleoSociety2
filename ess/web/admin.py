"""Administration pages (Google sign-in required)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ess.db import get_session
from ess.models import MembershipStatus, TaskType
from ess.services import directory, members, memberships, tasks
from ess.services.access import DomainError, PermissionDenied
from ess.web.auth import AdminContext, current_admin, verify_csrf
from ess.web.templates import ERRORS, templates

router = APIRouter(prefix="/admin")
PAGE_SIZE = 50

Admin = Annotated[AdminContext, Depends(current_admin)]
Db = Annotated[Session, Depends(get_session)]


def _render(request: Request, name: str, admin: AdminContext, session: Session | None = None, **context):
    flash = request.session.pop("flash", None)
    open_tasks = tasks.count_open(session) if session is not None else None
    return templates.TemplateResponse(request, name, {"admin": admin, "flash": flash, "open_tasks": open_tasks, **context})


def _act(request: Request, session: Session, back: str, action, success: str) -> RedirectResponse:
    """Run a service call in one transaction and redirect back with a message (POST-redirect-GET)."""
    try:
        action()
        session.commit()
        request.session["flash"] = {"kind": "ok", "text": success}
    except (DomainError, PermissionDenied) as exc:
        session.rollback()
        code = exc.code if isinstance(exc, DomainError) else str(exc)
        request.session["flash"] = {"kind": "error", "text": ERRORS.get(code, "Akciu nebolo možné vykonať.")}
    return RedirectResponse(back, status_code=303)


@router.get("")
def dashboard(request: Request, admin: Admin, session: Db):
    return _render(request, "admin/dashboard.html", admin, session, counts=directory.dashboard_counts(session))


@router.get("/members")
def member_list(
    request: Request, admin: Admin, session: Db, q: str = "", club: str = "", status: str = "", page: int = 1
):
    club_id = uuid.UUID(club) if club else None
    status_value = MembershipStatus(status) if status else None
    rows = directory.list_members(session, q or None, club_id, status_value)
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(1, page), pages)
    return _render(
        request, "admin/members.html", admin, session,
        rows=rows[(page - 1) * PAGE_SIZE : page * PAGE_SIZE], total=len(rows), page=page, pages=pages,
        q=q, club=club, status=status, clubs=directory.clubs_overview(session), statuses=list(MembershipStatus),
    )


@router.get("/members/{member_id}")
def member_page(request: Request, member_id: uuid.UUID, admin: Admin, session: Db):
    detail = directory.member_detail(session, member_id)
    if detail is None:
        return _render(request, "admin/not_found.html", admin, session)
    return _render(request, "admin/member.html", admin, session, d=detail, S=MembershipStatus)


@router.post("/memberships/{membership_id}/status", dependencies=[Depends(verify_csrf)])
def membership_status(
    request: Request, membership_id: uuid.UUID, admin: Admin, session: Db,
    new_status: Annotated[str, Form()], back: Annotated[str, Form()] = "/admin",
):
    target = MembershipStatus(new_status)
    action = lambda: memberships.change_status(session, admin.actor, membership_id, target)  # noqa: E731
    return _act(request, session, _safe_back(back), action, "Stav členstva bol zmenený.")


@router.post("/memberships/{membership_id}/terminate", dependencies=[Depends(verify_csrf)])
def membership_terminate(
    request: Request, membership_id: uuid.UUID, admin: Admin, session: Db, back: Annotated[str, Form()] = "/admin"
):
    return _act(request, session, _safe_back(back),
                lambda: memberships.terminate(session, admin.actor, membership_id),
                "Členstvo v skupine bolo ukončené.")


@router.get("/tasks")
def task_list(request: Request, admin: Admin, session: Db, show: str = "open", type: str = ""):
    open_only = show != "done"
    return _render(
        request, "admin/tasks.html", admin, session,
        rows=tasks.list_tasks(session, open_only=open_only, task_type=type or None),
        show="open" if open_only else "done", type=type, T=TaskType,
    )


@router.post("/tasks/{task_id}/activate", dependencies=[Depends(verify_csrf)])
def task_activate(request: Request, task_id: uuid.UUID, admin: Admin, session: Db):
    return _act(request, session, "/admin/tasks", lambda: tasks.activate(session, admin.actor, task_id),
                "Člen bol aktivovaný.")


@router.post("/tasks/{task_id}/reject", dependencies=[Depends(verify_csrf)])
def task_reject(request: Request, task_id: uuid.UUID, admin: Admin, session: Db, reason: Annotated[str, Form()] = ""):
    return _act(request, session, "/admin/tasks",
                lambda: tasks.reject_activation(session, admin.actor, task_id, reason),
                "Návrh bol zamietnutý.")


@router.post("/tasks/{task_id}/keep-unaffiliated", dependencies=[Depends(verify_csrf)])
def task_keep_unaffiliated(request: Request, task_id: uuid.UUID, admin: Admin, session: Db):
    return _act(request, session, "/admin/tasks", lambda: tasks.keep_as_unaffiliated(session, admin.actor, task_id),
                "Člen bol zaradený do „SSS – nezaradení“.")


@router.post("/tasks/{task_id}/end-sss", dependencies=[Depends(verify_csrf)])
def task_end_sss(request: Request, task_id: uuid.UUID, admin: Admin, session: Db, note: Annotated[str, Form()] = ""):
    return _act(request, session, "/admin/tasks", lambda: tasks.end_sss(session, admin.actor, task_id, note),
                "Členstvo v SSS bolo ukončené.")


@router.post("/members/{member_id}/restore-unaffiliated", dependencies=[Depends(verify_csrf)])
def member_restore(
    request: Request, member_id: uuid.UUID, admin: Admin, session: Db, back: Annotated[str, Form()] = "/admin"
):
    return _act(request, session, _safe_back(back),
                lambda: members.restore_to_unaffiliated(session, admin.actor, member_id),
                "Člen bol zaradený do „SSS – nezaradení“.")


@router.get("/activations")
@router.get("/awaiting")
def old_lists():
    return RedirectResponse("/admin/tasks", status_code=301)


@router.get("/clubs")
def clubs(request: Request, admin: Admin, session: Db):
    return _render(request, "admin/clubs.html", admin, session, rows=directory.clubs_overview(session), S=MembershipStatus)


def _safe_back(back: str) -> str:
    """Only allow redirects inside the administration (no open redirect)."""
    return back if back.startswith("/admin") and "//" not in back else "/admin"
