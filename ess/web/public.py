"""Public pages: application for an eCP (verification page and portal come later)."""

import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ess.config import get_settings
from ess.db import get_session
from ess.images import MAX_UPLOAD_BYTES
from ess.mail import Mailer, get_mailer
from ess.services import directory, ecp_applications
from ess.services.access import DomainError
from ess.services.ecp_applications import ApplicationForm
from ess.storage import MediaStore, get_media_store
from ess.web.auth import csrf_token
from ess.web.common import parse_date
from ess.web.mailing import render_mail, send
from ess.web.templates import ERRORS, templates

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ecp")
verify_router = APIRouter()

SESSION_KEY = "ecp_application"


async def verify_public_csrf(request: Request) -> None:
    form = await request.form()
    expected = request.session.get("csrf")
    if not expected or not secrets.compare_digest(str(form.get("csrf_token", "")), expected):
        raise HTTPException(status_code=400, detail="Formulár vypršal, načítajte stránku znova.")


def _page(request: Request, name: str, status_code: int = 200, **context):
    return templates.TemplateResponse(request, name, {"csrf": csrf_token(request), **context},
                                      status_code=status_code)


def base_url(request: Request) -> str:
    return (get_settings().public_base_url or str(request.base_url)).rstrip("/")


def _send_verification(request: Request, mailer: Mailer | None, pending: ecp_applications.VerificationMail):
    link = f"{base_url(request)}/ecp/email/{pending.token}"
    send(mailer, render_mail(pending.email, "Overenie e-mailu – žiadosť o eCP", "verify_email",
                             first_name=pending.first_name, link=link))


@router.get("/apply")
def apply_form(request: Request, session: Session = Depends(get_session)):
    return _page(request, "public/apply.html", clubs=directory.active_clubs(session), raw={})


@router.post("/apply", dependencies=[Depends(verify_public_csrf)])
async def apply_submit(request: Request, session: Session = Depends(get_session),
                       mailer: Mailer | None = Depends(get_mailer)):
    form = await request.form()
    raw = {k: str(form.get(k, "")).strip() for k in
           ("first_name", "last_name", "birth_date", "email", "card_number", "member_since", "club_id")}
    if form.get("website"):  # honeypot: people do not see this field, simple bots fill it
        return RedirectResponse("/ecp/apply/sent", status_code=303)
    try:
        club_id = uuid.UUID(raw["club_id"]) if raw["club_id"] else None
    except ValueError:
        club_id = None
    try:
        data = ApplicationForm(
            first_name=raw["first_name"], last_name=raw["last_name"], birth_date=parse_date(raw["birth_date"]),
            email=raw["email"], card_number=raw["card_number"],
            member_since_year=int(raw["member_since"]) if raw["member_since"].isdigit() else None,
            club_id=club_id)
        pending = ecp_applications.start_public(session, data)
        session.commit()
    except DomainError as exc:
        session.rollback()
        return _page(request, "public/apply.html", status_code=400, clubs=directory.active_clubs(session), raw=raw,
                     error=ERRORS.get(exc.code, "Skontrolujte vyplnené údaje."))
    if pending:
        _send_verification(request, mailer, pending)
    return RedirectResponse("/ecp/apply/sent", status_code=303)


@router.get("/apply/sent")
def apply_sent(request: Request):
    return _page(request, "public/apply_sent.html")


@router.get("/email/{token}")
def email_link(request: Request, token: str, session: Session = Depends(get_session)):
    application = ecp_applications.verify_email(session, token)
    if application is None:
        session.rollback()
        return _page(request, "public/link_invalid.html", status_code=410)
    session.commit()
    request.session[SESSION_KEY] = str(application.id)
    return RedirectResponse("/ecp/apply/photo", status_code=303)


def _application_in_session(request: Request) -> uuid.UUID | None:
    try:
        return uuid.UUID(request.session.get(SESSION_KEY, ""))
    except ValueError:
        return None


def _crop(form) -> tuple[float, float, float, float] | None:
    try:
        values = tuple(float(form.get(f"crop_{k}", "")) for k in ("x", "y", "w", "h"))
    except ValueError:
        return None  # no JavaScript: automatic crop
    return values if all(0 <= v <= 1 for v in values) and values[2] > 0 else None


@router.get("/apply/photo")
def apply_photo(request: Request):
    if _application_in_session(request) is None:
        return _page(request, "public/link_invalid.html", status_code=410)
    return _page(request, "public/apply_photo.html")


@router.post("/apply/photo", dependencies=[Depends(verify_public_csrf)])
async def apply_photo_submit(request: Request, session: Session = Depends(get_session),
                             store: MediaStore | None = Depends(get_media_store)):
    application_id = _application_in_session(request)
    if application_id is None:
        return _page(request, "public/link_invalid.html", status_code=410)
    form = await request.form()
    upload = form.get("photo")
    data = await upload.read(MAX_UPLOAD_BYTES + 1) if hasattr(upload, "read") else b""
    result = None
    try:
        result = await run_in_threadpool(
            ecp_applications.submit_photo, session, application_id, data, _crop(form), form.get("gdpr") == "on",
            form.get("notifications") == "on", form.get("wants_card") == "on", store)
        session.commit()
    except DomainError as exc:
        session.rollback()
        return _page(request, "public/apply_photo.html", status_code=400,
                     error=ERRORS.get(exc.code, "Fotku sa nepodarilo spracovať."))
    except Exception:
        session.rollback()
        if result and store:
            for name in result.objects:
                store.delete(name)
        raise
    request.session.pop(SESSION_KEY, None)
    return RedirectResponse("/ecp/apply/done", status_code=303)


@router.get("/apply/done")
def apply_done(request: Request):
    return _page(request, "public/apply_done.html")


@verify_router.get("/v/{token}")
def verification_page(request: Request, token: str):
    """Target of the eCP QR code (R18). The full verification page (section 5a) comes next."""
    return _page(request, "public/verify_placeholder.html")
