"""Administration: membership fees, payment links (member and bulk) and manual payment (phase 3)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from ess.models import Club, Member, PaymentReference
from ess.services import payments
from ess.services.access import DomainError, PermissionDenied
from ess.web.auth import verify_csrf
from ess.web.common import Admin, Db, act, error_text, render

router = APIRouter(prefix="/admin")


def _create_and_show(request: Request, session: Db, back: str, create) -> RedirectResponse:
    """Create (or reuse) a reference, commit and show it; on error go back with a message."""
    try:
        reference = create()
        session.commit()
    except (DomainError, PermissionDenied) as exc:
        session.rollback()
        request.session["flash"] = {"kind": "error", "text": error_text(exc)}
        return RedirectResponse(back, status_code=303)
    return RedirectResponse(f"/admin/payments/{reference.id}", status_code=303)


@router.get("/payments")
def payments_page(request: Request, admin: Admin, session: Db):
    from ess.services import ecp_content

    return render(request, "admin/payments.html", admin, session, due_year=max(payments.payment_years(session)),
                  pending=ecp_content.pending_count(session))


@router.post("/payments/publish-links", dependencies=[Depends(verify_csrf)])
def publish_links(request: Request, admin: Admin, session: Db):
    from ess.services import ecp_content

    return act(request, session, "/admin/payments", lambda: ecp_content.publish_payment_links(session, admin.actor),
                "Platobné odkazy sa odosielajú do eCP.")


@router.post("/payments/push", dependencies=[Depends(verify_csrf)])
def push_links(request: Request, admin: Admin, session: Db):
    """Send the next batch (after_commit sends it; nothing else changes)."""
    return act(request, session, "/admin/payments", lambda: None, "Ďalšia dávka eCP bola odoslaná.")


@router.post("/members/{member_id}/payment-link", dependencies=[Depends(verify_csrf)])
def member_payment_link(request: Request, member_id: uuid.UUID, admin: Admin, session: Db,
                        year: Annotated[int, Form()]):
    return _create_and_show(request, session, f"/admin/members/{member_id}",
                            lambda: payments.member_reference(session, admin.actor, member_id, year))


@router.post("/members/{member_id}/fee-paid", dependencies=[Depends(verify_csrf)])
def fee_paid(request: Request, member_id: uuid.UUID, admin: Admin, session: Db,
             year: Annotated[int, Form()], note: Annotated[str, Form()] = ""):
    return act(request, session, f"/admin/members/{member_id}",
               lambda: payments.mark_paid(session, admin.actor, member_id, year, note),
               f"Členské na rok {year} bolo označené ako zaplatené.")


@router.get("/payments/{reference_id}")
def payment_page(request: Request, reference_id: uuid.UUID, admin: Admin, session: Db):
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
def payment_cancel(request: Request, reference_id: uuid.UUID, admin: Admin, session: Db):
    return act(request, session, f"/admin/payments/{reference_id}",
               lambda: payments.cancel_reference(session, admin.actor, reference_id), "Platobný odkaz bol zrušený.")


@router.get("/clubs/{club_id}/bulk-payment")
def bulk_payment_form(request: Request, club_id: uuid.UUID, admin: Admin, session: Db, year: int | None = None):
    club = session.get(Club, club_id)
    if club is None:
        return render(request, "admin/not_found.html", admin, session)
    years = payments.payment_years(session)
    year = year if year in years else years[-1]
    return render(request, "admin/bulk_payment.html", admin, session, club=club, year=year, years=years,
                  candidates=payments.bulk_candidates(session, admin.actor, club_id, year),
                  open_refs=payments.open_bulk_references(session, club_id))


@router.post("/clubs/{club_id}/bulk-payment", dependencies=[Depends(verify_csrf)])
async def bulk_payment_create(request: Request, club_id: uuid.UUID, admin: Admin, session: Db):
    form = await request.form()
    back = f"/admin/clubs/{club_id}/bulk-payment"
    try:
        year = int(form.get("year", ""))
        chosen = [uuid.UUID(v) for v in form.getlist("member_id")]
    except ValueError:
        request.session["flash"] = {"kind": "error", "text": error_text(DomainError("invalid_value"))}
        return RedirectResponse(back, status_code=303)
    return _create_and_show(request, session, f"{back}?year={year}",
                            lambda: payments.create_bulk(session, admin.actor, club_id, year, chosen))


def member_fee_rows(session, member: Member) -> dict:
    """Fees for the member page: paid years and the years that can still be paid."""
    fees = payments.member_fees(session, member.id)
    paid = {f.year for f in fees if f.paid_at}
    payable = [] if member.expelled_at or member.sss_ended_at else [
        y for y in payments.payment_years(session) if y not in paid]
    return {"fees": fees, "payable_years": payable}

