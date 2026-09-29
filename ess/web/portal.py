"""Member portal (phase 4): login from the eCP link with an e-mail code (R38) and the member's home page."""

import json
import secrets
import time
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from sqlalchemy.orm import Session
from typing import Annotated

from ess.config import get_settings
from ess.db import get_session
from ess.models import Member
from ess.services import outbox, passkeys, portal_auth
from ess.services.access import Actor, DomainError, PermissionDenied
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
    result = portal_auth.verify_code(session, key, _browser(request), code, device_label(request))
    session.commit()  # also a failed attempt
    if isinstance(result, str):
        return _page(request, "portal/code.html", status_code=400, key=key, error=ERRORS.get(result, result),
                     expired=result == "code_expired")
    request.session["portal_offer_passkey"] = True
    return _signed_in(request, result, RedirectResponse("/portal", status_code=303))


PENDING_SECONDS = 600


def _signed_in(request: Request, result, response):
    """Set the cookie, or – when the member already uses the maximum of devices – let them pick one to log out."""
    if isinstance(result, portal_auth.TooManyDevices):
        request.session["portal_pending"] = {"member_id": str(result.member_id), "method": result.method,
                                             "until": int(time.time()) + PENDING_SECONDS}
        return RedirectResponse("/portal/devices/choose", status_code=303) if isinstance(
            response, RedirectResponse) else JSONResponse({"ok": True, "redirect": "/portal/devices/choose"})
    return _with_cookie(response, result)


def device_label(request: Request) -> str:
    """A short name of the device from the browser, e.g. "Chrome, Android" (no personal data)."""
    ua = request.headers.get("user-agent", "")
    browser = next((name for token, name in (("Edg/", "Edge"), ("SamsungBrowser", "Samsung Internet"),
                                             ("Firefox/", "Firefox"), ("OPR/", "Opera"), ("Chrome/", "Chrome"),
                                             ("Safari/", "Safari")) if token in ua), "prehliadač")
    system = next((name for token, name in (("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"),
                                            ("Windows", "Windows"), ("Mac OS X", "macOS"), ("Linux", "Linux"))
                   if token in ua), "")
    return f"{browser}, {system}" if system else browser


def _pending(request: Request) -> dict | None:
    pending = request.session.get("portal_pending")
    if not pending or pending.get("until", 0) < time.time():
        request.session.pop("portal_pending", None)
        return None
    return pending


@router.get("/portal/devices/choose")
def devices_choose(request: Request, session: Db):
    pending = _pending(request)
    if pending is None:
        return RedirectResponse("/portal", status_code=303)
    return _page(request, "portal/devices_choose.html",
                 devices=portal_auth.devices(session, uuid.UUID(pending["member_id"])))


@router.post("/portal/devices/choose", dependencies=[Depends(verify_public_csrf)])
def devices_replace(request: Request, session: Db, device_id: Annotated[str, Form()] = ""):
    pending = _pending(request)
    if pending is None:
        return RedirectResponse("/portal", status_code=303)
    member_id = uuid.UUID(pending["member_id"])
    try:
        result = portal_auth.open_session(session, member_id, pending["method"], device_label(request),
                                          replace=uuid.UUID(device_id))
        if isinstance(result, portal_auth.TooManyDevices):
            raise DomainError("device_not_found")
        session.commit()
    except (DomainError, ValueError) as exc:
        session.rollback()
        return _page(request, "portal/devices_choose.html", status_code=400, error=ERRORS.get(
            getattr(exc, "code", ""), ERRORS["device_not_found"]), devices=portal_auth.devices(session, member_id))
    request.session.pop("portal_pending", None)
    return _with_cookie(RedirectResponse("/portal", status_code=303), result)


@router.post("/portal/devices/{device_id}/logout", dependencies=[Depends(verify_public_csrf)])
def device_logout(request: Request, device_id: uuid.UUID, session: Db):
    current = portal_auth.current_session(session, request.cookies.get(COOKIE))
    if current is None:
        return RedirectResponse("/portal", status_code=303)
    try:
        portal_auth.log_out_device(session, current.member_id, device_id)
        session.commit()
    except DomainError:
        session.rollback()
    if device_id == current.id:
        response = _page(request, "portal/logged_out.html", logged_out=True)
        response.delete_cookie(COOKIE, path="/")
        return response
    return RedirectResponse("/portal", status_code=303)


def _with_cookie(response, new: portal_auth.NewSession):
    response.set_cookie(COOKIE, new.token, max_age=int(portal_auth.SESSION_VALID.total_seconds()),
                        httponly=True, secure=_secure(), samesite="lax", path="/")
    return response


@router.get("/portal")
def home(request: Request, session: Db):
    from ess.services import portal

    current = portal_auth.current_session(session, request.cookies.get(COOKIE))
    if current is None:
        response = _page(request, "portal/logged_out.html", status_code=401)
        response.delete_cookie(COOKIE, path="/")
        return response
    session.commit()  # last use of the device
    member = session.get(Member, current.member_id)
    offer = request.session.pop("portal_offer_passkey", False) or passkeys.count(session, member.id) == 0
    from ess.services import cave_trips

    return _page(request, "portal/home.html", home=portal.home(session, member), offer_passkey=offer,
                 devices=portal_auth.devices(session, member.id), current_device=current.id,
                 trip=cave_trips.open_trip(session, member.id), flash=request.session.pop("portal_flash", None))


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
    current = portal_auth.current_session(session, request.cookies.get(COOKIE))
    challenge = _challenge(request)
    if current is None or challenge is None:
        return JSONResponse({"error": ERRORS["passkey_failed"]}, status_code=400)
    member = session.get(Member, current.member_id)
    try:
        passkeys.register(session, member, json.dumps(body.get("credential")), challenge, base_url(request),
                          session_id=current.id)
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
    result = passkeys.authenticate(session, json.dumps(body.get("credential")), challenge, base_url(request),
                                   device_label(request))
    session.commit()
    if isinstance(result, str):
        return JSONResponse({"error": ERRORS.get(result, result)}, status_code=400)
    return _signed_in(request, result, JSONResponse({"ok": True, "redirect": "/portal"}))


