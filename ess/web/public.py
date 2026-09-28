"""Public pages: application for an eCP (verification page and portal come later)."""

import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ess.config import get_settings
from ess.db import get_session
from ess.mail import Mail, Mailer, MailError, get_mailer
from ess.services import directory, ecp_applications
from ess.services.access import DomainError
from ess.services.ecp_applications import ApplicationForm
from ess.web.auth import csrf_token
from ess.web.common import parse_date
from ess.web.templates import ERRORS, templates

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ecp")

SESSION_KEY = "ecp_application"


async def verify_public_csrf(request: Request) -> None:
    form = await request.form()
    expected = request.session.get("csrf")
    if not expected or not secrets.compare_digest(str(form.get("csrf_token", "")), expected):
        raise HTTPException(status_code=400, detail="Formulár vypršal, načítajte stránku znova.")


def _page(request: Request, name: str, status_code: int = 200, **context):
    return templates.TemplateResponse(request, name, {"csrf": csrf_token(request), **context},
                                      status_code=status_code)


def _base_url(request: Request) -> str:
    return (get_settings().public_base_url or str(request.base_url)).rstrip("/")


def _send_verification(request: Request, mailer: Mailer | None, pending: ecp_applications.VerificationMail):
    link = f"{_base_url(request)}/ecp/email/{pending.token}"
    context = {"first_name": pending.first_name, "link": link}
    mail = Mail(to=pending.email, subject="Overenie e-mailu – žiadosť o eCP",
                text=templates.get_template("email/verify_email.txt").render(context),
                html=templates.get_template("email/verify_email.html").render(context))
    if mailer is None:
        log.warning("Verification e-mail not sent: mailer is not configured")
        return
    try:
        mailer.send(mail)
    except MailError:
        pass  # already logged without the address; the applicant can apply again


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


@router.get("/apply/photo")
def apply_photo(request: Request):
    if not request.session.get(SESSION_KEY):
        return _page(request, "public/link_invalid.html", status_code=410)
    return _page(request, "public/apply_photo.html")
