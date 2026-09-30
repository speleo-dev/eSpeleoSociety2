"""What the eCP shows besides its state: paid year ("Platný do"), the yearly sticker and the payment link
(R34, R36).

The payment link is shown for the latest year of the payment period (R27) until its fee is paid, and only
after the sticker of that year is published (R45). Publishing the sticker publishes the links
(`publish_payment_links`) – every pass is marked stale and sent in batches. After a fee is paid the pass is marked `content_stale`; the web layer sends the new content to Google
Wallet after the commit (`push_pending`), like state changes in `ecp_state`. A failed push is retried
on the next call. The QR code is not touched here (it holds a one-time token, see ecp_verification).
"""

import logging
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ess import audit
from ess.config import get_settings
from ess.models import EcpPass, EcpPassState, Fee, Member
from ess.services import members, payments, sticker
from ess.services.access import SYSTEM, Actor, DomainError, require_admin
from ess.wallet import PassContent, WalletClient, WalletError, build_pass_object

log = logging.getLogger(__name__)


def paid_years(session: Session, member_id: uuid.UUID) -> list[int]:
    return sorted(session.scalars(select(Fee.year).where(Fee.member_id == member_id, Fee.paid_at.is_not(None))),
                  reverse=True)


def valid_until(session: Session, member_id: uuid.UUID) -> date | None:
    """End of the last paid year."""
    years = paid_years(session, member_id)
    return date(years[0], 12, 31) if years else None


def hero_url(session: Session, member_id: uuid.UUID) -> str | None:
    """Sticker of the last paid year that has one; without a paid year the sticker of this year."""
    for year in paid_years(session, member_id):
        url = sticker.hero_url(session, year)
        if url:
            return url
    return sticker.hero_url(session)


def payment_link(session: Session, member_id: uuid.UUID) -> tuple[str, str] | None:
    """(PAYMe URL, label) for the member's own reference of the due year; None when paid or not possible."""
    year = max(payments.payment_years(session))
    if not sticker.is_published(session, year):  # paying through the eCP opens with the new sticker (R45)
        return None
    fee = payments.get_fee(session, member_id, year)
    if fee is not None and fee.paid_at is not None:
        return None
    try:
        reference = payments.member_reference(session, SYSTEM, member_id, year)
        return payments.payme_url(session, reference), f"Zaplatiť členské SSS na rok {year}"
    except DomainError:  # e.g. IBAN not configured, member left SSS
        return None


def current_pass(session: Session, member_id: uuid.UUID) -> EcpPass | None:
    return session.scalar(select(EcpPass).where(EcpPass.member_id == member_id,
                                                EcpPass.state != EcpPassState.REVOKED.value))


def mark_stale(session: Session, member_id: uuid.UUID) -> None:
    ecp_pass = current_pass(session, member_id)
    if ecp_pass is not None:
        ecp_pass.content_stale = True


def _pending_query():
    return select(EcpPass).where(EcpPass.content_stale.is_(True), EcpPass.state != EcpPassState.REVOKED.value)


def has_pending(session: Session) -> bool:
    return session.scalar(_pending_query().with_only_columns(EcpPass.id).limit(1)) is not None


def pending_count(session: Session) -> int:
    return session.scalar(_pending_query().with_only_columns(func.count()))


def publish_payment_links(session: Session, actor: Actor) -> int:
    """The payment period opened: every eCP gets its payment link (sent in batches after commits)."""
    require_admin(actor)
    if not sticker.is_published(session, max(payments.payment_years(session))):
        raise DomainError("sticker_not_published")
    passes = session.scalars(select(EcpPass).where(EcpPass.state != EcpPassState.REVOKED.value)).all()
    for ecp_pass in passes:
        ecp_pass.content_stale = True
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="ecp.publish_payment_links",
                 entity_type="ecp_pass", entity_id="*",
                 details={"year": max(payments.payment_years(session)), "passes": len(passes)})
    return len(passes)


def portal_url(ecp_pass: EcpPass, base_url: str | None) -> str | None:
    base = base_url or get_settings().public_base_url
    return f"{base.rstrip('/')}/p/{ecp_pass.portal_key}" if base and ecp_pass.portal_key else None


def content_patch(session: Session, ecp_pass: EcpPass, base_url: str | None = None) -> dict:
    """Fields of the Wallet object that follow the register and payments (not the QR code)."""
    from ess.services.ecp_issuance import _primary_club_name

    member = session.get(Member, ecp_pass.member_id)
    data = members.read_member(member)
    content = PassContent(
        object_id=ecp_pass.wallet_object_id, member_name=data.full_name(),
        club_name=_primary_club_name(session, member.id), card_number=data.card_number,
        member_since=data.member_since, birth_date=data.birth_date,
        photo_url="", check_url="",  # not patched
        valid_until=valid_until(session, member.id), hero_url=hero_url(session, member.id),
        payment=payment_link(session, member.id), portal_url=portal_url(ecp_pass, base_url))
    obj = build_pass_object(content)
    return {k: obj[k] for k in ("header", "textModulesData", "heroImage", "linksModuleData") if k in obj}


BATCH = 50  # passes per request (Cloud Run request time); the rest follows on the next requests


def push_pending(session: Session, wallet: WalletClient, limit: int = BATCH, base_url: str | None = None) -> int:
    """Send changed content to Google Wallet. Commits each pass separately; returns the number pushed."""
    done = 0
    for ecp_pass in session.scalars(_pending_query().order_by(EcpPass.id).limit(limit)).all():
        try:
            wallet.patch_object(ecp_pass.wallet_object_id, content_patch(session, ecp_pass, base_url))
        except WalletError:
            log.warning("eCP content not pushed to Google Wallet; will retry")
            continue
        ecp_pass.content_stale = False
        session.commit()
        done += 1
    return done
