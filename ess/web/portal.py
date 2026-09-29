"""Member portal (phase 4): login from the eCP link with an e-mail code (R38) and the member's home page."""

import json
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from sqlalchemy.orm import Session
from typing import Annotated

from ess.config import get_settings
from ess.db import get_session
from ess.models import Member
from ess.services import outbox, passkeys, portal_auth
from ess.services.access import DomainError
from ess.web.auth import csrf_token
from ess.web.common import after_commit, base_url
from ess.web.public import verify_public_csrf
from ess.web.templates import ERRORS, templates

router = APIRouter()
COOKIE = "ess_member"
Db = Annotated[Session, Depends(get_session)]


def _page(request: Request, name: str, status_code: int = 200, **context):
    return templates.TemplateResponse(request, name, {"csrf": csrf_token(request), **context}, status_code=status_code)


def _browser(request: Request) -> str:
    """Random value of this browser (kept in its session); a login code works only here."""
    value = request.session.get("portal_browser")
    if not value:
        value = request.session["portal_browser"] = secrets.token_urlsafe(16)
    return value


def _member(request: Request, session: Session) -> Member | None:
    return portal_auth.current_member(session, request.cookies.get(COOKIE))


def _secure() -> bool:
    s = get_settings()
    return s.environment == "prod" or (s.public_base_url or "").startswith("https://")


@router.get("/p/{key}")
def login_start(request: Request, key: str, session: Db):
    ecp_pass = portal_auth.pass_for_key(session, key)
    if ecp_pass is None:
        return _page(request, "portal/unavailable.html", status_code=404)
    member = _member(request, session)
    if member is not None and member.id == ecp_pass.member_id:
        return RedirectResponse("/portal", status_code=303)
    return _page(request, "portal/login.html", key=key)


@router.post("/p/{key}/code", dependencies=[Depends(verify_public_csrf)])
def login_send_code(request: Request, key: str, session: Db):
    try:
        portal_auth.send_code(session, key, _browser(request))
        session.commit()
    except DomainError as exc:
        session.rollback()
        outbox.discard(session)
        return _page(request, "portal/login.html", status_code=400, key=key, error=ERRORS.get(exc.code, exc.code))
    after_commit(request, session)
    return RedirectResponse(f"/p/{key}/code", status_code=303)


@router.get("/p/{key}/code")
def login_code_form(request: Request, key: str, session: Db):
    if portal_auth.pass_for_key(session, key) is None:
        return _page(request, "portal/unavailable.html", status_code=404)
    return _page(request, "portal/code.html", key=key)


@router.post("/p/{key}/code/verify", dependencies=[Depends(verify_public_csrf)])
def login_verify(request: Request, key: str, session: Db, code: Annotated[str, Form()] = ""):
    result = portal_auth.verify_code(session, key, _browser(request), code)
    session.commit()  # also a failed attempt
    if isinstance(result, str):
        return _page(request, "portal/code.html", status_code=400, key=key, error=ERRORS.get(result, result),
                     expired=result == "code_expired")
    request.session["portal_offer_passkey"] = True
    return _with_cookie(RedirectResponse("/portal", status_code=303), result)


def _with_cookie(response, new: portal_auth.NewSession):
    response.set_cookie(COOKIE, new.token, max_age=int(portal_auth.SESSION_VALID.total_seconds()),
                        httponly=True, secure=_secure(), samesite="lax", path="/")
    return response


@router.get("/portal")
def home(request: Request, session: Db):
    from ess.services import portal

    member = _member(request, session)
    if member is None:
        response = _page(request, "portal/logged_out.html", status_code=401)
        response.delete_cookie(COOKIE, path="/")
        return response
    offer = request.session.pop("portal_offer_passkey", False) or passkeys.count(session, member.id) == 0
    return _page(request, "portal/home.html", home=portal.home(session, member), offer_passkey=offer)


@router.post("/portal/logout", dependencies=[Depends(verify_public_csrf)])
def logout(request: Request, session: Db):
    portal_auth.log_out(session, request.cookies.get(COOKIE))
    session.commit()
    response = _page(request, "portal/logged_out.html", logged_out=True)
    response.delete_cookie(COOKIE, path="/")
    return response


# --- passkeys (JSON for static/passkey.js) -------------------------------------------------------------


async def _json_csrf(request: Request) -> dict:
    expected = request.session.get("csrf")
    if not expected or not secrets.compare_digest(request.headers.get("x-csrf-token", ""), expected):
        raise HTTPException(status_code=400, detail="csrf")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="json") from None
    return body if isinstance(body, dict) else {}


def _challenge(request: Request, value: bytes | None = None) -> bytes | None:
    if value is not None:
        request.session["passkey_challenge"] = bytes_to_base64url(value)
        return value
    stored = request.session.pop("passkey_challenge", None)
    return base64url_to_bytes(stored) if stored else None


@router.post("/portal/passkey/register-options")
async def passkey_register_options(request: Request, session: Db):
    await _json_csrf(request)
    member = _member(request, session)
    if member is None:
        return JSONResponse({"error": ERRORS["portal_not_available"]}, status_code=401)
    options, challenge = passkeys.registration_options(session, member, base_url(request))
    _challenge(request, challenge)
    return Response(options, media_type="application/json")


@router.post("/portal/passkey/register")
async def passkey_register(request: Request, session: Db):
    body = await _json_csrf(request)
    member = _member(request, session)
    challenge = _challenge(request)
    if member is None or challenge is None:
        return JSONResponse({"error": ERRORS["passkey_failed"]}, status_code=400)
    try:
        passkeys.register(session, member, json.dumps(body.get("credential")), challenge, base_url(request))
        session.commit()
    except DomainError as exc:
        session.rollback()
        return JSONResponse({"error": ERRORS.get(exc.code, exc.code)}, status_code=400)
    return JSONResponse({"ok": True})


@router.post("/portal/passkey/login-options")
async def passkey_login_options(request: Request, session: Db):
    body = await _json_csrf(request)
    options, challenge = passkeys.authentication_options(session, base_url(request), str(body.get("key") or ""))
    _challenge(request, challenge)
    return Response(options, media_type="application/json")


@router.post("/portal/passkey/login")
async def passkey_login(request: Request, session: Db):
    body = await _json_csrf(request)
    challenge = _challenge(request)
    if challenge is None:
        return JSONResponse({"error": ERRORS["passkey_failed"]}, status_code=400)
    result = passkeys.authenticate(session, json.dumps(body.get("credential")), challenge, base_url(request))
    session.commit()
    if isinstance(result, str):
        return JSONResponse({"error": ERRORS.get(result, result)}, status_code=400)
    return _with_cookie(JSONResponse({"ok": True, "redirect": "/portal"}), result)
