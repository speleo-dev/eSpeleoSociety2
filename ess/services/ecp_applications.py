"""Applications for an eCP (R22, R23, docs/data-model-ecp.md).

Public application, step 1: the form is matched against the register; only on an exact match an
e-mail with a one-time link is sent. The visitor always sees the same answer, so the page cannot be
used to find out who is a member or to send e-mails to arbitrary addresses.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ess import audit
from ess.models import (
    EcpApplication,
    EcpApplicationSource,
    EcpApplicationStatus,
    EcpPass,
    EcpPassState,
    Member,
    Membership,
    MembershipStatus,
    OneTimeToken,
)
from ess.security import pii
from ess.security.crypto import normalize_for_index
from ess.services import members, settings
from ess.services.access import PUBLIC, DomainError

S = EcpApplicationStatus
OPEN_STATUSES = (S.EMAIL_PENDING.value, S.PHOTO_PENDING.value, S.SUBMITTED.value)
UNFINISHED_STATUSES = (S.EMAIL_PENDING.value, S.PHOTO_PENDING.value)
MAX_APPLICATIONS_PER_EMAIL_PER_DAY = 3
PURPOSE_EMAIL_VERIFY = "email_verify"


@dataclass
class ApplicationForm:
    """What the applicant typed. Exists only in memory, never logged."""

    first_name: str
    last_name: str
    birth_date: date | None
    email: str
    card_number: str
    member_since_year: int | None
    club_id: uuid.UUID | None


@dataclass
class VerificationMail:
    """Returned when an e-mail should be sent (after commit)."""

    email: str
    first_name: str
    token: str


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii", errors="ignore")).digest()


def _now() -> datetime:
    return datetime.now(UTC)


def validate_form(form: ApplicationForm) -> None:
    """Checks visible to the applicant (they do not depend on the register)."""
    if not form.first_name.strip() or not form.last_name.strip():
        raise DomainError("name_required")
    if form.birth_date is None:
        raise DomainError("birth_date_required")
    if "@" not in form.email or len(form.email) > 254 or any(c in form.email for c in "\r\n<>,; "):
        raise DomainError("invalid_email")
    if not form.card_number.strip():
        raise DomainError("card_number_required")
    this_year = date.today().year
    if form.member_since_year is None or not (1900 <= form.member_since_year <= this_year):
        raise DomainError("member_since_required")
    if form.club_id is None:
        raise DomainError("club_required")


def _same_card(a: str, b: str) -> bool:
    return normalize_for_index(a).replace(" ", "") == normalize_for_index(b).replace(" ", "")


def find_member(session: Session, form: ApplicationForm) -> Member | None:
    """Exact match (R22): name, birth date and e-mail must match; card number and "member since"
    must match when the register has them. The member must be an active member of the chosen club."""
    index = members.lookup_index(form.first_name, form.last_name, form.birth_date.year)
    email_index = members.email_index(form.email)
    if index is None or email_index is None:
        return None
    candidates = session.scalars(
        select(Member).where(Member.lookup_bidx == index, Member.email_bidx == email_index,
                             Member.expelled_at.is_(None), Member.sss_ended_at.is_(None))
    ).all()
    matches = []
    for member in candidates:
        data = members.read_member(member)
        if data.birth_date != form.birth_date:
            continue
        if data.card_number and not _same_card(data.card_number, form.card_number):
            continue
        if member.member_since and member.member_since.year != form.member_since_year:
            continue
        in_club = session.scalar(
            select(Membership.id).where(Membership.member_id == member.id, Membership.club_id == form.club_id,
                                        Membership.valid_to.is_(None),
                                        Membership.status == MembershipStatus.MEMBER)
        )
        if in_club:
            matches.append(member)
    return matches[0] if len(matches) == 1 else None


def expire_stale(session: Session) -> None:
    """Unfinished applications expire after the configured number of days."""
    days = settings.get_int(session, "ecp_application_expiry_days")
    session.execute(
        update(EcpApplication)
        .where(EcpApplication.status.in_(UNFINISHED_STATUSES),
               EcpApplication.created_at < _now() - timedelta(days=days))
        .values(status=S.EXPIRED.value)
    )


def _has_current_pass(session: Session, member_id: uuid.UUID) -> bool:
    return session.scalar(
        select(EcpPass.id).where(EcpPass.member_id == member_id, EcpPass.state != EcpPassState.REVOKED.value)
    ) is not None


def _new_token(session: Session, application: EcpApplication, purpose: str) -> str:
    token = secrets.token_urlsafe(32)
    hours = settings.get_int(session, "ecp_link_valid_hours")
    session.add(OneTimeToken(id=uuid.uuid4(), token_hash=hash_token(token), purpose=purpose,
                             application_id=application.id, expires_at=_now() + timedelta(hours=hours)))
    return token


def start_public(session: Session, form: ApplicationForm) -> VerificationMail | None:
    """Step 1 of the public application. Returns the e-mail to send, or None (silently) when the data
    do not match the register, the member already has an eCP or too many attempts were made."""
    validate_form(form)
    expire_stale(session)
    email_index = members.email_index(form.email)
    recent = session.scalar(
        select(func.count()).select_from(EcpApplication).where(
            EcpApplication.email_bidx == email_index, EcpApplication.created_at > _now() - timedelta(days=1))
    )
    if recent >= MAX_APPLICATIONS_PER_EMAIL_PER_DAY:
        return None
    member = find_member(session, form)
    if member is None or _has_current_pass(session, member.id):
        return None
    # A new application replaces an unfinished one (e.g. the first e-mail got lost).
    open_app = session.scalar(
        select(EcpApplication).where(EcpApplication.member_id == member.id,
                                     EcpApplication.status.in_(OPEN_STATUSES))
    )
    if open_app is not None:
        if open_app.status == S.SUBMITTED.value:
            return None  # already waiting for the administrator
        open_app.status = S.CANCELLED.value
        session.flush()
    ctx = "ecp_applications."
    application = EcpApplication(
        id=uuid.uuid4(), source=EcpApplicationSource.PUBLIC.value, status=S.EMAIL_PENDING.value,
        member_id=member.id, club_id=form.club_id,
        first_name_enc=pii.encrypt(form.first_name.strip(), ctx + "first_name"),
        last_name_enc=pii.encrypt(form.last_name.strip(), ctx + "last_name"),
        birth_date_enc=pii.encrypt_date(form.birth_date, ctx + "birth_date"),
        email_enc=pii.encrypt(form.email.strip(), ctx + "email"),
        email_bidx=email_index,
        card_number_enc=pii.encrypt(form.card_number.strip(), ctx + "card_number"),
        member_since_enc=pii.encrypt(str(form.member_since_year), ctx + "member_since"),
        wants_wallet=True, wants_card=False,
    )
    session.add(application)
    session.flush()
    token = _new_token(session, application, PURPOSE_EMAIL_VERIFY)
    audit.record(session, actor_type=PUBLIC.audit_type, actor_id=None, action="ecp_application.start",
                 entity_type="ecp_application", entity_id=str(application.id))
    return VerificationMail(email=form.email.strip(), first_name=form.first_name.strip(), token=token)


def use_token(session: Session, token: str, purpose: str) -> EcpApplication | None:
    """Consume a one-time link token; None if unknown, used or expired."""
    row = session.scalar(
        select(OneTimeToken).where(OneTimeToken.token_hash == hash_token(token), OneTimeToken.purpose == purpose)
        .with_for_update()
    )
    if row is None or row.used_at is not None or row.expires_at <= _now():
        return None
    row.used_at = _now()
    return session.get(EcpApplication, row.application_id)


def verify_email(session: Session, token: str) -> EcpApplication | None:
    """Step 2: the applicant clicked the link in the e-mail."""
    expire_stale(session)
    application = use_token(session, token, PURPOSE_EMAIL_VERIFY)
    if application is None or application.status != S.EMAIL_PENDING.value:
        return None
    application.status = S.PHOTO_PENDING.value
    application.email_verified_at = _now()
    audit.record(session, actor_type=PUBLIC.audit_type, actor_id=None, action="ecp_application.email_verified",
                 entity_type="ecp_application", entity_id=str(application.id))
    return application


# --- step 3: photo and consents ------------------------------------------------------------------------

CONSENT_GDPR = "gdpr_ecp"
CONSENT_NOTIFICATIONS = "notifications"
CONSENT_TEXT_VERSION = "2026-1"  # bump when the texts in public/apply_photo.html change


@dataclass
class PhotoUpload:
    """Objects stored in the bucket; the caller deletes them if the transaction fails."""

    application: EcpApplication
    objects: list[str]


def random_photo_name(prefix: str) -> str:
    return f"{prefix}/{secrets.token_hex(32)}.jpg"  # 64 random characters (R24)


def submit_photo(
    session: Session, application_id: uuid.UUID, photo: bytes, crop: tuple[float, float, float, float] | None,
    gdpr_consent: bool, notifications: bool, wants_card: bool, store,
) -> PhotoUpload:
    """The applicant uploads a face photo and gives consents; the application goes to the administrator."""
    from ess.images import crop_portrait, normalize_original
    from ess.models import Consent, TaskType
    from ess.services import tasks

    if not gdpr_consent:
        raise DomainError("gdpr_consent_required")
    if store is None:
        raise DomainError("media_store_not_configured")
    application = session.get(EcpApplication, application_id, with_for_update=True)
    if application is None or application.status != S.PHOTO_PENDING.value:
        raise DomainError("application_not_open")
    original = normalize_original(photo)
    portrait = crop_portrait(original, crop)
    original_name, portrait_name = random_photo_name("originals"), random_photo_name("photos")
    store.put(original_name, original, "image/jpeg")
    store.put(portrait_name, portrait, "image/jpeg")
    application.photo_original, application.photo_cropped = original_name, portrait_name
    application.wants_card = wants_card
    application.status = S.SUBMITTED.value
    application.submitted_at = _now()
    for kind, granted in ((CONSENT_GDPR, True), (CONSENT_NOTIFICATIONS, notifications)):
        session.add(Consent(id=uuid.uuid4(), member_id=application.member_id, kind=kind,
                            text_version=CONSENT_TEXT_VERSION, granted=granted, source="application",
                            application_id=application.id))
    tasks.open_task(session, PUBLIC, TaskType.ECP_ISSUE, application.member_id, club_id=application.club_id,
                    context={"application_id": str(application.id)})
    audit.record(session, actor_type=PUBLIC.audit_type, actor_id=None, action="ecp_application.submit",
                 entity_type="ecp_application", entity_id=str(application.id))
    return PhotoUpload(application, [original_name, portrait_name])
