"""ORM models. See docs/data-model.md (phase 1) and docs/data-model-ecp.md (phase 2).

Columns ending in `_enc` hold values encrypted by `ess.security.pii`; `_bidx` columns hold blind
indexes. Never read or write them directly - use the helpers in `ess.services`.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ess.db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Club(TimestampMixin, Base):
    __tablename__ = "clubs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), unique=True)
    # Short unique code used in imports (e.g. "JS-DEM"); "SSS" for the unaffiliated club.
    code: Mapped[str | None] = mapped_column(String(20), unique=True)
    short_name: Mapped[str | None] = mapped_column(String(50))
    # Public image of the club logo (https), e.g. in the Cloud Storage bucket. Not personal data.
    logo_url: Mapped[str | None] = mapped_column(String(500))
    # Public contact details of the club (an association, not personal data).
    street: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(10))
    country: Mapped[str] = mapped_column(String(2), default="SK", server_default="SK")
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(50))
    web: Mapped[str | None] = mapped_column(String(300))
    founded_on: Mapped[date | None] = mapped_column(Date)
    is_unaffiliated: Mapped[bool] = mapped_column(Boolean, default=False)
    uses_candidates: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        # Exactly one "SSS - nezaradení" club.
        Index("uq_clubs_unaffiliated", "is_unaffiliated", unique=True, postgresql_where=text("is_unaffiliated")),
    )


class Member(TimestampMixin, Base):
    __tablename__ = "members"

    id: Mapped[uuid.UUID] = _uuid_pk()
    first_name_enc: Mapped[bytes] = mapped_column(LargeBinary)
    last_name_enc: Mapped[bytes] = mapped_column(LargeBinary)
    title_before_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    title_after_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    birth_date_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    email_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    street_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    city_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    postal_code_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    country: Mapped[str] = mapped_column(String(2), default="SK", server_default="SK")  # not identifying alone
    phone_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    card_number_enc: Mapped[bytes | None] = mapped_column(LargeBinary)

    lookup_bidx: Mapped[bytes | None] = mapped_column(LargeBinary, index=True)
    email_bidx: Mapped[bytes | None] = mapped_column(LargeBinary)
    card_number_bidx: Mapped[bytes | None] = mapped_column(LargeBinary)

    member_since: Mapped[date | None] = mapped_column(Date)
    reduced_fee: Mapped[bool] = mapped_column(Boolean, default=False)
    # The member receives the SSS card (no smartphone); "pdf" or "png". None = no card (R33).
    card_format: Mapped[str | None] = mapped_column(String(3))
    expelled_at: Mapped[date | None] = mapped_column(Date)
    expelled_reason: Mapped[str | None] = mapped_column(Text)
    # SSS membership ended by decision of the presidium (not expulsion) - can be restored later.
    sss_ended_at: Mapped[date | None] = mapped_column(Date)
    sss_ended_note: Mapped[str | None] = mapped_column(Text)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="member")

    __table_args__ = (
        # Not unique: spouses often share one e-mail. Never identify a member by e-mail alone.
        Index("ix_members_email_bidx", "email_bidx"),
        Index(
            "uq_members_card_number_bidx",
            "card_number_bidx",
            unique=True,
            postgresql_where=text("card_number_bidx IS NOT NULL"),
        ),
    )


class MembershipStatus(str, enum.Enum):
    CANDIDATE = "candidate"
    PENDING_ACTIVATION = "pending_activation"
    MEMBER = "member"
    SUSPENDED = "suspended"


class MembershipEndReason(str, enum.Enum):
    STATUS_CHANGE = "status_change"  # replaced by a newer record of the same membership
    TERMINATED = "terminated"
    EXPELLED = "expelled"


class Membership(TimestampMixin, Base):
    """One period of a member's membership in a club. A status change closes the record and opens a new one."""

    __tablename__ = "memberships"

    id: Mapped[uuid.UUID] = _uuid_pk()
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id"), index=True)
    club_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clubs.id"), index=True)
    status: Mapped[MembershipStatus] = mapped_column(
        Enum(MembershipStatus, name="membership_status", values_callable=lambda e: [m.value for m in e])
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    end_reason: Mapped[MembershipEndReason | None] = mapped_column(
        Enum(MembershipEndReason, name="membership_end_reason", values_callable=lambda e: [m.value for m in e])
    )
    created_by: Mapped[str | None] = mapped_column(String(64))
    activated_by: Mapped[str | None] = mapped_column(String(64))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

    member: Mapped[Member] = relationship(back_populates="memberships")
    club: Mapped[Club] = relationship()

    __table_args__ = (
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="ck_memberships_period"),
        CheckConstraint("(valid_to IS NULL) = (end_reason IS NULL)", name="ck_memberships_end_reason"),
        CheckConstraint("valid_to IS NULL OR NOT is_primary", name="ck_memberships_closed_not_primary"),
        Index(
            "uq_memberships_open_member_club",
            "member_id",
            "club_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
        Index(
            "uq_memberships_open_primary",
            "member_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL AND is_primary"),
        ),
    )


