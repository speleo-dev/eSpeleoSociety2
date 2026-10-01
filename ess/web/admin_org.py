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
from ess.services import admin_access, certificates, clubs, delegations, directory, documents, importing, settings
from ess.services.access import DomainError, PermissionDenied
from ess.storage import MediaStore, get_media_store
from ess.web.auth import verify_csrf
from ess.web.common import Admin, RegisterAdmin, Db, act, error_text, forbidden, parse_date, render
from ess.web.paths import A

Store = Annotated[MediaStore | None, Depends(get_media_store)]
Mailer_ = Annotated[Mailer | None, Depends(get_mailer)]

router = APIRouter()  # mounted under the admin path (R48)

SETTING_KEYS = ("fee_amount", "reduced_fee_amount", "reduced_fee_age", "fee_currency", "renewal_window_days",
                "payment_iban", "payment_account_name",
                "ecp_link_valid_hours", "ecp_application_expiry_days", "ecp_qr_grace_minutes", "ecp_qr_daily_limit",
                "portal_max_devices")


# --- clubs --------------------------------------------------------------------------------------------

@router.get("/clubs/new")
def club_new(request: Request, admin: RegisterAdmin, session: Db):
    return render(request, "admin/club_form.html", admin, session, club=None, raw={"uses_candidates": True})


def _club_form(form) -> tuple[dict, clubs.ClubContact]:
    """Raw values of the club form (to re-fill it on error) and the parsed contact details."""
    raw = {k: str(form.get(k, "")).strip() for k in ("name", "short_name", "code", "logo_url", *clubs.CONTACT_FIELDS)}
    raw["uses_candidates"] = form.get("uses_candidates") == "on"
    raw["active"] = form.get("active") == "on"
    contact = clubs.ClubContact(**{f: raw[f] or None for f in clubs.CONTACT_FIELDS if f not in ("country", "founded_on")},
                                country=raw["country"] or "SK", founded_on=parse_date(raw["founded_on"]))
    return raw, contact


@router.post("/clubs/new", dependencies=[Depends(verify_csrf)])
async def club_create(request: Request, admin: RegisterAdmin, session: Db):
    raw = {}
    try:
        raw, contact = _club_form(await request.form())
        club = clubs.create_club(session, admin.actor, raw["name"], raw["short_name"], raw["uses_candidates"],
                                 raw["code"], raw["logo_url"], contact)
        session.commit()
    except (DomainError, PermissionDenied) as exc:
        session.rollback()
        return render(request, "admin/club_form.html", admin, session, status_code=400, club=None, raw=raw,
                      error=error_text(exc))
    request.session["flash"] = {"kind": "ok", "text": "Skupina bola vytvorená."}
    return RedirectResponse(f"{A}/clubs/{club.id}", status_code=303)


@router.get("/clubs/{club_id}")
def club_page(request: Request, club_id: uuid.UUID, admin: Admin, session: Db):
    club = session.get(Club, club_id)
    if club is None:
        return render(request, "admin/not_found.html", admin, session)
    chairs = [h for h in directory.current_positions(session) if h.club_id == club_id]
    active_members = directory.list_members(session, club_id=club_id, status=MembershipStatus.MEMBER)
    raw = {"name": club.name, "short_name": club.short_name or "", "uses_candidates": club.uses_candidates,
           "active": club.active, "code": club.code or "", "logo_url": club.logo_url or ""}
    raw.update({f: getattr(club, f) or "" for f in clubs.CONTACT_FIELDS})
    raw["founded_on"] = club.founded_on.isoformat() if club.founded_on else ""
    delegation = delegations.current(session, club_id)
    eligible = set(delegations.eligible_ids(session, club_id))
    names = {r.id: f"{r.data.last_name} {r.data.first_name}" for r in active_members}
    return render(request, "admin/club_form.html", admin, session, club=club, raw=raw, chairs=chairs,
                  active_members=active_members, delegation=delegation,
                  delegate_name=names.get(delegation.delegate_member_id, "") if delegation else "",
                  delegate_options=[r for r in active_members if r.id in eligible])


