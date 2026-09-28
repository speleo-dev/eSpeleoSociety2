"""Administration: clubs, organisation structure, administrative access, settings and documents."""

import csv
import io
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from ess import audit
from ess.images import MAX_UPLOAD_BYTES
from ess.mail import Mail, Mailer, MailError, get_mailer
from ess.models import AdminRole, Club, MembershipStatus
from ess.services import admin_access, certificates, clubs, directory, documents, importing, settings
from ess.services.access import DomainError, PermissionDenied
from ess.storage import MediaStore, get_media_store
from ess.web.auth import verify_csrf
from ess.web.common import Admin, Db, act, error_text, forbidden, parse_date, render

Store = Annotated[MediaStore | None, Depends(get_media_store)]
Mailer_ = Annotated[Mailer | None, Depends(get_mailer)]

router = APIRouter(prefix="/admin")

SETTING_KEYS = ("fee_amount", "reduced_fee_amount", "reduced_fee_age", "fee_currency",
                "ecp_link_valid_hours", "ecp_application_expiry_days", "ecp_qr_grace_minutes", "ecp_qr_daily_limit")


# --- clubs --------------------------------------------------------------------------------------------

@router.get("/clubs/new")
def club_new(request: Request, admin: Admin, session: Db):
    return render(request, "admin/club_form.html", admin, session, club=None, raw={"uses_candidates": True})


@router.post("/clubs/new", dependencies=[Depends(verify_csrf)])
def club_create(
    request: Request, admin: Admin, session: Db, name: Annotated[str, Form()] = "",
    short_name: Annotated[str, Form()] = "", uses_candidates: Annotated[str, Form()] = "",
    code: Annotated[str, Form()] = "", logo_url: Annotated[str, Form()] = "",
):
    raw = {"name": name, "short_name": short_name, "uses_candidates": uses_candidates == "on", "code": code,
           "logo_url": logo_url}
    try:
        club = clubs.create_club(session, admin.actor, name, short_name, raw["uses_candidates"], code, logo_url)
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
           "active": club.active, "code": club.code or "", "logo_url": club.logo_url or ""}
    return render(request, "admin/club_form.html", admin, session, club=club, raw=raw, chairs=chairs,
                  active_members=active_members)


@router.post("/clubs/{club_id}", dependencies=[Depends(verify_csrf)])
def club_update(
    request: Request, club_id: uuid.UUID, admin: Admin, session: Db, name: Annotated[str, Form()] = "",
    short_name: Annotated[str, Form()] = "", uses_candidates: Annotated[str, Form()] = "",
    active: Annotated[str, Form()] = "", code: Annotated[str, Form()] = "", logo_url: Annotated[str, Form()] = "",
):
    return act(request, session, f"/admin/clubs/{club_id}",
               lambda: clubs.update_club(session, admin.actor, club_id, name, short_name,
                                         uses_candidates == "on", active == "on", code, logo_url),
               "Skupina bola uložená.")


def _logo_action(request: Request, session: Db, store: MediaStore | None, club_id: uuid.UUID, action, success: str):
    """Change the logo; delete the replaced object only after commit and the new one on failure."""
    change = None
    try:
        change = action()
        session.commit()
        request.session["flash"] = {"kind": "ok", "text": success}
    except (DomainError, PermissionDenied) as exc:
        session.rollback()
        request.session["flash"] = {"kind": "error", "text": error_text(exc)}
        return RedirectResponse(f"/admin/clubs/{club_id}", status_code=303)
    except Exception:
        session.rollback()
        if change and change.new_object and store:
            store.delete(change.new_object)
        raise
    if change.old_object and store:
        store.delete(change.old_object)
    return RedirectResponse(f"/admin/clubs/{club_id}", status_code=303)


@router.post("/clubs/{club_id}/logo", dependencies=[Depends(verify_csrf)])
def club_logo_upload(request: Request, club_id: uuid.UUID, admin: Admin, session: Db, store: Store,
                           logo: Annotated[UploadFile, File()]):
    data = logo.file.read(MAX_UPLOAD_BYTES + 1)  # sync handler runs in a thread pool
    return _logo_action(request, session, store, club_id,
                        lambda: clubs.set_logo(session, admin.actor, club_id, data, store), "Logo bolo nahraté.")


