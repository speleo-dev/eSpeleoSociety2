"""Administration: member forms and actions on a member (memberships, positions, certificates, expulsion)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from ess.models import Member, MembershipStatus
from ess.cards import render_card_pdf
from ess.mail import Mailer, get_mailer
from ess.services import certificates, directory, ecp_applications, members, memberships, outbox, positions, sss_cards
from ess.services.access import DomainError, PermissionDenied
from ess.services.members import MemberData
from ess.web.auth import verify_csrf
from ess.web.common import Admin, Db, act, after_commit, base_url, error_text, parse_date, render
from ess.web.mailing import render_mail, send

MailerDep = Annotated[Mailer | None, Depends(get_mailer)]

router = APIRouter(prefix="/admin")

S = MembershipStatus
MEMBER_FIELDS = ("title_before", "first_name", "last_name", "title_after", "birth_date", "email", "phone",
                 "street", "city", "postal_code", "country", "card_number", "member_since")


async def _member_form(request: Request) -> tuple[MemberData, dict]:
    """Read the member form. Returns parsed data and the raw values (to re-fill the form on error)."""
    form = await request.form()
    raw = {f: str(form.get(f, "")).strip() for f in MEMBER_FIELDS}
    raw["reduced_fee"] = form.get("reduced_fee") == "on"
    data = MemberData(
        first_name=raw["first_name"],
        last_name=raw["last_name"],
        title_before=raw["title_before"] or None,
        title_after=raw["title_after"] or None,
        birth_date=parse_date(raw["birth_date"]),
        email=raw["email"] or None,
        phone=raw["phone"] or None,
        street=raw["street"] or None,
        city=raw["city"] or None,
        postal_code=raw["postal_code"] or None,
        country=raw["country"] or "SK",
        card_number=raw["card_number"] or None,
        member_since=parse_date(raw["member_since"]),
        reduced_fee=raw["reduced_fee"],
    )
    return data, raw


def _raw_from(data: MemberData) -> dict:
    raw = {f: getattr(data, f) or "" for f in MEMBER_FIELDS}
    for f in ("birth_date", "member_since"):
        raw[f] = getattr(data, f).isoformat() if getattr(data, f) else ""
    raw["reduced_fee"] = data.reduced_fee
    return raw


@router.get("/members/new")
def member_new(request: Request, admin: Admin, session: Db):
    return render(request, "admin/member_form.html", admin, session, raw={}, member_id=None,
                  clubs=directory.active_clubs(session), S=S, club_id="", status="member")


@router.post("/members/new", dependencies=[Depends(verify_csrf)])
async def member_create(request: Request, admin: Admin, session: Db):
    form = await request.form()
    club_id, status = str(form.get("club_id", "")), str(form.get("status", "member"))
    issue_ecp = form.get("issue_ecp") == "on"
    raw: dict = {}
    try:
        data, raw = await _member_form(request)
        if not club_id:
            raise DomainError("club_required")
        membership = memberships.add_new_member_to_club(session, admin.actor, data, uuid.UUID(club_id), S(status))
        if issue_ecp:
            ecp_applications.request_for_new_member(session, admin.actor, membership.member_id, membership.club_id)
        session.commit()
    except (DomainError, PermissionDenied) as exc:
        outbox.discard(session)
        session.rollback()
        return render(request, "admin/member_form.html", admin, session, status_code=400, raw=raw, member_id=None,
                      clubs=directory.active_clubs(session), S=S, club_id=club_id, status=status, error=error_text(exc),
                      issue_ecp=issue_ecp)
    text = "Člen bol pridaný." + (" Poslali sme mu e-mail na nahratie fotky pre eCP." if issue_ecp else "")
    if not after_commit(request, session):
        text = "Člen bol pridaný, ale e-mail na nahratie fotky sa nepodarilo odoslať."
    request.session["flash"] = {"kind": "ok", "text": text}
    return RedirectResponse(f"/admin/members/{membership.member_id}", status_code=303)


@router.get("/members/{member_id}/edit")
def member_edit(request: Request, member_id: uuid.UUID, admin: Admin, session: Db):
    member = session.get(Member, member_id)
    if member is None:
        return render(request, "admin/not_found.html", admin, session)
    return render(request, "admin/member_form.html", admin, session, raw=_raw_from(members.read_member(member)),
                  member_id=member_id)


@router.post("/members/{member_id}/edit", dependencies=[Depends(verify_csrf)])
async def member_update(request: Request, member_id: uuid.UUID, admin: Admin, session: Db):
    raw: dict = {}
    try:
        data, raw = await _member_form(request)
        members.update_member(session, admin.actor, member_id, data)
        session.commit()
    except (DomainError, PermissionDenied) as exc:
        session.rollback()
        return render(request, "admin/member_form.html", admin, session, status_code=400, raw=raw,
                      member_id=member_id, error=error_text(exc))
    request.session["flash"] = {"kind": "ok", "text": "Údaje boli uložené."}
    return RedirectResponse(f"/admin/members/{member_id}", status_code=303)


def _back(member_id: uuid.UUID) -> str:
    return f"/admin/members/{member_id}"


@router.post("/members/{member_id}/memberships", dependencies=[Depends(verify_csrf)])
def membership_add(
    request: Request, member_id: uuid.UUID, admin: Admin, session: Db,
    club_id: Annotated[str, Form()], status: Annotated[str, Form()] = "member",
):
    return act(request, session, _back(member_id),
               lambda: memberships.add_membership(session, admin.actor, member_id, uuid.UUID(club_id), S(status)),
               "Člen bol pridaný do skupiny.")


@router.post("/memberships/{membership_id}/primary", dependencies=[Depends(verify_csrf)])
def membership_primary(
    request: Request, membership_id: uuid.UUID, admin: Admin, session: Db, back: Annotated[str, Form()] = "/admin"
):
    return act(request, session, back, lambda: memberships.set_primary(session, admin.actor, membership_id),
               "Primárna skupina bola zmenená.")


@router.post("/members/{member_id}/expel", dependencies=[Depends(verify_csrf)])
def member_expel(
    request: Request, member_id: uuid.UUID, admin: Admin, session: Db,
    reason: Annotated[str, Form()] = "", on: Annotated[str, Form()] = "",
):
    return act(request, session, _back(member_id),
               lambda: members.expel_member(session, admin.actor, member_id, reason, parse_date(on)),
               "Člen bol vylúčený zo SSS.")


@router.post("/members/{member_id}/positions", dependencies=[Depends(verify_csrf)])
def position_assign(
    request: Request, member_id: uuid.UUID, admin: Admin, session: Db,
    position_code: Annotated[str, Form()], club_id: Annotated[str, Form()] = "",
    valid_from: Annotated[str, Form()] = "", back: Annotated[str, Form()] = "",
):
    return act(request, session, back or _back(member_id),
               lambda: positions.assign_position(session, admin.actor, position_code, member_id,
                                                 uuid.UUID(club_id) if club_id else None, parse_date(valid_from)),
               "Funkcia bola priradená.")


@router.post("/positions", dependencies=[Depends(verify_csrf)])
def position_assign_any(
    request: Request, admin: Admin, session: Db, member_id: Annotated[str, Form()] = "",
    position_code: Annotated[str, Form()] = "", club_id: Annotated[str, Form()] = "",
    valid_from: Annotated[str, Form()] = "", back: Annotated[str, Form()] = "/admin/organization",
):
    def assign():
        if not member_id:
            raise DomainError("member_required")
        positions.assign_position(session, admin.actor, position_code, uuid.UUID(member_id),
                                  uuid.UUID(club_id) if club_id else None, parse_date(valid_from))

    return act(request, session, back, assign, "Funkcia bola priradená.")


@router.post("/positions/{holder_id}/end", dependencies=[Depends(verify_csrf)])
def position_end(
    request: Request, holder_id: uuid.UUID, admin: Admin, session: Db,
    on: Annotated[str, Form()] = "", back: Annotated[str, Form()] = "/admin/organization",
):
    return act(request, session, back, lambda: positions.end_position(session, admin.actor, holder_id, parse_date(on)),
               "Funkcia bola ukončená.")


@router.post("/members/{member_id}/certificates", dependencies=[Depends(verify_csrf)])
def certificate_add(
    request: Request, member_id: uuid.UUID, admin: Admin, session: Db,
    certificate_type_id: Annotated[str, Form()], valid_from: Annotated[str, Form()] = "",
    valid_to: Annotated[str, Form()] = "", note: Annotated[str, Form()] = "",
):
    return act(request, session, _back(member_id),
               lambda: certificates.add_certificate(session, admin.actor, member_id, uuid.UUID(certificate_type_id),
                                                    parse_date(valid_from), parse_date(valid_to), note),
               "Certifikát bol pridaný.")


@router.post("/certificates/{certificate_id}/delete", dependencies=[Depends(verify_csrf)])
def certificate_delete(
    request: Request, certificate_id: uuid.UUID, admin: Admin, session: Db, back: Annotated[str, Form()] = "/admin"
):
    return act(request, session, back, lambda: certificates.remove_certificate(session, admin.actor, certificate_id),
               "Certifikát bol odstránený.")


def _deliver_card(request: Request, session, mailer, back: str, make, delivery: str):
    """Create or look up the card, commit, then return the PDF or send it by e-mail."""
    try:
        issued = make()
        if delivery == "email" and not issued.email:
            raise DomainError("card_needs_email")
        pdf = render_card_pdf(issued.content)
        session.commit()
    except (DomainError, PermissionDenied) as exc:
        session.rollback()
        request.session["flash"] = {"kind": "error", "text": error_text(exc)}
        return RedirectResponse(back, status_code=303)
    year = issued.card.year
    filename = f"karticka-sss-{year}.pdf"
    if delivery == "email":
        sent = send(mailer, render_mail(issued.email, f"Kartička SSS na rok {year}", "sss_card",
                                        attachments=[(filename, pdf, "application/pdf")],
                                        first_name=issued.first_name, year=year))
        request.session["flash"] = ({"kind": "ok", "text": f"Kartička na rok {year} bola odoslaná e-mailom."} if sent
                                    else {"kind": "error", "text": "E-mail s kartičkou sa nepodarilo odoslať."})
        return RedirectResponse(back, status_code=303)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


@router.post("/members/{member_id}/card", dependencies=[Depends(verify_csrf)])
def issue_card(request: Request, member_id: uuid.UUID, admin: Admin, session: Db, mailer: MailerDep,
               year: Annotated[int, Form()], delivery: Annotated[str, Form()] = "download"):
    """First SSS card of the year (R31)."""
    return _deliver_card(request, session, mailer, f"/admin/members/{member_id}",
                         lambda: sss_cards.issue(session, admin.actor, member_id, year, base_url(request)), delivery)


@router.post("/cards/{card_id}/again", dependencies=[Depends(verify_csrf)])
def card_again(request: Request, card_id: uuid.UUID, admin: Admin, session: Db, mailer: MailerDep,
               member_id: Annotated[uuid.UUID, Form()], delivery: Annotated[str, Form()] = "download"):
    """The same card (same QR) again – e.g. a printing problem or a lost e-mail."""
    return _deliver_card(request, session, mailer, f"/admin/members/{member_id}",
                         lambda: sss_cards.again(session, admin.actor, card_id, base_url(request)), delivery)


@router.post("/cards/{card_id}/replace", dependencies=[Depends(verify_csrf)])
def card_replace(request: Request, card_id: uuid.UUID, admin: Admin, session: Db, mailer: MailerDep,
                 member_id: Annotated[uuid.UUID, Form()], reason: Annotated[str, Form()],
                 delivery: Annotated[str, Form()] = "download"):
    """Lost / stolen / damaged card: the old QR shows that state, a new card is issued (R32)."""
    return _deliver_card(request, session, mailer, f"/admin/members/{member_id}",
                         lambda: sss_cards.replace(session, admin.actor, card_id, reason, base_url(request)), delivery)
