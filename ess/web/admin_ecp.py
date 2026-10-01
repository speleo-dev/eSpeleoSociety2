"""Administration: review of eCP applications (approve / reject / re-crop the photo)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse

from ess.mail import Mailer, get_mailer
from ess.services import ecp_issuance
from ess.services.access import DomainError, PermissionDenied
from ess.storage import MediaStore, get_media_store
from ess.wallet import WalletClient, get_wallet, static_url
from ess.web.auth import verify_csrf
from ess.web.common import Admin, Db, error_text, render
from ess.web.mailing import render_mail, send
from ess.web.public import _crop, base_url
from ess.web.paths import A

router = APIRouter()  # mounted under the admin path (R48)

Store = Annotated[MediaStore | None, Depends(get_media_store)]
MailerDep = Annotated[Mailer | None, Depends(get_mailer)]
Wallet = Annotated[WalletClient, Depends(get_wallet)]


def _page_url(application_id: uuid.UUID) -> str:
    return f"{A}/ecp-applications/{application_id}"


@router.get("/ecp-applications/{application_id}")
def application_page(request: Request, application_id: uuid.UUID, admin: Admin, session: Db, store: Store):
    try:
        v = ecp_issuance.view(session, admin.actor, application_id)
    except DomainError:
        return render(request, "admin/not_found.html", admin, session)
    a = v.application
    return render(request, "admin/ecp_application.html", admin, session, v=v,
                  portrait_url=store.url(a.photo_cropped) if store and a.photo_cropped else None,
                  original_url=store.url(a.photo_original) if store and a.photo_original else None)


def _decide(request: Request, session, store, application_id, action, after, success: str):
    """Run a decision: commit, then delete replaced photos and send the e-mail."""
    try:
        decision = action()
        session.commit()
    except (DomainError, PermissionDenied) as exc:
        session.rollback()
        request.session["flash"] = {"kind": "error", "text": error_text(exc)}
        return RedirectResponse(_page_url(application_id), status_code=303)
    for name in decision.cleanup:
        if store:
            store.delete(name)
    text, kind = success, "ok"
    if after is not None and not after(decision):
        text, kind = success + " E-mail žiadateľovi sa však nepodarilo odoslať.", "error"
    request.session["flash"] = {"kind": kind, "text": text}
    return RedirectResponse(_page_url(application_id), status_code=303)


@router.post("/ecp-applications/{application_id}/approve", dependencies=[Depends(verify_csrf)])
def approve(request: Request, application_id: uuid.UUID, admin: Admin, session: Db, store: Store,
            wallet: Wallet, mailer: MailerDep):
    def mail(d: ecp_issuance.Decision) -> bool:
        return send(mailer, render_mail(d.email, "Váš elektronický jaskyniarsky preukaz je pripravený",
                                        "ecp_issued", member_name=d.member_name, save_url=d.save_url,
                                        badge_url=static_url("sk_add_to_google_wallet_add-wallet-badge.png")))

    return _decide(request, session, store, application_id,
                   lambda: ecp_issuance.approve(session, admin.actor, application_id, store, wallet,
                                                base_url(request)),
                   mail, "eCP bol vydaný.")


@router.post("/ecp-applications/{application_id}/reject", dependencies=[Depends(verify_csrf)])
def reject(request: Request, application_id: uuid.UUID, admin: Admin, session: Db, store: Store,
           mailer: MailerDep, reason: Annotated[str, Form()] = ""):
    def mail(d: ecp_issuance.Decision) -> bool:
        return send(mailer, render_mail(d.email, "Žiadosť o eCP", "ecp_rejected", first_name=d.first_name,
                                        reason=d.application.reject_reason,
                                        apply_url=f"{base_url(request)}/ecp/apply"))

    return _decide(request, session, store, application_id,
                   lambda: ecp_issuance.reject(session, admin.actor, application_id, reason),
                   mail, "Žiadosť bola zamietnutá.")


@router.post("/ecp-applications/{application_id}/recrop", dependencies=[Depends(verify_csrf)])
async def recrop(request: Request, application_id: uuid.UUID, admin: Admin, session: Db, store: Store):
    crop = _crop(await request.form())
    return await run_in_threadpool(
        _decide, request, session, store, application_id,
        lambda: ecp_issuance.recrop(session, admin.actor, application_id, crop, store), None,
        "Fotka bola orezaná znova.")