# --- club (R37) ----------------------------------------------------------------------------------------


@router.get("/portal/clubs/{club_id}")
def club_page(request: Request, club_id: uuid.UUID, session: Db):
    from ess.services import portal

    member = _member(request, session)
    if member is None:
        return RedirectResponse("/portal", status_code=303)
    try:
        view = portal.club_view(session, member, club_id)
    except DomainError:
        return _page(request, "portal/unavailable.html", status_code=404)
    return _page(request, "portal/club.html", view=view, flash=request.session.pop("portal_flash", None))


def _club_action(request: Request, session: Session, club_id: uuid.UUID, action, success: str):
    member = _member(request, session)
    if member is None:
        return RedirectResponse("/portal", status_code=303)
    actor = Actor(kind="member", id=str(member.id))
    try:
        action(actor)
        session.commit()
        request.session["portal_flash"] = {"kind": "ok", "text": success}
    except (DomainError, PermissionDenied) as exc:
        session.rollback()
        request.session["portal_flash"] = {"kind": "error", "text": ERRORS.get(getattr(exc, "code", str(exc)),
                                                                              "Akciu nebolo možné vykonať.")}
    return RedirectResponse(f"/portal/clubs/{club_id}", status_code=303)


@router.post("/portal/clubs/{club_id}/delegate", dependencies=[Depends(verify_public_csrf)])
def club_delegate(request: Request, club_id: uuid.UUID, session: Db, member_id: Annotated[str, Form()] = ""):
    from ess.services import delegations

    def run(actor):
        try:
            target = uuid.UUID(member_id)
        except ValueError:
            raise DomainError("member_required") from None
        delegations.delegate(session, actor, club_id, target)

    return _club_action(request, session, club_id, run, "Správu skupiny ste preniesli na zástupcu.")


@router.post("/portal/clubs/{club_id}/take-back", dependencies=[Depends(verify_public_csrf)])
def club_take_back(request: Request, club_id: uuid.UUID, session: Db):
    from ess.services import delegations

    return _club_action(request, session, club_id, lambda actor: delegations.take_back(session, actor, club_id),
                        "Správu skupiny ste prevzali späť.")


@router.post("/portal/clubs/{club_id}/resign", dependencies=[Depends(verify_public_csrf)])
def club_resign(request: Request, club_id: uuid.UUID, session: Db):
    from ess.services import delegations

    return _club_action(request, session, club_id, lambda actor: delegations.resign(session, actor, club_id),
                        "Administráciu skupiny ste zrušili, práva má znova predseda.")


# --- cave trips (R41) ----------------------------------------------------------------------------------


def _local_datetime(value: str):
    """<input type=datetime-local> in Slovak time -> aware datetime (UTC)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    try:
        return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo("Europe/Bratislava"))
    except ValueError:
        raise DomainError("invalid_return_time") from None


def _trip_action(request: Request, session: Session, action, success: str):
    member = _member(request, session)
    if member is None:
        return RedirectResponse("/portal", status_code=303)
    try:
        action(member)
        session.commit()
        request.session["portal_flash"] = {"kind": "ok", "text": success}
    except DomainError as exc:
        session.rollback()
        request.session["portal_flash"] = {"kind": "error", "text": ERRORS.get(exc.code, exc.code)}
    return RedirectResponse("/portal#jaskyna", status_code=303)


@router.post("/portal/cave", dependencies=[Depends(verify_public_csrf)])
def cave_start(request: Request, session: Db, cave: Annotated[str, Form()] = "",
               companions: Annotated[str, Form()] = "", planned_return: Annotated[str, Form()] = ""):
    from ess.services import cave_trips

    return _trip_action(request, session, lambda m: cave_trips.start(session, m.id, cave, companions,
                                                                     _local_datetime(planned_return)),
                        "Vstup do jaskyne je nahlásený. Po návrate kliknite na „Som vonku“.")


@router.post("/portal/cave/extend", dependencies=[Depends(verify_public_csrf)])
def cave_extend(request: Request, session: Db, planned_return: Annotated[str, Form()] = ""):
    from ess.services import cave_trips

    return _trip_action(request, session, lambda m: cave_trips.extend(session, m.id, _local_datetime(planned_return)),
                        "Čas návratu bol predĺžený.")


@router.post("/portal/cave/finish", dependencies=[Depends(verify_public_csrf)])
def cave_finish(request: Request, session: Db):
    from ess.services import cave_trips

    return _trip_action(request, session, lambda m: cave_trips.finish(session, m.id), "Vitajte späť!")


# --- scheduler -----------------------------------------------------------------------------------------


@router.post("/internal/tick")
def scheduler_tick(request: Request, session: Db):
    """Called by Cloud Scheduler every 5 minutes: cave trip reminders, then waiting Wallet batches."""
    from ess.services import cave_trips

    token = get_settings().scheduler_token
    given = request.headers.get("x-ess-scheduler-token", "")
    if not token or not secrets.compare_digest(given, token):
        raise HTTPException(status_code=404)
    result = cave_trips.check(session)
    session.commit()
    after_commit(request, session)
    return JSONResponse({"reminders": result.reminders, "alerts": result.alerts, "no_chair": result.no_chair})
