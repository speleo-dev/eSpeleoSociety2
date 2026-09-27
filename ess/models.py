"""ORM models for phase 1 (administration). See docs/data-model.md.

Columns ending in `_enc` hold values encrypted by `ess.security.pii`; `_bidx` columns hold blind
indexes. Never read or write them directly - use the helpers in `ess.services`.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
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
    short_name: Mapped[str | None] = mapped_column(String(50))
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
    address_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    phone_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    card_number_enc: Mapped[bytes | None] = mapped_column(LargeBinary)

    lookup_bidx: Mapped[bytes | None] = mapped_column(LargeBinary, index=True)
    email_bidx: Mapped[bytes | None] = mapped_column(LargeBinary)
    card_number_bidx: Mapped[bytes | None] = mapped_column(LargeBinary)

    member_since: Mapped[date | None] = mapped_column(Date)
    reduced_fee: Mapped[bool] = mapped_column(Boolean, default=False)
    expelled_at: Mapped[date | None] = mapped_column(Date)
    expelled_reason: Mapped[str | None] = mapped_column(Text)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="member")

    __table_args__ = (
        Index("uq_members_email_bidx", "email_bidx", unique=True, postgresql_where=text("email_bidx IS NOT NULL")),
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