class OrgPosition(Base):
    __tablename__ = "org_positions"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    is_single: Mapped[bool] = mapped_column(Boolean)  # only one holder at a time (per club for club_chair)
    is_club_bound: Mapped[bool] = mapped_column(Boolean)
    sort_order: Mapped[int] = mapped_column()


class PositionHolder(TimestampMixin, Base):
    __tablename__ = "position_holders"

    id: Mapped[uuid.UUID] = _uuid_pk()
    position_code: Mapped[str] = mapped_column(ForeignKey("org_positions.code"))
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id"), index=True)
    club_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clubs.id"))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="ck_position_holders_period"),
        Index(
            "uq_position_holders_single",
            "position_code",
            unique=True,
            postgresql_where=text("valid_to IS NULL AND position_code IN ('sss_chair', 'sss_vice_chair', 'audit_chair')"),
        ),
        Index(
            "uq_position_holders_club_chair",
            "club_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL AND position_code = 'club_chair'"),
        ),
    )


class AdminRole(str, enum.Enum):
    ADMIN = "admin"
    SYSTEM_ADMIN = "system_admin"


class AdminUser(TimestampMixin, Base):
    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    display_name_enc: Mapped[bytes] = mapped_column(LargeBinary)
    google_email_enc: Mapped[bytes] = mapped_column(LargeBinary)
    google_email_bidx: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    role: Mapped[AdminRole] = mapped_column(
        Enum(AdminRole, name="admin_role", values_callable=lambda e: [m.value for m in e])
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    granted_by: Mapped[str | None] = mapped_column(String(64))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CertificateType(Base):
    __tablename__ = "certificate_types"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MemberCertificate(TimestampMixin, Base):
    __tablename__ = "member_certificates"

    id: Mapped[uuid.UUID] = _uuid_pk()
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id"), index=True)
    certificate_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("certificate_types.id"))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(1000))
    valid_until: Mapped[date | None] = mapped_column(Date)
    sort_order: Mapped[int] = mapped_column(default=0)


class TaskType(str, enum.Enum):
    MEMBER_ACTIVATION = "member_activation"  # new member / promoted candidate proposed by a club chair
    SSS_DECISION = "sss_decision"  # member left all clubs; presidium decides about SSS membership
    ECP_ISSUE = "ecp_issue"  # submitted eCP application waiting for approval
    PAYMENT_UNMATCHED = "payment_unmatched"  # bank payment with an unknown reference (no member)
    PAYMENT_OVERPAID = "payment_overpaid"  # more was paid than owed: refund or gift


class TaskStatus(str, enum.Enum):
    OPEN = "open"
    DONE = "done"
    REJECTED = "rejected"
    CANCELLED = "cancelled"  # the subject changed so the task no longer applies


