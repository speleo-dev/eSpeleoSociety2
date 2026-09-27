"""Audit log: who changed what and when.

Records are written in the same transaction as the change they describe, so a change is never
committed without its audit entry. `details` must never contain personal data - only identifiers
and names of changed fields.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from ess.db import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_type: Mapped[str] = mapped_column(String(20))  # admin | member | system | public
    actor_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))  # e.g. member.create, membership.activate
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
        Index("ix_audit_log_occurred_at", "occurred_at"),
    )


def record(
    session: Session,
    *,
    actor_type: str,
    actor_id: str | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict | None = None,
    request_id: str | None = None,
) -> AuditLog:
    """Add an audit entry to the current transaction (committed together with the change)."""
    entry = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        request_id=request_id,
    )
    session.add(entry)
    return entry