@router.post("/clubs/{club_id}/logo/remove", dependencies=[Depends(verify_csrf)])
def club_logo_remove(request: Request, club_id: uuid.UUID, admin: Admin, session: Db, store: Store):
    return _logo_action(request, session, store, club_id,
                        lambda: clubs.remove_logo(session, admin.actor, club_id, store), "Logo bolo odstránené.")


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
            if key not in form:
                continue
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


@router.post("/settings/test-mail", dependencies=[Depends(verify_csrf)])
def test_mail(request: Request, admin: Admin, session: Db, mailer: Mailer_, to: Annotated[str, Form()] = ""):
    """Send a test e-mail to check the SMTP configuration (system administrators only)."""
    if not admin.is_system_admin:
        return forbidden(request, admin, session)
    to = to.strip()
    if mailer is None:
        text, kind = "Odosielanie e-mailov nie je nastavené (ESS_SMTP_PASSWORD).", "error"
    elif "@" not in to or len(to) > 254 or any(c in to for c in "\r\n<>,;"):
        text, kind = "Zadajte platnú e-mailovú adresu.", "error"
    else:
        try:
            mailer.send(Mail(to=to, subject="eSS – testovací e-mail",
                             text="Toto je testovací e-mail z informačného systému SSS (eSS). Odosielanie funguje."))
            audit.record(session, actor_type=admin.actor.audit_type, actor_id=admin.actor.id, action="mail.test")
            session.commit()
            text, kind = "Testovací e-mail bol odoslaný.", "ok"
        except MailError as exc:
            text, kind = f"E-mail sa nepodarilo odoslať ({exc}).", "error"
    request.session["flash"] = {"kind": kind, "text": text}
    return RedirectResponse("/admin/settings", status_code=303)


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


# --- CSV import -------------------------------------------------------------------------------------------

MAX_IMPORT_BYTES = 2 * 1024 * 1024


@router.get("/import")
def import_page(request: Request, admin: Admin, session: Db):
    return render(request, "admin/import.html", admin, session, result=None, kind=None)


@router.post("/import/{kind}", dependencies=[Depends(verify_csrf)])
async def import_upload(request: Request, kind: str, admin: Admin, session: Db):
    if kind not in ("clubs", "members"):
        return render(request, "admin/not_found.html", admin, session)
    form = await request.form()
    upload = form.get("file")
    dry_run = form.get("execute") != "on"
    content = await upload.read(MAX_IMPORT_BYTES + 1) if upload is not None and hasattr(upload, "read") else b""
    if not content:
        result = importing.ImportResult(False, errors=["Vyberte súbor CSV."])
    elif len(content) > MAX_IMPORT_BYTES:
        result = importing.ImportResult(False, errors=["Súbor je príliš veľký (najviac 2 MB)."])
    else:
        fn = importing.import_clubs if kind == "clubs" else importing.import_members
        try:
            result = fn(session, admin.actor, content, dry_run=dry_run)
            if result.ok and not dry_run:
                session.commit()
            else:
                session.rollback()
        except (DomainError, PermissionDenied) as exc:
            session.rollback()
            result = importing.ImportResult(False, errors=[error_text(exc)])
    return render(request, "admin/import.html", admin, session, result=result, kind=kind, dry_run=dry_run,
                  status_code=200 if result.ok else 400)


@router.get("/import/template/{kind}.csv")
def import_template(kind: str, admin: Admin):
    if kind not in ("clubs", "members"):
        kind = "members"
    name = "vzor_skupiny.csv" if kind == "clubs" else "vzor_clenovia.csv"
    return Response(importing.template_csv(kind), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/import/club-codes.csv")
def club_codes(admin: Admin, session: Db):
    """Current clubs with their codes - for the person preparing the member list."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(["kod", "nazov"])
    for club in directory.active_clubs(session):
        writer.writerow([club.code or "", club.name])
    return Response("﻿" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="kody_skupin.csv"'})