@router.post("/clubs/{club_id}/delegation", dependencies=[Depends(verify_csrf)])
def club_delegate(request: Request, club_id: uuid.UUID, admin: RegisterAdmin, session: Db,
                  member_id: Annotated[uuid.UUID, Form()]):
    return act(request, session, f"{A}/clubs/{club_id}",
               lambda: delegations.delegate(session, admin.actor, club_id, member_id), "Zástupca predsedu bol určený.")


@router.post("/clubs/{club_id}/delegation/end", dependencies=[Depends(verify_csrf)])
def club_delegation_end(request: Request, club_id: uuid.UUID, admin: RegisterAdmin, session: Db):
    return act(request, session, f"{A}/clubs/{club_id}", lambda: delegations.take_back(session, admin.actor, club_id),
               "Zastupovanie bolo ukončené, skupinu spravuje predseda.")


@router.post("/clubs/{club_id}", dependencies=[Depends(verify_csrf)])
async def club_update(request: Request, club_id: uuid.UUID, admin: RegisterAdmin, session: Db):
    form = await request.form()

    def update():
        raw, contact = _club_form(form)
        clubs.update_club(session, admin.actor, club_id, raw["name"], raw["short_name"], raw["uses_candidates"],
                          raw["active"], raw["code"], raw["logo_url"], contact)

    return act(request, session, f"{A}/clubs/{club_id}", update, "Skupina bola uložená.")


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
        return RedirectResponse(f"{A}/clubs/{club_id}", status_code=303)
    except Exception:
        session.rollback()
        if change and change.new_object and store:
            store.delete(change.new_object)
        raise
    if change.old_object and store:
        store.delete(change.old_object)
    return RedirectResponse(f"{A}/clubs/{club_id}", status_code=303)


@router.post("/clubs/{club_id}/logo", dependencies=[Depends(verify_csrf)])
def club_logo_upload(request: Request, club_id: uuid.UUID, admin: RegisterAdmin, session: Db, store: Store,
                           logo: Annotated[UploadFile, File()]):
    data = logo.file.read(MAX_UPLOAD_BYTES + 1)  # sync handler runs in a thread pool
    return _logo_action(request, session, store, club_id,
                        lambda: clubs.set_logo(session, admin.actor, club_id, data, store), "Logo bolo nahraté.")


@router.post("/clubs/{club_id}/logo/remove", dependencies=[Depends(verify_csrf)])
def club_logo_remove(request: Request, club_id: uuid.UUID, admin: RegisterAdmin, session: Db, store: Store):
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
                  super_admins=sorted(admin_access.super_admin_emails()))


@router.post("/access", dependencies=[Depends(verify_csrf)])
def access_grant(
    request: Request, admin: Admin, session: Db, email: Annotated[str, Form()] = "",
    name: Annotated[str, Form()] = "", role: Annotated[str, Form()] = "admin",
):
    return act(request, session, f"{A}/access",
               lambda: admin_access.grant_access(session, admin.actor, email, name, AdminRole(role)),
               "Prístup bol udelený.")


@router.post("/access/{user_id}/revoke", dependencies=[Depends(verify_csrf)])
def access_revoke(request: Request, user_id: uuid.UUID, admin: Admin, session: Db):
    return act(request, session, f"{A}/access", lambda: admin_access.revoke_access(session, admin.actor, user_id),
               "Prístup bol odobratý.")


# --- settings (system administrators only) ------------------------------------------------------------

@router.get("/settings")
def settings_page(request: Request, admin: Admin, session: Db):
    """R50: administrators change fees and eCP settings, superadmins eCP settings; both certificate types."""
    return _settings_page(request, admin, session)


