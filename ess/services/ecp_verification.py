"""Verification page behind the eCP QR code (PLAN section 5a, R18, R25).

The QR token is single-use: on the first scan a new token is issued and the pass in Google Wallet gets
the new QR. The scanned token stays valid for a short grace period (link previews, a phone without
signal). If a new QR cannot be issued (daily limit, Wallet error), the token is not consumed.
"""

import enum
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ess import audit
from ess.models import Club, Document, EcpPass, EcpPassState, Member, Membership, PositionHolder, VerificationToken
from ess.services import documents, members, settings
from ess.services.access import PUBLIC
from ess.services.ecp_issuance import hash_token, new_verification_token
from ess.wallet import WalletClient, WalletError

log = logging.getLogger(__name__)


class Outcome(str, enum.Enum):
    VALID = "valid"  # member of SSS, eCP active
    SUSPENDED = "suspended"  # eCP inactive (membership suspended in all clubs)
    NOT_MEMBER = "not_member"  # eCP revoked: expelled or left SSS (R25)
    USED = "used"  # QR already used, grace period over
    UNKNOWN = "unknown"  # no such token


@dataclass
class Contact:
    role: str
    name: str
    phone: str | None
    code: str = ""  # position code (the page translates the role)


@dataclass
class VerificationResult:
    outcome: Outcome
    full_name: str = ""
    address: str = ""
    club_name: str = ""
    club_logo_url: str | None = None  # public logo of the primary club
    member_since: date | None = None
    paid_until: date | None = None  # end of the last paid year (None = no fee paid)
    photo: str | None = None
    contacts: list[Contact] = field(default_factory=list)
    documents: list[Document] = field(default_factory=list)
    checked_at: datetime | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _paid_until(session: Session, member_id) -> date | None:
    from ess.services import ecp_content

    return ecp_content.valid_until(session, member_id)


def _primary_club(session: Session, member_id) -> Club | None:
    return session.scalar(
        select(Club).join(Membership, Membership.club_id == Club.id)
        .where(Membership.member_id == member_id, Membership.valid_to.is_(None), Membership.is_primary)
    )


def _contacts(session: Session, club: Club | None) -> list[Contact]:
    """Chair of the member's club and chair of SSS, from the current organisation structure."""
    wanted = [("club_chair", "Predseda skupiny", club.id if club else None), ("sss_chair", "Predseda SSS", None)]
    result = []
    for code, role, club_id in wanted:
        if code == "club_chair" and club_id is None:
            continue
        query = select(Member).join(PositionHolder, PositionHolder.member_id == Member.id).where(
            PositionHolder.position_code == code, PositionHolder.valid_to.is_(None))
        if club_id:
            query = query.where(PositionHolder.club_id == club_id)
        holder = session.scalar(query)
        if holder:
            data = members.read_member(holder)
            result.append(Contact(role, data.full_name(), data.phone, code))
    return result


def _rotate(session: Session, ecp_pass: EcpPass, wallet: WalletClient, base_url: str) -> bool:
    """Issue a new QR token and put it into the pass; False if not possible now."""
    today = datetime.combine(_now().date(), datetime.min.time(), tzinfo=UTC)
    issued_today = session.scalar(select(func.count()).select_from(VerificationToken).where(
        VerificationToken.pass_id == ecp_pass.id, VerificationToken.created_at >= today))
    if issued_today >= settings.get_int(session, "ecp_qr_daily_limit"):
        return False
    token = new_verification_token(session, ecp_pass)
    try:
        wallet.patch_object(ecp_pass.wallet_object_id,
                            {"barcode": {"type": "QR_CODE", "value": f"{base_url.rstrip('/')}/v/{token}"}})
    except WalletError:
        return False
    return True


def verify(session: Session, token: str, wallet: WalletClient, base_url: str) -> VerificationResult:
    row = session.scalar(
        select(VerificationToken).where(VerificationToken.token_hash == hash_token(token)).with_for_update()
    )
    if row is None:
        return VerificationResult(Outcome.UNKNOWN)
    ecp_pass = session.get(EcpPass, row.pass_id)
    if ecp_pass.state == EcpPassState.REVOKED.value:
        return VerificationResult(Outcome.NOT_MEMBER)
    now = _now()
    grace = timedelta(minutes=settings.get_int(session, "ecp_qr_grace_minutes"))
    if row.first_used_at is not None and now > row.first_used_at + grace:
        return VerificationResult(Outcome.USED)
    if row.first_used_at is None and ecp_pass.state == EcpPassState.ACTIVE.value:
        savepoint = session.begin_nested()
        if _rotate(session, ecp_pass, wallet, base_url):
            savepoint.commit()
            row.first_used_at = now
        else:
            savepoint.rollback()  # keep the old token valid; the pass still shows it
            log.info("QR token not rotated (daily limit or Wallet error)")
    member = session.get(Member, ecp_pass.member_id)
    if member.expelled_at or member.sss_ended_at:
        return VerificationResult(Outcome.NOT_MEMBER)
    data = members.read_member(member)
    club = _primary_club(session, member.id)
    audit.record(session, actor_type=PUBLIC.audit_type, actor_id=None, action="ecp.verify",
                 entity_type="ecp_pass", entity_id=str(ecp_pass.id))
    outcome = Outcome.VALID if ecp_pass.state == EcpPassState.ACTIVE.value else Outcome.SUSPENDED
    return VerificationResult(
        outcome=outcome, full_name=data.full_name(), address=data.full_address(),
        club_name=club.name if club else "", club_logo_url=club.logo_url if club else None,
        member_since=member.member_since, photo=ecp_pass.photo, paid_until=_paid_until(session, member.id),
        contacts=_contacts(session, club), documents=documents.valid_documents(session), checked_at=now,
    )
