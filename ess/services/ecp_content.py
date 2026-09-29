"""What the eCP shows besides its state: paid year ("Platný do") and the yearly sticker (R34, R36).

After a fee is paid the pass is marked `content_stale`; the web layer sends the new content to Google
Wallet after the commit (`push_pending`), like state changes in `ecp_state`. A failed push is retried
on the next call. The QR code is not touched here (it holds a one-time token, see ecp_verification).
"""

import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess.models import EcpPass, EcpPassState, Fee, Member
from ess.services import members, sticker
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


def content_patch(session: Session, ecp_pass: EcpPass) -> dict:
    """Fields of the Wallet object that follow the register and payments (not the QR code)."""
    from ess.services.ecp_issuance import _primary_club_name

    member = session.get(Member, ecp_pass.member_id)
    data = members.read_member(member)
    content = PassContent(
        object_id=ecp_pass.wallet_object_id, member_name=data.full_name(),
        club_name=_primary_club_name(session, member.id), card_number=data.card_number,
        member_since=data.member_since, birth_date=data.birth_date,
        photo_url="", check_url="",  # not patched
        valid_until=valid_until(session, member.id), hero_url=hero_url(session, member.id))
    obj = build_pass_object(content)
    return {k: obj[k] for k in ("header", "textModulesData", "heroImage") if k in obj}


def push_pending(session: Session, wallet: WalletClient) -> int:
    """Send changed content to Google Wallet. Commits each pass separately; returns the number pushed."""
    done = 0
    for ecp_pass in session.scalars(_pending_query()).all():
        try:
            wallet.patch_object(ecp_pass.wallet_object_id, content_patch(session, ecp_pass))
        except WalletError:
            log.warning("eCP content not pushed to Google Wallet; will retry")
            continue
        ecp_pass.content_stale = False
        session.commit()
        done += 1
    return done
