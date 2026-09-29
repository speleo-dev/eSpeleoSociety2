"""Decision about an eCP application: approve (issue the Google Wallet pass), reject, re-crop the photo.

External calls (Cloud Storage, Google Wallet) happen before the commit; objects that must disappear are
returned in `cleanup` and deleted by the caller only after a successful commit.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess import audit
from ess.config import get_settings
from ess.images import crop_portrait
from ess.models import (
    Club,
    EcpApplication,
    EcpApplicationStatus,
    EcpPass,
    EcpPassState,
    Member,
    Membership,
    TaskStatus,
    TaskType,
    VerificationToken,
)
from ess.security import pii
from ess.services import ecp_content, members, portal_auth, tasks
from ess.services.access import Actor, DomainError, require_admin
from ess.services.ecp_applications import random_photo_name
from ess.wallet import PassContent, WalletClient, WalletError, build_pass_object

S = EcpApplicationStatus
_CTX = "ecp_applications."


@dataclass
class ApplicationView:
    """Application compared with the register, for the review page. In memory only."""

    application: EcpApplication
    member: Member
    first_name: str
    last_name: str
    birth_date: date | None
    email: str
    card_number: str
    member_since_year: str
    register: members.MemberData
    club_name: str
    fills: list[str] = field(default_factory=list)  # data that approval adds to the register


@dataclass
class Decision:
    application: EcpApplication
    email: str
    first_name: str
    save_url: str | None = None
    cleanup: list[str] = field(default_factory=list)
    member_name: str = ""


def _now() -> datetime:
    return datetime.now(UTC)


def _open_application(session: Session, application_id: uuid.UUID) -> EcpApplication:
    application = session.get(EcpApplication, application_id, with_for_update=True)
    if application is None or application.status != S.SUBMITTED.value:
        raise DomainError("application_not_open")
    return application


def view(session: Session, actor: Actor, application_id: uuid.UUID) -> ApplicationView:
    require_admin(actor)
    application = session.get(EcpApplication, application_id)
    if application is None:
        raise DomainError("application_not_found")
    member = session.get(Member, application.member_id)
    register = members.read_member(member)
    club = session.get(Club, application.club_id) if application.club_id else None
    result = ApplicationView(
        application=application, member=member,
        first_name=pii.decrypt(application.first_name_enc, _CTX + "first_name") or "",
        last_name=pii.decrypt(application.last_name_enc, _CTX + "last_name") or "",
        birth_date=pii.decrypt_date(application.birth_date_enc, _CTX + "birth_date"),
        email=pii.decrypt(application.email_enc, _CTX + "email") or "",
        card_number=pii.decrypt(application.card_number_enc, _CTX + "card_number") or "",
        member_since_year=pii.decrypt(application.member_since_enc, _CTX + "member_since") or "",
        register=register, club_name=club.name if club else "",
    )
    if application.source == "club_chair":  # the chair entered the data; nothing to compare
        result.first_name, result.last_name = register.first_name, register.last_name
        result.birth_date = register.birth_date
    if not register.card_number and result.card_number:
        result.fills.append("card_number")
    if not member.member_since and result.member_since_year:
        result.fills.append("member_since")
    return result


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii", errors="ignore")).digest()


def new_verification_token(session: Session, ecp_pass: EcpPass) -> str:
    """Token for the QR code (R18); only its hash is stored."""
    token = secrets.token_urlsafe(24)
    session.add(VerificationToken(id=uuid.uuid4(), pass_id=ecp_pass.id, token_hash=hash_token(token)))
    return token


def _primary_club_name(session: Session, member_id: uuid.UUID) -> str:
    return session.scalar(
        select(Club.name).join(Membership, Membership.club_id == Club.id)
        .where(Membership.member_id == member_id, Membership.valid_to.is_(None), Membership.is_primary)
    ) or ""


def approve(session: Session, actor: Actor, application_id: uuid.UUID, store, wallet: WalletClient,
            base_url: str) -> Decision:
    """Approve: fill missing register data, create the pass in Google Wallet, sign the save link."""
    require_admin(actor)
    if store is None:
        raise DomainError("media_store_not_configured")
    info = view(session, actor, application_id)
    application = _open_application(session, application_id)
    member = info.member
    if member.expelled_at or member.sss_ended_at:
        raise DomainError("member_not_in_sss")
    if session.scalar(select(EcpPass.id).where(EcpPass.member_id == member.id,
                                               EcpPass.state != EcpPassState.REVOKED.value)):
        raise DomainError("member_has_ecp")

    data = info.register
    if "card_number" in info.fills:
        data.card_number = info.card_number
    if "member_since" in info.fills:
        data.member_since = date(int(info.member_since_year), 1, 1)
    if info.fills:
        members.update_member(session, actor, member.id, data)

    ecp_pass = EcpPass(id=uuid.uuid4(), member_id=member.id, application_id=application.id,
                       wallet_object_id=f"{get_settings().wallet_issuer_id}.{secrets.token_hex(16)}",
                       state=EcpPassState.ACTIVE.value, photo=application.photo_cropped,
                       portal_key=portal_auth.new_portal_key())
    session.add(ecp_pass)
    session.flush()
    token = new_verification_token(session, ecp_pass)
    content = PassContent(
        object_id=ecp_pass.wallet_object_id, member_name=data.full_name(),
        club_name=_primary_club_name(session, member.id), card_number=data.card_number,
        member_since=data.member_since, birth_date=data.birth_date,
        photo_url=store.url(application.photo_cropped), check_url=f"{base_url.rstrip('/')}/v/{token}",
        valid_until=ecp_content.valid_until(session, member.id), hero_url=ecp_content.hero_url(session, member.id),
        payment=ecp_content.payment_link(session, member.id), portal_url=ecp_content.portal_url(ecp_pass, base_url))
    try:
        wallet.upsert_object(build_pass_object(content))
        save_url = wallet.save_url(ecp_pass.wallet_object_id)
    except WalletError:
        raise DomainError("wallet_error") from None
    ecp_pass.wallet_state = ecp_pass.state

    application.status = S.APPROVED.value
    application.decided_at, application.decided_by = _now(), actor.id
    cleanup = [application.photo_original] if application.photo_original else []
    application.photo_original = None
    tasks.close_tasks(session, actor, TaskType.ECP_ISSUE, TaskStatus.DONE, "approved", member_id=member.id)
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="ecp.issue",
                 entity_type="ecp_pass", entity_id=str(ecp_pass.id),
                 details={"application_id": str(application.id), "filled": info.fills})
    return Decision(application, info.email, info.first_name, save_url, cleanup, member_name=data.full_name())


def reject(session: Session, actor: Actor, application_id: uuid.UUID, reason: str) -> Decision:
    """Reject with a reason for the applicant (e.g. unsuitable photo); both photos are deleted."""
    require_admin(actor)
    reason = " ".join(reason.split())
    if not reason:
        raise DomainError("reason_required")
    info = view(session, actor, application_id)
    application = _open_application(session, application_id)
    application.status = S.REJECTED.value
    application.reject_reason = reason[:500]
    application.decided_at, application.decided_by = _now(), actor.id
    cleanup = [n for n in (application.photo_original, application.photo_cropped) if n]
    application.photo_original = application.photo_cropped = None
    tasks.close_tasks(session, actor, TaskType.ECP_ISSUE, TaskStatus.REJECTED, "rejected",
                      member_id=application.member_id, note=reason)
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="ecp_application.reject",
                 entity_type="ecp_application", entity_id=str(application.id))
    return Decision(application, info.email, info.first_name, cleanup=cleanup)


def recrop(session: Session, actor: Actor, application_id: uuid.UUID, crop, store) -> Decision:
    """The administrator crops the original photo again."""
    require_admin(actor)
    if store is None:
        raise DomainError("media_store_not_configured")
    application = _open_application(session, application_id)
    if not application.photo_original:
        raise DomainError("photo_missing")
    portrait = crop_portrait(store.get(application.photo_original), crop)
    name = random_photo_name("photos")
    store.put(name, portrait, "image/jpeg")
    cleanup = [application.photo_cropped] if application.photo_cropped else []
    application.photo_cropped = name
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="ecp_application.recrop",
                 entity_type="ecp_application", entity_id=str(application.id))
    return Decision(application, "", "", cleanup=cleanup)
