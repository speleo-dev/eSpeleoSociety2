"""Notifications to the eCP (R41): an administrator writes a message for the whole SSS; it goes to the
Google Wallet pass of every member with an active eCP who agreed to notifications.

The deliveries are created at once and sent in batches after commits (like eCP content), because
~1 000 Wallet calls do not fit into one request. Google allows at most 3 notifications a day per pass.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ess import audit
from ess.models import Consent, EcpNotification, EcpNotificationDelivery, EcpPass, EcpPassState
from ess.services.access import Actor, DomainError, require_staff
from ess.wallet import WalletClient, WalletError

log = logging.getLogger(__name__)

DAILY_LIMIT = 3  # Google Wallet: notifications per pass in 24 hours
BATCH = 50
MAX_ATTEMPTS = 5


def _now() -> datetime:
    return datetime.now(UTC)


def consenting_member_ids(session: Session) -> set[uuid.UUID]:
    """Members whose newest "notifications" consent is granted."""
    latest: dict[uuid.UUID, bool] = {}
    for member_id, granted in session.execute(select(Consent.member_id, Consent.granted).where(
            Consent.kind == "notifications").order_by(Consent.created_at)):
        latest[member_id] = granted
    return {m for m, granted in latest.items() if granted}


def recipients(session: Session) -> list[EcpPass]:
    consenting = consenting_member_ids(session)
    return [p for p in session.scalars(select(EcpPass).where(EcpPass.state == EcpPassState.ACTIVE.value))
            if p.member_id in consenting]


def sent_last_day(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(EcpNotification).where(
        EcpNotification.created_at > _now() - timedelta(days=1))) or 0


def send(session: Session, actor: Actor, header: str, body: str) -> EcpNotification:
    require_staff(actor)
    header, body = " ".join(header.split()), body.strip()
    if not header or not body:
        raise DomainError("notification_required")
    if len(header) > 100 or len(body) > 500:
        raise DomainError("notification_too_long")
    if sent_last_day(session) >= DAILY_LIMIT:
        raise DomainError("notification_limit")
    passes = recipients(session)
    notification = EcpNotification(id=uuid.uuid4(), header=header, body=body, created_by=actor.id,
                                   recipients=len(passes))
    session.add(notification)
    session.flush()
    for ecp_pass in passes:
        session.add(EcpNotificationDelivery(id=uuid.uuid4(), notification_id=notification.id, pass_id=ecp_pass.id))
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="ecp_notification.send",
                 entity_type="ecp_notification", entity_id=str(notification.id), details={"recipients": len(passes)})
    return notification


def _waiting():
    return select(EcpNotificationDelivery).where(EcpNotificationDelivery.sent_at.is_(None),
                                                 EcpNotificationDelivery.failed_at.is_(None))


def pending_count(session: Session) -> int:
    return session.scalar(_waiting().with_only_columns(func.count())) or 0


def has_pending(session: Session) -> bool:
    return session.scalar(_waiting().with_only_columns(EcpNotificationDelivery.id).limit(1)) is not None


def push_pending(session: Session, wallet: WalletClient, limit: int = BATCH) -> int:
    """Send waiting notifications; commits each one. A pass that keeps failing is given up after 5 attempts."""
    done = 0
    rows = session.execute(_waiting().add_columns(EcpNotification, EcpPass)
                           .join(EcpNotification, EcpNotification.id == EcpNotificationDelivery.notification_id)
                           .join(EcpPass, EcpPass.id == EcpNotificationDelivery.pass_id)
                           .order_by(EcpNotification.created_at).limit(limit)).all()
    for delivery, notification, ecp_pass in rows:
        if ecp_pass.state != EcpPassState.ACTIVE.value:
            delivery.failed_at = _now()  # the pass is no longer active
        else:
            try:
                wallet.add_message(ecp_pass.wallet_object_id, f"n{notification.id.hex}", notification.header,
                                   notification.body)
                delivery.sent_at = _now()
                done += 1
            except WalletError:
                log.warning("eCP notification not delivered; will retry")
                delivery.attempts += 1
                if delivery.attempts >= MAX_ATTEMPTS:
                    delivery.failed_at = _now()
        session.commit()
    return done


@dataclass
class NotificationRow:
    notification: EcpNotification
    sent: int
    failed: int


def history(session: Session, limit: int = 50) -> list[NotificationRow]:
    counts = {nid: (sent, failed) for nid, sent, failed in session.execute(
        select(EcpNotificationDelivery.notification_id,
               func.count(EcpNotificationDelivery.sent_at), func.count(EcpNotificationDelivery.failed_at))
        .group_by(EcpNotificationDelivery.notification_id))}
    items = session.scalars(select(EcpNotification).order_by(EcpNotification.created_at.desc()).limit(limit)).all()
    return [NotificationRow(n, *counts.get(n.id, (0, 0))) for n in items]
