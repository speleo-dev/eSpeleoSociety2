"""Cave trip reports (R41): reminder to the member after 30 min, alert to the chair after 60 min."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from ess.models import CaveTrip
from ess.services import cave_trips, outbox, portal_auth, positions
from ess.services.access import SYSTEM, DomainError
from tests.test_ecp_application import _club, _member
from tests.test_web_admin import client  # noqa: F401 (fixture)

pytestmark = pytest.mark.db
NOW = datetime.now(UTC)


def _setup(session):
    club_id = _club(session)
    chair = _member(session, club_id, first_name="Predseda", card_number="1", email="predseda@example.org")
    positions.assign_position(session, SYSTEM, "club_chair", chair, club_id)
    caver = _member(session, club_id, first_name="Jaskyniar", card_number="2", email="jaskyniar@example.org",
                    phone="0900 123 456")
    return caver


def test_reminder_then_chair_alert(session):
    caver = _setup(session)
    with pytest.raises(DomainError):
        cave_trips.start(session, caver, "Jaskyňa", "", NOW - timedelta(minutes=1))  # return in the past
    trip = cave_trips.start(session, caver, "Demänovská jaskyňa slobody", "Peter, Eva", NOW + timedelta(hours=3))
    assert b"Dem" not in trip.cave_enc
    with pytest.raises(DomainError):
        cave_trips.start(session, caver, "Iná", "", NOW + timedelta(hours=1))  # one open trip
    session.flush()
    planned = trip.planned_return_at

    assert cave_trips.check(session, planned + timedelta(minutes=29)).reminders == 0
    assert cave_trips.check(session, planned + timedelta(minutes=31)).reminders == 1
    [mail] = outbox.take(session)
    assert mail.to == "jaskyniar@example.org" and mail.template == "cave_reminder"
    assert cave_trips.check(session, planned + timedelta(minutes=40)).reminders == 0  # only once
    assert outbox.take(session) == []

    result = cave_trips.check(session, planned + timedelta(minutes=61))
    assert result.alerts == 1
    [alert] = outbox.take(session)
    assert alert.to == "predseda@example.org" and alert.context["cave"] == "Demänovská jaskyňa slobody"
    assert alert.context["phone"] == "0900 123 456"
    assert cave_trips.check(session, planned + timedelta(hours=5)).alerts == 0  # only once


def test_finish_and_extend(session):
    caver = _setup(session)
    trip = cave_trips.start(session, caver, "Jaskyňa", "", NOW + timedelta(hours=1))
    session.flush()
    cave_trips.check(session, trip.planned_return_at + timedelta(minutes=35))
    outbox.take(session)
    cave_trips.extend(session, caver, NOW + timedelta(hours=4))  # reminders start over
    assert trip.reminder_sent_at is None
    cave_trips.finish(session, caver)
    assert cave_trips.open_trip(session, caver) is None
    assert cave_trips.check(session, NOW + timedelta(days=1)).reminders == 0
    cave_trips.start(session, caver, "Ďalšia", "", NOW + timedelta(hours=2))  # a new trip is possible


def test_portal_and_scheduler(migrated_db, client, monkeypatch):
    from ess.config import get_settings
    from ess.mail import MemoryMailer, get_mailer
    from ess.models import EcpPass

    mailer = MemoryMailer()
    client.app.dependency_overrides[get_mailer] = lambda: mailer
    with migrated_db() as session:
        caver = _setup(session)
        session.add(EcpPass(member_id=caver, wallet_object_id="i.x", state="active"))
        login = portal_auth.open_session(session, caver, "email_code")
        session.commit()
    client.cookies.set("ess_member", login.token)
    page = client.get("/portal").text
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    from zoneinfo import ZoneInfo

    local = (datetime.now(ZoneInfo("Europe/Bratislava")) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    r = client.post("/portal/cave", data={"csrf_token": token, "cave": "Ochtinská", "planned_return": local})
    assert "Vstup do jaskyne je nahlásený" in r.text and "Som vonku" in r.text

    assert client.post("/internal/tick").status_code == 404  # no token configured
    monkeypatch.setenv("ESS_SCHEDULER_TOKEN", "t" * 32)
    get_settings.cache_clear()
    assert client.post("/internal/tick", headers={"x-ess-scheduler-token": "wrong"}).status_code == 404
    with migrated_db() as session:  # pretend the planned return was long ago
        trip = session.scalar(select(CaveTrip))
        trip.planned_return_at = datetime.now(UTC) - timedelta(minutes=45)
        session.commit()
    r = client.post("/internal/tick", headers={"x-ess-scheduler-token": "t" * 32})
    assert r.json()["reminders"] == 1 and mailer.sent[0].subject == "Ste už vonku z jaskyne?"
    r = client.post("/portal/cave/finish", data={"csrf_token": token})
    assert "Vitajte späť" in r.text
