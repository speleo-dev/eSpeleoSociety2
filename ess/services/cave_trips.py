"""Cave trip reports (R41): the member says where they go, with whom and when they plan to be out.

Without "Som vonku": 30 minutes after the planned return the member gets a reminder e-mail, 30 minutes
later the chair of the member's primary club gets an alert e-mail; without a chair (or the chair's
e-mail) it goes to the address from the setting `cave_alert_email`. The alert also opens a task for the
administrator. `check` runs every few minutes (Cloud Scheduler calls /internal/tick) and sends the
e-mails itself: a reminder or alert is marked as sent only after it was really sent, otherwise the next
run tries again. This is a help, not a guarantee: members must still leave word with someone outside.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess import audit
from ess.mail import is_valid_address
from ess.models import CaveTrip, Club, Member, Membership, TaskStatus, TaskType
from ess.security import pii
from ess.services import delegations, members, outbox, settings, tasks
from ess.services.access import SYSTEM, DomainError

REMINDER_AFTER = timedelta(minutes=30)
ALERT_AFTER = timedelta(minutes=60)  # after the planned return (30 min after the reminder)
MAX_TRIP = timedelta(days=14)
_CTX = "cave_trips."


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class TripView:
    trip: CaveTrip
    cave: str
    companions: str


def _view(trip: CaveTrip) -> TripView:
    return TripView(trip, pii.decrypt(trip.cave_enc, _CTX + "cave") or "",
                    pii.decrypt(trip.companions_enc, _CTX + "companions") or "")


def open_trip(session: Session, member_id: uuid.UUID) -> TripView | None:
    trip = session.scalar(select(CaveTrip).where(CaveTrip.member_id == member_id, CaveTrip.returned_at.is_(None)))
    return _view(trip) if trip else None


def start(session: Session, member_id: uuid.UUID, cave: str, companions: str, planned_return_at: datetime) -> CaveTrip:
    cave, companions = " ".join(cave.split()), " ".join(companions.split())
    if not cave:
        raise DomainError("cave_required")
    now = _now()
    if planned_return_at <= now or planned_return_at > now + MAX_TRIP:
        raise DomainError("invalid_return_time")
    if open_trip(session, member_id) is not None:
        raise DomainError("trip_already_open")
    trip = CaveTrip(id=uuid.uuid4(), member_id=member_id, cave_enc=pii.encrypt(cave[:200], _CTX + "cave"),
                    companions_enc=pii.encrypt(companions[:500], _CTX + "companions"),
                    planned_return_at=planned_return_at)
    session.add(trip)
    audit.record(session, actor_type="member", actor_id=str(member_id), action="cave_trip.start",
                 entity_type="cave_trip", entity_id=str(trip.id))
    return trip


def extend(session: Session, member_id: uuid.UUID, planned_return_at: datetime) -> None:
    """A later return; the reminders start over."""
    view = open_trip(session, member_id)
    if view is None:
        raise DomainError("trip_not_open")
    if planned_return_at <= _now() or planned_return_at > _now() + MAX_TRIP:
        raise DomainError("invalid_return_time")
    trip = view.trip
    # Reminder and alert start over: after a later return the chair is alerted again if needed.
    trip.planned_return_at, trip.reminder_sent_at, trip.alert_sent_at = planned_return_at, None, None
    _close_alert_task(session, member_id, "extended")
    audit.record(session, actor_type="member", actor_id=str(member_id), action="cave_trip.extend",
                 entity_type="cave_trip", entity_id=str(trip.id))


def finish(session: Session, member_id: uuid.UUID) -> None:
    """ "Som vonku". """
    view = open_trip(session, member_id)
    if view is None:
        raise DomainError("trip_not_open")
    view.trip.returned_at = _now()
    _close_alert_task(session, member_id, "returned")
    audit.record(session, actor_type="member", actor_id=str(member_id), action="cave_trip.finish",
                 entity_type="cave_trip", entity_id=str(view.trip.id))


def _close_alert_task(session: Session, member_id: uuid.UUID, resolution: str) -> None:
    tasks.close_tasks(session, SYSTEM, TaskType.CAVE_ALERT, TaskStatus.DONE, resolution, member_id=member_id)


def _chair_of_primary_club(session: Session, member_id: uuid.UUID) -> tuple[Member | None, Club | None]:
    club = session.scalar(select(Club).join(Membership, Membership.club_id == Club.id).where(
        Membership.member_id == member_id, Membership.valid_to.is_(None), Membership.is_primary))
    if club is None or club.is_unaffiliated:
        return None, club
    chair_id = delegations.current_chair_id(session, club.id)
    return (session.get(Member, chair_id) if chair_id else None), club


@dataclass
class CheckResult:
    reminders: int = 0
    alerts: int = 0
    no_chair: int = 0  # alerts sent to the fallback address (no chair or no chair e-mail)
    failed: int = 0  # reminders or alerts that could not be sent now; tried again next run


Deliver = Callable[[outbox.QueuedMail], bool]  # sends one e-mail now; False when it was not sent


def check(session: Session, deliver: Deliver, now: datetime | None = None) -> CheckResult:
    now = now or _now()
    result = CheckResult()
    trips = session.scalars(select(CaveTrip).where(CaveTrip.returned_at.is_(None),
                                                   CaveTrip.planned_return_at <= now - REMINDER_AFTER)).all()
    fallback = (settings.get_setting(session, "cave_alert_email") or "").strip()
    for trip in trips:
        view = _view(trip)
        member = members.read_member(session.get(Member, trip.member_id))
        context = {"first_name": member.first_name, "full_name": member.full_name(), "phone": member.phone or "",
                   "cave": view.cave, "companions": view.companions, "planned": trip.planned_return_at,
                   "link_path": "/portal"}
        if trip.reminder_sent_at is None:
            sent = not is_valid_address(member.email) or deliver(outbox.QueuedMail(
                to=member.email, subject="Ste už vonku z jaskyne?", template="cave_reminder", context=context))
            if sent:
                trip.reminder_sent_at = now
                result.reminders += 1
            else:
                result.failed += 1
        if trip.alert_sent_at is None and trip.planned_return_at <= now - ALERT_AFTER:
            _alert(session, trip, member, context, fallback, deliver, now, result)
    return result


def _alert(session, trip, member, context, fallback, deliver, now, result) -> None:
    chair, club = _chair_of_primary_club(session, trip.member_id)
    chair_data = members.read_member(chair) if chair else None
    # The administrator sees it in Požiadavky even when no e-mail can be sent (opened once per trip).
    tasks.open_task(session, SYSTEM, TaskType.CAVE_ALERT, trip.member_id, club_id=club.id if club else None,
                    context={"trip_id": str(trip.id)})
    to_chair = chair_data is not None and is_valid_address(chair_data.email)
    to = chair_data.email if to_chair else fallback
    if not is_valid_address(to):
        result.failed += 1  # nobody to send to: the task stays; tried again when an address is set
        return
    sent = deliver(outbox.QueuedMail(
        to=to, subject=f"Člen sa nevrátil z jaskyne: {member.full_name()}", template="cave_alert",
        context={**context, "chair_name": chair_data.first_name if to_chair else "",
                 "club": club.name if club else "", "fallback": not to_chair}))
    if not sent:
        result.failed += 1
        return
    trip.alert_sent_at = now
    result.alerts += 1
    if not to_chair:
        result.no_chair += 1
    audit.record(session, actor_type="system", actor_id="system", action="cave_trip.alert",
                 entity_type="cave_trip", entity_id=str(trip.id), details={"chair": to_chair})
