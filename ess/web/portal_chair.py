"""Member portal – club management by the chair or the chair's delegate (phase 5, R37).

Every action goes through the services, which check `can_manage_club` again (the chair while represented
by a delegate only reads). Only members of the managed club are shown or changed here.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ess.cards import render_card
from ess.db import get_session
from ess.models import Club, Member, Membership, MembershipStatus, PaymentReference
from ess.services import (
    ecp_applications,
    members,
    memberships,
    outbox,
    payments,
    sss_cards,
)
from ess.services.access import Actor, DomainError, PermissionDenied, can_manage_club
from ess.web.admin_members import _member_form, _raw_from
from ess.web.common import after_commit, base_url
from ess.web.portal import COOKIE, _page
from ess.web.public import verify_public_csrf
from ess.web.templates import ERRORS

router = APIRouter(prefix="/portal/clubs/{club_id}")
Db = Annotated[Session, Depends(get_session)]
S = MembershipStatus

# Status changes a club manager may do, with button texts (the service checks them again).
CHAIR_TRANSITIONS = {
    S.CANDIDATE: [(S.PENDING_ACTIVATION, "Navrhnúť za člena")],
    S.PENDING_ACTIVATION: [(S.CANDIDATE, "Vrátiť medzi čakateľov")],
    S.MEMBER: [(S.SUSPENDED, "Pozastaviť členstvo")],
    S.SUSPENDED: [(S.MEMBER, "Obnoviť členstvo")],
}


class NotManager(Exception):
    pass


def _context(request: Request, session: Session, club_id: uuid.UUID) -> tuple[Member, Actor, Club]:
    from ess.services import portal_auth

    member = portal_auth.current_member(session, request.cookies.get(COOKIE))
    club = session.get(Club, club_id)
    if member is None or club is None:
        raise NotManager()
    actor = Actor(kind="member", id=str(member.id))
    if not can_manage_club(session, actor, club):
        raise NotManager()
    return member, actor, club


def _denied(request: Request):
    return _page(request, "portal/unavailable.html", status_code=403)


def _club_membership(session: Session, club_id: uuid.UUID, member_id: uuid.UUID) -> Membership:
    membership = session.scalar(select(Membership).where(Membership.club_id == club_id,
                                                         Membership.member_id == member_id,
                                                         Membership.valid_to.is_(None)))
    if membership is None:
        raise DomainError("member_not_found")
    return membership


def _flash(request: Request, kind: str, text: str) -> None:
    request.session["portal_flash"] = {"kind": kind, "text": text}


def _error(exc: Exception) -> str:
    return ERRORS.get(getattr(exc, "code", str(exc)), "Akciu nebolo možné vykonať.")


def _run(request: Request, session: Session, back: str, action, success: str):
    try:
        action()
        session.commit()
        _flash(request, "ok", success)
        if not after_commit(request, session):
            _flash(request, "error", success + " E-mail sa však nepodarilo odoslať.")
    except (DomainError, PermissionDenied) as exc:
        outbox.discard(session)
        session.rollback()
        _flash(request, "error", _error(exc))
    return RedirectResponse(back, status_code=303)


# --- members -------------------------------------------------------------------------------------------


@router.get("/members/new")
def member_new(request: Request, club_id: uuid.UUID, session: Db):
    try:
        _, _, club = _context(request, session, club_id)
    except NotManager:
        return _denied(request)
    return _page(request, "portal/member_form.html", club=club, raw={}, member_id=None, status="candidate")


@router.post("/members/new", dependencies=[Depends(verify_public_csrf)])
async def member_create(request: Request, club_id: uuid.UUID, session: Db):
    try:
        _, actor, club = _context(request, session, club_id)
    except NotManager:
        return _denied(request)
    form = await request.form()
    status = S.PENDING_ACTIVATION if form.get("status") == "pending_activation" else S.CANDIDATE
    issue_ecp = form.get("issue_ecp") == "on"
    raw: dict = {}
    try:
        data, raw = await _member_form(request)
        data.reduced_fee = False  # set by administrators only
        membership = memberships.add_new_member_to_club(session, actor, data, club_id, status)
        if issue_ecp:
            ecp_applications.request_for_new_member(session, actor, membership.member_id, club_id)
        session.commit()
    except (DomainError, PermissionDenied) as exc:
        outbox.discard(session)
        session.rollback()
        return _page(request, "portal/member_form.html", status_code=400, club=club, raw=raw, member_id=None,
                     status=status.value, issue_ecp=issue_ecp, error=_error(exc))
    text = ("Čakateľ bol pridaný." if status == S.CANDIDATE
            else "Nový člen bol navrhnutý – administrátor ho aktivuje po doručení prihlášky.")
    if issue_ecp:
        text += " Po aktivácii mu príde e-mail na nahratie fotky pre eCP."
    after_commit(request, session)
    _flash(request, "ok", text)
    return RedirectResponse(f"/portal/clubs/{club_id}/members/{membership.member_id}", status_code=303)


@router.get("/members/{member_id}")
def member_page(request: Request, club_id: uuid.UUID, member_id: uuid.UUID, session: Db):
    try:
        _, _, club = _context(request, session, club_id)
        membership = _club_membership(session, club_id, member_id)
    except (NotManager, DomainError):
        return _denied(request)
    target = session.get(Member, member_id)
    years = sss_cards.allowed_years(session)
    return _page(request, "portal/member.html", club=club, m=membership, data=members.read_member(target),
                 target=target, transitions=CHAIR_TRANSITIONS.get(membership.status, []),
                 card_years=[y for y in years if sss_cards.can_issue(session, member_id, y)],
                 fees={f.year: f for f in payments.member_fees(session, member_id)}, fee_years=years,
                 flash=request.session.pop("portal_flash", None))


@router.get("/members/{member_id}/edit")
def member_edit(request: Request, club_id: uuid.UUID, member_id: uuid.UUID, session: Db):
    try:
        _, _, club = _context(request, session, club_id)
        _club_membership(session, club_id, member_id)
    except (NotManager, DomainError):
        return _denied(request)
    return _page(request, "portal/member_form.html", club=club, member_id=member_id,
                 raw=_raw_from(members.read_member(session.get(Member, member_id))))


@router.post("/members/{member_id}/edit", dependencies=[Depends(verify_public_csrf)])
async def member_update(request: Request, club_id: uuid.UUID, member_id: uuid.UUID, session: Db):
    try:
        _, actor, club = _context(request, session, club_id)
        _club_membership(session, club_id, member_id)
    except (NotManager, DomainError):
        return _denied(request)
    raw: dict = {}
    try:
        data, raw = await _member_form(request)
        data.reduced_fee = session.get(Member, member_id).reduced_fee  # not changed here
        members.update_member(session, actor, member_id, data)
        session.commit()
    except (DomainError, PermissionDenied) as exc:
        session.rollback()
        return _page(request, "portal/member_form.html", status_code=400, club=club, member_id=member_id, raw=raw,
                     error=_error(exc))
    _flash(request, "ok", "Údaje boli uložené.")
    return RedirectResponse(f"/portal/clubs/{club_id}/members/{member_id}", status_code=303)


@router.post("/memberships/{membership_id}/status", dependencies=[Depends(verify_public_csrf)])
def membership_status(request: Request, club_id: uuid.UUID, membership_id: uuid.UUID, session: Db,
                      new_status: Annotated[str, Form()] = ""):
    try:
        _, actor, _ = _context(request, session, club_id)
    except NotManager:
        return _denied(request)
    membership = session.get(Membership, membership_id)
    if membership is None or membership.club_id != club_id:
        return _denied(request)
    back = f"/portal/clubs/{club_id}/members/{membership.member_id}"
    try:
        target = S(new_status)
    except ValueError:
        return _denied(request)
    return _run(request, session, back, lambda: memberships.change_status(session, actor, membership_id, target),
                "Stav členstva bol zmenený.")


@router.post("/memberships/{membership_id}/terminate", dependencies=[Depends(verify_public_csrf)])
def membership_terminate(request: Request, club_id: uuid.UUID, membership_id: uuid.UUID, session: Db):
    try:
        _, actor, _ = _context(request, session, club_id)
    except NotManager:
        return _denied(request)
    membership = session.get(Membership, membership_id)
    if membership is None or membership.club_id != club_id:
        return _denied(request)
    return _run(request, session, f"/portal/clubs/{club_id}",
                lambda: memberships.terminate(session, actor, membership_id),
                "Členstvo v skupine bolo ukončené (členom SSS ostáva, kým nerozhodne administrátor).")


@router.post("/members/{member_id}/card", dependencies=[Depends(verify_public_csrf)])
def issue_card(request: Request, club_id: uuid.UUID, member_id: uuid.UUID, session: Db,
               year: Annotated[int, Form()] = 0, card_format: Annotated[str, Form()] = "pdf"):
    """First SSS card of the year (R33) – downloaded here and printed by the chair."""
    try:
        _, actor, _ = _context(request, session, club_id)
        _club_membership(session, club_id, member_id)
    except (NotManager, DomainError):
        return _denied(request)
    try:
        issued = sss_cards.issue(session, actor, member_id, year, base_url(request), card_format)
        data, mime, filename = render_card(issued.content, card_format)
        session.commit()
    except (DomainError, PermissionDenied) as exc:
        session.rollback()
        _flash(request, "error", _error(exc))
        return RedirectResponse(f"/portal/clubs/{club_id}/members/{member_id}", status_code=303)
    return Response(data, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


# --- fees and bulk payment -----------------------------------------------------------------------------


@router.get("/payments")
def payments_page(request: Request, club_id: uuid.UUID, session: Db, year: int | None = None):
    try:
        _, actor, club = _context(request, session, club_id)
    except NotManager:
        return _denied(request)
    years = payments.payment_years(session)
    year = year if year in years else years[-1]
    rows = payments.overview(session, actor, year, club_id)
    return _page(request, "portal/payments.html", club=club, year=year, years=years, rows=rows,
                 paid=sum(1 for r in rows if r.paid_at),
                 candidates=payments.bulk_candidates(session, actor, club_id, year),
                 open_refs=payments.open_bulk_references(session, club_id),
                 flash=request.session.pop("portal_flash", None))


@router.post("/payments", dependencies=[Depends(verify_public_csrf)])
async def bulk_create(request: Request, club_id: uuid.UUID, session: Db):
    try:
        _, actor, _ = _context(request, session, club_id)
    except NotManager:
        return _denied(request)
    form = await request.form()
    back = f"/portal/clubs/{club_id}/payments"
    try:
        year = int(form.get("year", ""))
        chosen = [uuid.UUID(v) for v in form.getlist("member_id")]
        reference = payments.create_bulk(session, actor, club_id, year, chosen)
        session.commit()
    except ValueError:
        _flash(request, "error", ERRORS["invalid_value"])
        return RedirectResponse(back, status_code=303)
    except (DomainError, PermissionDenied) as exc:
        session.rollback()
        _flash(request, "error", _error(exc))
        return RedirectResponse(back, status_code=303)
    return RedirectResponse(f"{back}/{reference.id}", status_code=303)


def _reference(session: Session, club_id: uuid.UUID, reference_id: uuid.UUID) -> PaymentReference:
    reference = session.get(PaymentReference, reference_id)
    if reference is None or reference.club_id != club_id or reference.kind != payments.K.BULK.value:
        raise DomainError("reference_not_found")
    return reference


@router.get("/payments/{reference_id}")
def bulk_page(request: Request, club_id: uuid.UUID, reference_id: uuid.UUID, session: Db):
    try:
        _, _, club = _context(request, session, club_id)
        reference = _reference(session, club_id, reference_id)
    except (NotManager, DomainError):
        return _denied(request)
    link, link_error = None, None
    if reference.status in payments.UNFINISHED:
        try:
            link = payments.payme_url(session, reference)
        except DomainError as exc:
            link_error = _error(exc)
    return _page(request, "portal/bulk_payment.html", club=club, ref=reference, link=link, link_error=link_error,
                 lines=payments.reference_lines(session, reference), remaining=payments.remaining(reference),
                 flash=request.session.pop("portal_flash", None))


@router.post("/payments/{reference_id}/cancel", dependencies=[Depends(verify_public_csrf)])
def bulk_cancel(request: Request, club_id: uuid.UUID, reference_id: uuid.UUID, session: Db):
    try:
        _, actor, _ = _context(request, session, club_id)
        _reference(session, club_id, reference_id)
    except (NotManager, DomainError):
        return _denied(request)
    return _run(request, session, f"/portal/clubs/{club_id}/payments",
                lambda: payments.cancel_reference(session, actor, reference_id), "Platobný odkaz bol zrušený.")

