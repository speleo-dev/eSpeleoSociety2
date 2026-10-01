"""Administration: membership fees, payment links (member and bulk) and manual payment (phase 3)."""

import base64
import csv
import io
import secrets
import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from ess.images import MAX_UPLOAD_BYTES
from ess.models import Club, Member, PaymentReference
from ess.services import payments, sticker
from ess.services.access import DomainError, PermissionDenied
from ess.storage import MediaStore, get_media_store
from ess.web.auth import verify_csrf
from ess.web.common import Admin, RegisterAdmin, Db, act, after_commit, error_text, render
from ess.web.templates import FEE_METHOD_LABELS
from ess.web.paths import A

router = APIRouter()  # mounted under the admin path (R48)
MAX_STATEMENT = 10 * 1024 * 1024  # bytes
Store = Annotated[MediaStore | None, Depends(get_media_store)]


def _create_and_show(request: Request, session: Db, back: str, create) -> RedirectResponse:
    """Create (or reuse) a reference, commit and show it; on error go back with a message."""
    try:
        reference = create()
        session.commit()
    except (DomainError, PermissionDenied) as exc:
        session.rollback()
        request.session["flash"] = {"kind": "error", "text": error_text(exc)}
        return RedirectResponse(back, status_code=303)
    return RedirectResponse(f"{A}/payments/{reference.id}", status_code=303)


@router.get("/payments")
def payments_page(request: Request, admin: RegisterAdmin, session: Db, year: int | None = None, club: str = ""):
    from ess.services import ecp_content

    years = _overview_years(session)
    year = year if year in years else years[0]
    club_id = _club_id(club)
    rows = payments.overview(session, admin.actor, year)
    due_year = max(payments.payment_years(session))
    return render(request, "admin/payments.html", admin, session, due_year=due_year,
                  sticker_published=sticker.is_published(session, due_year),
                  pending=ecp_content.pending_count(session), year=year, years=years, club=club,
                  summary=payments.summarize(rows),
                  rows=[r for r in rows if club_id and r.club_id == club_id] if club else [],
                  paid_total=sum((r.amount for r in rows if r.paid_at), Decimal("0")),
                  paid_count=sum(1 for r in rows if r.paid_at), total_count=len(rows))


def _overview_years(session) -> list[int]:
    """Newest first: the payment period years and the previous few years."""
    newest = max(payments.payment_years(session))
    return list(range(newest, newest - 5, -1))


def _club_id(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


@router.get("/payments/export.csv")
def payments_export(request: Request, admin: RegisterAdmin, session: Db, year: int, club: str = ""):
    """Fee overview of a year for a spreadsheet (personal data: administrators only, not logged)."""
    club_id = _club_id(club)
    rows = [r for r in payments.overview(session, admin.actor, year) if not club_id or r.club_id == club_id]
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Skupina", "Priezvisko", "Meno", "Číslo preukazu", "Suma", "Zľavnené", "Zaplatené", "Spôsob"])
    for r in rows:
        writer.writerow([r.club_name, r.last_name, r.first_name, r.card_number or "", f"{r.amount:.2f}".replace(".", ","),
                         "áno" if r.reduced else "", r.paid_at.strftime("%d.%m.%Y") if r.paid_at else "",
                         FEE_METHOD_LABELS.get(r.method, "")])
    return Response("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="clenske_{year}.csv"',
                             "Cache-Control": "no-store"})


@router.get("/statements")
def statements_page(request: Request, admin: RegisterAdmin, session: Db):
    from ess.banking import FORMATS
    from ess.models import BankStatement

    recent = session.scalars(select(BankStatement).order_by(BankStatement.uploaded_at.desc()).limit(20)).all()
    return render(request, "admin/statements.html", admin, session, formats=FORMATS, recent=recent,
                  result=request.session.pop("statement_result", None))


@router.post("/statements", dependencies=[Depends(verify_csrf)])
async def statement_upload(request: Request, admin: RegisterAdmin, session: Db):
    from ess.banking import StatementError
    from ess.services import bank_statements

    form = await request.form()
    upload = form.get("file")
    data = await upload.read(MAX_STATEMENT + 1) if hasattr(upload, "read") else b""
    try:
        if not data:
            raise DomainError("invalid_statement")
        if len(data) > MAX_STATEMENT:
            raise DomainError("statement_too_large")
        result = bank_statements.import_statement(session, admin.actor, str(form.get("format", "")), data)
        session.commit()
    except (DomainError, PermissionDenied, StatementError) as exc:
        session.rollback()
        from ess.services import outbox

        outbox.discard(session)
        request.session["flash"] = {"kind": "error", "text": error_text(exc)}
        return RedirectResponse(f"{A}/statements", status_code=303)
    request.session["statement_result"] = {"counts": result.counts, "duplicates": result.duplicates}
    request.session["flash"] = {"kind": "ok", "text": "Výpis bol spracovaný."}
    if not after_commit(request, session):
        request.session["flash"] = {"kind": "error", "text": "Výpis bol spracovaný, niektorý e-mail sa však nepodarilo odoslať."}
    return RedirectResponse(f"{A}/statements", status_code=303)


@router.post("/tasks/{task_id}/assign-payment", dependencies=[Depends(verify_csrf)])
def task_assign_payment(request: Request, task_id: uuid.UUID, admin: RegisterAdmin, session: Db,
                        code: Annotated[str, Form()] = ""):
    from ess.services import bank_statements

    return act(request, session, f"{A}/tasks", lambda: bank_statements.assign(session, admin.actor, task_id, code),
               "Platba bola priradená.")