class Task(Base):
    """A request waiting for an administrator ("Požiadavky").

    Tasks are opened and closed by the services in the same transaction as the change they belong to,
    so the list always matches the data. Types and statuses are stored as text to allow new types
    without altering a database enum.
    """

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    task_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default=TaskStatus.OPEN.value)
    member_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("members.id"), index=True)
    membership_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("memberships.id"))
    bank_transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_transactions.id"))
    club_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clubs.id"))
    context: Mapped[dict | None] = mapped_column(JSONB)  # e.g. {"from_status": "candidate"}; no personal data
    requested_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(64))
    resolution: Mapped[str | None] = mapped_column(String(32))  # e.g. activated, rejected, restored, sss_ended
    resolution_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_tasks_open", "status", "task_type"),
        Index(
            "uq_tasks_open_activation",
            "membership_id",
            unique=True,
            postgresql_where=text("status = 'open' AND task_type = 'member_activation'"),
        ),
        Index(
            "uq_tasks_open_sss_decision",
            "member_id",
            unique=True,
            postgresql_where=text("status = 'open' AND task_type = 'sss_decision'"),
        ),
        Index(
            "uq_tasks_open_ecp_issue",
            "member_id",
            unique=True,
            postgresql_where=text("status = 'open' AND task_type = 'ecp_issue'"),
        ),
    )


# --- phase 2: eCP and SSS card (docs/data-model-ecp.md) ---------------------------------------------------


class EcpApplicationSource(str, enum.Enum):
    PUBLIC = "public"  # existing member applies on the public page (R22)
    CLUB_CHAIR = "club_chair"  # new member proposed by a club chair with "issue eCP" (R23)


class EcpApplicationStatus(str, enum.Enum):
    EMAIL_PENDING = "email_pending"
    PHOTO_PENDING = "photo_pending"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class EcpApplication(TimestampMixin, Base):
    """An application for an eCP. Personal data from the form are encrypted; they are copied to the
    member only after approval. Status is stored as text (new states without altering an enum)."""

    __tablename__ = "ecp_applications"

    id: Mapped[uuid.UUID] = _uuid_pk()
    source: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    member_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("members.id"), index=True)
    club_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clubs.id"))
    first_name_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    last_name_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    birth_date_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    email_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    email_bidx: Mapped[bytes | None] = mapped_column(LargeBinary, index=True)  # rate limit per e-mail
    card_number_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    member_since_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    photo_original: Mapped[str | None] = mapped_column(String(200))  # object name; deleted after decision
    photo_cropped: Mapped[str | None] = mapped_column(String(200))
    wants_wallet: Mapped[bool] = mapped_column(Boolean, default=True)
    wants_card: Mapped[bool] = mapped_column(Boolean, default=False)
    reject_reason: Mapped[str | None] = mapped_column(Text)  # shown to the applicant; no personal data
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_ecp_applications_status", "status"),
        # At most one unfinished application per member.
        Index("uq_ecp_applications_open", "member_id", unique=True,
              postgresql_where=text("status IN ('email_pending', 'photo_pending', 'submitted')")),
    )


