"""Cave trip reports (R41): the member says where they go, with whom and when they plan to be out.

Without "Som vonku": 30 minutes after the planned return the member gets a reminder e-mail, 30 minutes
later the chair of the member's primary club gets an alert e-mail. `check` runs every few minutes
(Cloud Scheduler calls /internal/tick). E-mails go through the outbox (sent after commit).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess import audit
from ess.models import CaveTrip, Club, Member, Membership
from ess.security import pii
from ess.services import delegations, members, outbox
from ess.services.access import DomainError

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
    trip.planned_return_at, trip.reminder_sent_at = planned_return_at, None
    audit.record(session, actor_type="member", actor_id=str(member_id), action="cave_trip.extend",
                 entity_type="cave_trip", entity_id=str(trip.id))


def finish(session: Session, member_id: uuid.UUID) -> None:
    """ "Som vonku". """
    view = open_trip(session, member_id)
    if view is None:
        raise DomainError("trip_not_open")
    view.trip.returned_at = _now()
    audit.record(session, actor_type="member", actor_id=str(member_id), action="cave_trip.finish",
                 entity_type="cave_trip", entity_id=str(view.trip.id))


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
    no_chair: int = 0  # alerts that had nobody to go to


def check(session: Session, now: datetime | None = None) -> CheckResult:
    now = now or _now()
    result = CheckResult()
    trips = session.scalars(select(CaveTrip).where(CaveTrip.returned_at.is_(None),
                                                   CaveTrip.planned_return_at <= now - REMINDER_AFTER)).all()
    for trip in trips:
        view = _view(trip)
        member = members.read_member(session.get(Member, trip.member_id))
        context = {"first_name": member.first_name, "full_name": member.full_name(), "phone": member.phone or "",
                   "cave": view.cave, "companions": view.companions, "planned": trip.planned_return_at,
                   "link_path": "/portal"}
        if trip.reminder_sent_at is None:
            trip.reminder_sent_at = now
            result.reminders += 1
            if member.email:
                outbox.queue(session, outbox.QueuedMail(to=member.email, subject="Ste už vonku z jaskyne?",
                                                        template="cave_reminder", context=context))
        elif trip.alert_sent_at is None and trip.planned_return_at <= now - ALERT_AFTER:
            trip.alert_sent_at = now
            chair, club = _chair_of_primary_club(session, trip.member_id)
            chair_data = members.read_member(chair) if chair else None
            if chair_data and chair_data.email:
                result.alerts += 1
                outbox.queue(session, outbox.QueuedMail(
                    to=chair_data.email, subject=f"Člen sa nevrátil z jaskyne: {member.full_name()}",
                    template="cave_alert", context={**context, "chair_name": chair_data.first_name,
                                                    "club": club.name if club else ""}))
            else:
                result.no_chair += 1
            audit.record(session, actor_type="system", actor_id="system", action="cave_trip.alert",
                         entity_type="cave_trip", entity_id=str(trip.id), details={"chair": bool(chair_data)})
    return result