@router.post("/tasks/{task_id}/resolve-payment", dependencies=[Depends(verify_csrf)])
def task_resolve_payment(request: Request, task_id: uuid.UUID, admin: RegisterAdmin, session: Db,
                         note: Annotated[str, Form()] = ""):
    from ess.services import bank_statements

    return act(request, session, f"{A}/tasks", lambda: bank_statements.resolve(session, admin.actor, task_id, note),
               "Požiadavka bola vybavená.")


@router.post("/payments/push", dependencies=[Depends(verify_csrf)])
def push_links(request: Request, admin: RegisterAdmin, session: Db):
    """Send the next batch (after_commit sends it; nothing else changes)."""
    return act(request, session, f"{A}/payments", lambda: None, "Ďalšia dávka eCP bola odoslaná.")


@router.post("/members/{member_id}/payment-link", dependencies=[Depends(verify_csrf)])
def member_payment_link(request: Request, member_id: uuid.UUID, admin: RegisterAdmin, session: Db,
                        year: Annotated[int, Form()]):
    return _create_and_show(request, session, f"{A}/members/{member_id}",
                            lambda: payments.member_reference(session, admin.actor, member_id, year))


@router.post("/members/{member_id}/fee-paid", dependencies=[Depends(verify_csrf)])
def fee_paid(request: Request, member_id: uuid.UUID, admin: RegisterAdmin, session: Db,
             year: Annotated[int, Form()], note: Annotated[str, Form()] = ""):
    return act(request, session, f"{A}/members/{member_id}",
               lambda: payments.mark_paid(session, admin.actor, member_id, year, note),
               f"Členské na rok {year} bolo označené ako zaplatené.")


@router.get("/payments/{reference_id}")
def payment_page(request: Request, reference_id: uuid.UUID, admin: RegisterAdmin, session: Db):
    reference = session.get(PaymentReference, reference_id)
    if reference is None:
        return render(request, "admin/not_found.html", admin, session)
    link, link_error = None, None
    if reference.status in payments.UNFINISHED:
        try:
            link = payments.payme_url(session, reference)
        except DomainError as exc:
            link_error = error_text(exc)
    club = session.get(Club, reference.club_id) if reference.club_id else None
    return render(request, "admin/payment.html", admin, session, ref=reference, club=club, link=link,
                  link_error=link_error, lines=payments.reference_lines(session, reference),
                  remaining=payments.remaining(reference))


@router.post("/payments/{reference_id}/cancel", dependencies=[Depends(verify_csrf)])
def payment_cancel(request: Request, reference_id: uuid.UUID, admin: RegisterAdmin, session: Db):
    return act(request, session, f"{A}/payments/{reference_id}",
               lambda: payments.cancel_reference(session, admin.actor, reference_id), "Platobný odkaz bol zrušený.")


# --- yearly sticker (R45) ------------------------------------------------------------------------------


def _sticker_page(request: Request, admin, session, status_code: int = 200, **extra):
    return render(request, "admin/sticker.html", admin, session, status_code=status_code,
                  sticker=sticker.current(session), edit_year=sticker.edit_year(session),
                  due_year=sticker.due_year(session), **extra)


@router.get("/sticker")
def sticker_page(request: Request, admin: RegisterAdmin, session: Db):
    return _sticker_page(request, admin, session)


@router.post("/sticker", dependencies=[Depends(verify_csrf)])
async def sticker_action(request: Request, admin: RegisterAdmin, session: Db, store: Store):
    """Preview (new random colours) or publish the sticker shown in the preview."""
    form = await request.form()
    action = str(form.get("action", "preview"))
    background = "transparent" if form.get("transparent") == "on" else str(form.get("bg_color", "#0B4A46"))
    try:
        year = int(str(form.get("year", "0")))
        seed = int(str(form.get("seed") or 0)) if action == "publish" else secrets.randbelow(2**31)
        args = (session, admin.actor, store, year, str(form.get("text_color", "#FFFFFF")), background, seed)
        if action == "publish":
            sticker.publish(*args)
            session.commit()
            request.session["flash"] = {"kind": "ok", "text": f"Ročná známka na rok {year} je zverejnená. "
                                        "Platba členského cez eCP je otvorená."}
            after_commit(request, session)
            return RedirectResponse(f"{A}/sticker", status_code=303)
        png = sticker.render(*args)
        session.commit()
    except (DomainError, PermissionDenied, ValueError) as exc:
        session.rollback()
        return _sticker_page(request, admin, session, status_code=400, error=error_text(exc))
    preview = "data:image/png;base64," + base64.b64encode(png).decode()
    return _sticker_page(request, admin, session, preview=preview, preview_seed=seed)


@router.post("/sticker/template", dependencies=[Depends(verify_csrf)])
def sticker_template(request: Request, admin: RegisterAdmin, session: Db, store: Store,
                     template: Annotated[UploadFile, File()]):
    data = template.file.read(MAX_UPLOAD_BYTES + 1)
    return act(request, session, f"{A}/sticker", lambda: sticker.upload_template(session, admin.actor, store, data),
               "Šablóna známky bola nahraná.")


def member_fee_rows(session, member: Member) -> dict:
    """Fees for the member page: paid years and the years that can still be paid."""
    fees = payments.member_fees(session, member.id)
    paid = {f.year for f in fees if f.paid_at}
    payable = [] if member.expelled_at or member.sss_ended_at else [
        y for y in payments.payment_years(session) if y not in paid]
    return {"fees": fees, "payable_years": payable}