class OneTimeToken(Base):
    """Single-use link token sent by e-mail. Only the SHA-256 hash is stored."""

    __tablename__ = "one_time_tokens"

    id: Mapped[uuid.UUID] = _uuid_pk()
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    purpose: Mapped[str] = mapped_column(String(32))  # email_verify, ecp_photo
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ecp_applications.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Consent(Base):
    """Consent given or withdrawn (never deleted; the newest record per kind applies)."""

    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # gdpr_ecp, notifications
    text_version: Mapped[str] = mapped_column(String(32))
    granted: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(32))  # application, paper_form
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ecp_applications.id"))
    recorded_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EcpPassState(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"  # suspended in all clubs; restorable
    REVOKED = "revoked"  # expelled or left SSS (R25); final


class EcpPass(TimestampMixin, Base):
    """eCP in Google Wallet."""

    __tablename__ = "ecp_passes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id"), index=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ecp_applications.id"))
    wallet_object_id: Mapped[str] = mapped_column(String(120), unique=True)  # issuer.random, no personal data
    state: Mapped[str] = mapped_column(String(16))
    wallet_state: Mapped[str | None] = mapped_column(String(16))  # last state sent to Google Wallet
    # Content (paid year, sticker, name) changed and is not yet in Google Wallet (retried after commits).
    content_stale: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Random id in the portal link of the pass (/p/<key>); says who logs in, is not a proof of identity (R38).
    portal_key: Mapped[str | None] = mapped_column(String(43), unique=True)
    photo: Mapped[str | None] = mapped_column(String(200))  # object name in the media bucket
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("uq_ecp_passes_current", "member_id", unique=True, postgresql_where=text("state <> 'revoked'")),
    )


class VerificationToken(Base):
    """Token in the eCP QR code (R18). After first use it stays valid for a short grace period."""

    __tablename__ = "verification_tokens"

    id: Mapped[uuid.UUID] = _uuid_pk()
    pass_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ecp_passes.id"), index=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    first_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SssCard(Base):
    """Printable SSS card (PDF) for one calendar year with its own code."""

    __tablename__ = "sss_cards"

    id: Mapped[uuid.UUID] = _uuid_pk()
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id"), index=True)
    year: Mapped[int]
    code_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    code_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # encrypted code: download / send the same card again
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    issued_by: Mapped[str | None] = mapped_column(String(64))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(16))  # lost, stolen, damaged

    __table_args__ = (
        Index("uq_sss_cards_member_year", "member_id", "year", unique=True, postgresql_where=text("revoked_at IS NULL")),
    )


class ClubDelegation(Base):
    """A club chair hands over managing the club to another member (R37). At most one active per club."""

    __tablename__ = "club_delegations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    club_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clubs.id"), index=True)
    chair_member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id"))  # chair who is represented
    delegate_member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id"), index=True)
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_by: Mapped[str | None] = mapped_column(String(64))
    # taken_back (chair), resigned (delegate), chair_changed, delegate_left, replaced (administrator)
    end_reason: Mapped[str | None] = mapped_column(String(16))

    __table_args__ = (
        Index("uq_club_delegations_active", "club_id", unique=True, postgresql_where=text("ended_at IS NULL")),
    )


# --- phase 3: payments (docs/data-model-payments.md) ---------------------------------------------------------


class Fee(TimestampMixin, Base):
    """Membership fee of a member for one year. The amount is fixed when the fee is assessed."""

    __tablename__ = "fees"

    id: Mapped[uuid.UUID] = _uuid_pk()
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id"), index=True)
    year: Mapped[int]
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    reduced: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_reference_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_references.id"))
    paid_manually_by: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("uq_fees_member_year", "member_id", "year", unique=True),)


class PaymentReferenceKind(str, enum.Enum):
    MEMBER = "member"  # a member pays for themselves (link in the eCP)
    BULK = "bulk"  # a club chair pays for selected members


class PaymentReferenceStatus(str, enum.Enum):
    OPEN = "open"
    PARTIAL = "partial"
    PAID = "paid"
    CANCELLED = "cancelled"


class PaymentReference(TimestampMixin, Base):
    """Code sent in the "payer reference" field (R35); maps a payment to fees."""

    __tablename__ = "payment_references"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(12), unique=True)
    kind: Mapped[str] = mapped_column(String(8))
    year: Mapped[int]
    club_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clubs.id"))
    created_by: Mapped[str | None] = mapped_column(String(64))
    expected_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(10), default=PaymentReferenceStatus.OPEN.value)

    items: Mapped[list["PaymentReferenceItem"]] = relationship(back_populates="reference")

    __table_args__ = (
        Index("ix_payment_references_status", "status"),
        CheckConstraint("kind IN ('member', 'bulk')", name="ck_payment_references_kind"),
        CheckConstraint("status IN ('open', 'partial', 'paid', 'cancelled')", name="ck_payment_references_status"),
    )


