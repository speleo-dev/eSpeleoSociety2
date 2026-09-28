"""Administration: clubs, organisation structure, administrative access, settings and documents."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from ess.models import AdminRole, Club, MembershipStatus
from ess.services import admin_access, certificates, clubs, directory, documents, settings
from ess.services.access import DomainError, PermissionDenied
from ess.web.auth import verify_csrf
from ess.web.common import Admin, Db, act, error_text, forbidden, parse_date, render

router = APIRouter(prefix="/admin")

SETTING_KEYS = ("fee_amount", "reduced_fee_amount", "reduced_fee_age", "fee_currency")


# --- clubs --------------------------------------------------------------------------------------------

@router.get("/clubs/new")
def club_new(request: Request, admin: Admin, session: Db):
    return render(request, "admin/club_form.html", admin, session, club=None, raw={"uses_candidates": True})


@router.post("/clubs/new", dependencies=[Depends(verify_csrf)])
def club_create(
    request: Request, admin: Admin, session: Db, name: Annotated[str, Form()] = "",
    short_name: Annotated[str, Form()] = "", uses_candidates: Annotated[str, Form()] = "",
):
    raw = {"name": name, "short_name": short_name, "uses_candidates": uses_candidates == "on"}
    try:
        club = clubs.create_club(session, admin.actor, name, short_name, raw["uses_candidates"])
        session.commit()
    except (DomainError, PermissionDenied) as exc:
        session.rollback()
        return render(request, "admin/club_form.html", admin, session, status_code=400, club=None, raw=raw,
                      error=error_text(exc))
    request.session["flash"] = {"kind": "ok", "text": "Skupina bola vytvorená."}
    return RedirectResponse(f"/admin/clubs/{club.id}", status_code=303)


@router.get("/clubs/{club_id}")
def club_page(request: Request, club_id: uuid.UUID, admin: Admin, session: Db):
    club = session.get(Club, club_id)
    if club is None:
        return render(request, "admin/not_found.html", admin, session)
    chairs = [h for h in directory.current_positions(session) if h.club_id == club_id]
    active_members = directory.list_members(session, club_id=club_id, status=MembershipStatus.MEMBER)
    raw = {"name": club.name, "short_name": club.short_name or "", "uses_candidates": club.uses_candidates,
           "active": club.active}
    return render(request, "admin/club_form.html", admin, session, club=club, raw=raw, chairs=chairs,
                  active_members=active_members)


@router.post("/clubs/{club_id}", dependencies=[Depends(verify_csrf)])
def club_update(
    request: Request, club_id: uuid.UUID, admin: Admin, session: Db, name: Annotated[str, Form()] = "",
    short_name: Annotated[str, Form()] = "", uses_candidates: Annotated[str, Form()] = "",
    active: Annotated[str, Form()] = "",
):
    return act(request, session, f"/admin/clubs/{club_id}",
               lambda: clubs.update_club(session, admin.actor, club_id, name, short_name,
                                         uses_candidates == "on", active == "on"),
               "Skupina bola uložená.")


# --- organisation structure ---------------------------------------------------------------------------

@router.get("/organization")
def organization(request: Request, admin: Admin, session: Db):
    return render(request, "admin/organization.html", admin, session, holders=directory.current_positions(session))


# --- administrative access (system administrators only) -----------------------------------------------

@router.get("/access")
def access_page(request: Request, admin: Admin, session: Db):
    if not admin.is_system_admin:
        return forbidden(request, admin, session)
    return render(request, "admin/access.html", admin, session, users=admin_access.list_users(session),
                  roles=list(AdminRole))


@router.post("/access", dependencies=[Depends(verify_csrf)])
def access_grant(
    request: Request, admin: Admin, session: Db, email: Annotated[str, Form()] = "",
    name: Annotated[str, Form()] = "", role: Annotated[str, Form()] = "admin",
):
    return act(request, session, "/admin/access",
               lambda: admin_access.grant_access(session, admin.actor, email, name, AdminRole(role)),
               "Prístup bol udelený.")


@router.post("/access/{user_id}/revoke", dependencies=[Depends(verify_csrf)])
def access_revoke(request: Request, user_id: uuid.UUID, admin: Admin, session: Db):
    return act(request, session, "/admin/access", lambda: admin_access.revoke_access(session, admin.actor, user_id),
               "Prístup bol odobratý.")


# --- settings (system administrators only) ------------------------------------------------------------

@router.get("/settings")
def settings_page(request: Request, admin: Admin, session: Db):
    if not admin.is_system_admin:
        return forbidden(request, admin, session)
    values = {k: settings.get_setting(session, k) or "" for k in SETTING_KEYS}
    return render(request, "admin/settings.html", admin, session, values=values,
                  cert_types=certificates.active_types(session))


@router.post("/settings", dependencies=[Depends(verify_csrf)])
async def settings_save(request: Request, admin: Admin, session: Db):
    form = await request.form()

    def save():
        for key in SETTING_KEYS:
            new = str(form.get(key, "")).strip()
            if new != (settings.get_setting(session, key) or ""):
                settings.set_setting(session, admin.actor, key, new)

    return act(request, session, "/admin/settings", save, "Nastavenia boli uložené.")


@router.post("/settings/certificate-types", dependencies=[Depends(verify_csrf)])
def certificate_type_add(
    request: Request, admin: Admin, session: Db, code: Annotated[str, Form()] = "", name: Annotated[str, Form()] = ""
):
    return act(request, session, "/admin/settings",
               lambda: certificates.add_certificate_type(session, admin.actor, code, name),
               "Typ certifikátu bol pridaný.")


# --- documents ----------------------------------------------------------------------------------------

@router.get("/documents")
def documents_page(request: Request, admin: Admin, session: Db):
    return render(request, "admin/documents.html", admin, session, docs=documents.all_documents(session))


@router.post("/documents", dependencies=[Depends(verify_csrf)])
def document_save(
    request: Request, admin: Admin, session: Db, title: Annotated[str, Form()] = "", url: Annotated[str, Form()] = "",
    valid_until: Annotated[str, Form()] = "", sort_order: Annotated[int, Form()] = 0,
    document_id: Annotated[str, Form()] = "",
):
    return act(request, session, "/admin/documents",
               lambda: documents.save_document(session, admin.actor, title, url, parse_date(valid_until), sort_order,
                                               uuid.UUID(document_id) if document_id else None),
               "Dokument bol uložený.")


@router.post("/documents/{document_id}/delete", dependencies=[Depends(verify_csrf)])
def document_delete(request: Request, document_id: uuid.UUID, admin: Admin, session: Db):
    return act(request, session, "/admin/documents", lambda: documents.delete_document(session, admin.actor, document_id),
               "Dokument bol odstránený.")