def _settings_page(request: Request, admin, session, status_code: int = 200, **extra):
    values = {k: settings.get_setting(session, k) or "" for k in SETTING_KEYS}
    return render(request, "admin/settings.html", admin, session, status_code=status_code, values=values,
                  cert_types=certificates.active_types(session), **extra)


@router.post("/settings", dependencies=[Depends(verify_csrf)])
async def settings_save(request: Request, admin: Admin, session: Db):
    form = await request.form()

    def save():
        for key in SETTING_KEYS:
            if key not in form or (key in settings.ADMIN_KEYS and not admin.is_admin):
                continue  # R50: the superadmin does not change fees (the service checks it too)
            new = str(form.get(key, "")).strip()
            if new != (settings.get_setting(session, key) or ""):
                settings.set_setting(session, admin.actor, key, new)

    return act(request, session, f"{A}/settings", save, "Nastavenia boli uložené.")


@router.post("/settings/certificate-types", dependencies=[Depends(verify_csrf)])
def certificate_type_add(
    request: Request, admin: Admin, session: Db, code: Annotated[str, Form()] = "", name: Annotated[str, Form()] = ""
):
    return act(request, session, f"{A}/settings",
               lambda: certificates.add_certificate_type(session, admin.actor, code, name),
               "Typ certifikátu bol pridaný.")


@router.post("/settings/certificate-types/{type_id}/remove", dependencies=[Depends(verify_csrf)])
def certificate_type_remove(request: Request, type_id: uuid.UUID, admin: Admin, session: Db):
    return act(request, session, f"{A}/settings",
               lambda: certificates.deactivate_certificate_type(session, admin.actor, type_id),
               "Typ certifikátu bol odobratý.")


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
    return RedirectResponse(f"{A}/settings", status_code=303)


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
    return act(request, session, f"{A}/documents",
               lambda: documents.save_document(session, admin.actor, title, url, parse_date(valid_until), sort_order,
                                               uuid.UUID(document_id) if document_id else None),
               "Dokument bol uložený.")


@router.get("/notifications")
def notifications_page(request: Request, admin: Admin, session: Db):
    from ess.services import ecp_notifications as n

    return render(request, "admin/notifications.html", admin, session, rows=n.history(session),
                  recipients=len(n.recipients(session)), pending=n.pending_count(session),
                  left_today=max(0, n.DAILY_LIMIT - n.sent_last_day(session)))


@router.post("/notifications", dependencies=[Depends(verify_csrf)])
def notification_send(request: Request, admin: Admin, session: Db, header: Annotated[str, Form()] = "",
                      body: Annotated[str, Form()] = ""):
    from ess.services import ecp_notifications

    return act(request, session, f"{A}/notifications",
               lambda: ecp_notifications.send(session, admin.actor, header, body),
               "Notifikácia sa odosiela do eCP.")


@router.post("/notifications/push", dependencies=[Depends(verify_csrf)])
def notification_push(request: Request, admin: Admin, session: Db):
    return act(request, session, f"{A}/notifications", lambda: None, "Ďalšia dávka bola odoslaná.")


@router.post("/documents/{document_id}/delete", dependencies=[Depends(verify_csrf)])
def document_delete(request: Request, document_id: uuid.UUID, admin: Admin, session: Db):
    return act(request, session, f"{A}/documents", lambda: documents.delete_document(session, admin.actor, document_id),
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
def import_template(request: Request, kind: str, admin: Admin, session: Db):
    if kind not in ("clubs", "members"):
        kind = "members"
    name = "vzor_skupiny.csv" if kind == "clubs" else "vzor_clenovia.csv"
    return Response(importing.template_csv(kind), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/import/club-codes.csv")
def club_codes(request: Request, admin: Admin, session: Db):
    """Current clubs with their codes - for the person preparing the member list."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(["kod", "nazov"])
    for club in directory.active_clubs(session):
        writer.writerow([club.code or "", club.name])
    return Response("﻿" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="kody_skupin.csv"'})