class PaymentReferenceItem(Base):
    __tablename__ = "payment_reference_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    reference_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payment_references.id"), index=True)
    fee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fees.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    reference: Mapped[PaymentReference] = relationship(back_populates="items")
    fee: Mapped[Fee] = relationship()


class BankStatement(Base):
    """An uploaded bank statement; the same file cannot be uploaded twice."""

    __tablename__ = "bank_statements"

    id: Mapped[uuid.UUID] = _uuid_pk()
    file_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    file_format: Mapped[str] = mapped_column(String(16))
    uploaded_by: Mapped[str | None] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BankTransaction(Base):
    """An incoming payment from a bank statement."""

    __tablename__ = "bank_transactions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    statement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_statements.id"), index=True)
    bank_ref: Mapped[str] = mapped_column(String(100), unique=True)
    booked_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3))
    payer_reference: Mapped[str | None] = mapped_column(String(140))
    payer_name_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    payer_iban_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    message_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # payment message (may hold personal data)
    payment_reference_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_references.id"))
    result: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- phase 4: member portal (R38) ----------------------------------------------------------------------------


class MemberLoginCode(Base):
    """6-digit code sent by e-mail; valid only in the browser that asked for it. Only hashes are stored."""

    __tablename__ = "member_login_codes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id"), index=True)
    code_hash: Mapped[bytes] = mapped_column(LargeBinary)
    browser_hash: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemberSession(Base):
    """A signed-in device of a member (cookie holds the token, the database only its hash)."""

    __tablename__ = "member_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id"), index=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    method: Mapped[str] = mapped_column(String(16))  # email_code, passkey
    device: Mapped[str | None] = mapped_column(String(60))  # e.g. "Chrome, Android" (from the browser)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemberPasskey(Base):
    """A passkey of a member (WebAuthn). Only the public key is stored."""

    __tablename__ = "member_passkeys"

    id: Mapped[uuid.UUID] = _uuid_pk()
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id"), index=True)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    # The device (session) where it was set up; logging that device out removes the passkey too.
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("member_sessions.id"))
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EcpNotification(Base):
    """A message sent by an administrator to the eCP of all members who agreed to notifications (R41)."""

    __tablename__ = "ecp_notifications"

    id: Mapped[uuid.UUID] = _uuid_pk()
    header: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    recipients: Mapped[int] = mapped_column(default=0)


class EcpNotificationDelivery(Base):
    """One notification to one eCP; sent in batches after commits (`sent_at` empty = waiting)."""

    __tablename__ = "ecp_notification_deliveries"

    id: Mapped[uuid.UUID] = _uuid_pk()
    notification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ecp_notifications.id"), index=True)
    pass_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ecp_passes.id"))
    attempts: Mapped[int] = mapped_column(default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # gave up after repeated errors

    __table_args__ = (
        Index("uq_ecp_notification_deliveries", "notification_id", "pass_id", unique=True),
        Index("ix_ecp_notification_deliveries_waiting", "notification_id",
              postgresql_where=text("sent_at IS NULL AND failed_at IS NULL")),
    )


class CaveTrip(Base):
    """A member reports going into a cave (R41). Reminder to the member 30 min after the planned return,
    alert to the chair of the primary club 30 min later, unless the member confirms being out."""

    __tablename__ = "cave_trips"

    id: Mapped[uuid.UUID] = _uuid_pk()
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id"), index=True)
    cave_enc: Mapped[bytes] = mapped_column(LargeBinary)  # where (with the time it says where the person is)
    companions_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # names of other people
    planned_return_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("uq_cave_trips_open", "member_id", unique=True, postgresql_where=text("returned_at IS NULL")),
    )
