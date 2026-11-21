"""Cave trip reports (R41): reminder to the member after 30 min, alert to the chair after 60 min."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from ess.models import CaveTrip
from ess.services import cave_trips, portal_auth, positions
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


class Outbox:
    """Delivery used by `check`: records the e-mails; `fail` simulates an SMTP outage."""

    def __init__(self):
        self.sent, self.fail = [], False

    def __call__(self, mail) -> bool:
        if self.fail:
            return False
        self.sent.append(mail)
        return True

    def take(self):
        sent, self.sent = self.sent, []
        return sent


def _open_task(session, member_id):
    from ess.models import Task

    return session.scalar(select(Task).where(Task.member_id == member_id, Task.task_type == "cave_alert",
                                             Task.status == "open"))


def test_reminder_then_chair_alert(session):
    caver = _setup(session)
    box = Outbox()
    with pytest.raises(DomainError):
        cave_trips.start(session, caver, "Jaskyňa", "", NOW - timedelta(minutes=1))  # return in the past
    trip = cave_trips.start(session, caver, "Demänovská jaskyňa slobody", "Peter, Eva", NOW + timedelta(hours=3))
    assert b"Dem" not in trip.cave_enc
    with pytest.raises(DomainError):
        cave_trips.start(session, caver, "Iná", "", NOW + timedelta(hours=1))  # one open trip
    session.flush()
    planned = trip.planned_return_at

    assert cave_trips.check(session, box, planned + timedelta(minutes=29)).reminders == 0
    assert cave_trips.check(session, box, planned + timedelta(minutes=31)).reminders == 1
    [mail] = box.take()
    assert mail.to == "jaskyniar@example.org" and mail.template == "cave_reminder"
    assert cave_trips.check(session, box, planned + timedelta(minutes=40)).reminders == 0  # only once
    assert box.take() == []

    result = cave_trips.check(session, box, planned + timedelta(minutes=61))
    assert result.alerts == 1
    [alert] = box.take()
    assert alert.to == "predseda@example.org" and alert.context["cave"] == "Demänovská jaskyňa slobody"
    assert alert.context["phone"] == "0900 123 456" and not alert.context["fallback"]
    assert _open_task(session, caver) is not None  # the administrator sees it too
    assert cave_trips.check(session, box, planned + timedelta(hours=5)).alerts == 0  # only once
    cave_trips.finish(session, caver)
    assert _open_task(session, caver) is None  # closed by "Som vonku"


def test_failed_sending_is_retried(session):
    caver = _setup(session)
    box = Outbox()
    trip = cave_trips.start(session, caver, "Jaskyňa", "", NOW + timedelta(hours=1))
    session.flush()
    planned = trip.planned_return_at
    box.fail = True  # SMTP down: nothing is marked as sent
    result = cave_trips.check(session, box, planned + timedelta(minutes=65))
    assert result.reminders == 0 and result.alerts == 0 and result.failed == 2
    assert trip.reminder_sent_at is None and trip.alert_sent_at is None
    assert _open_task(session, caver) is not None  # visible to the administrator even without e-mail
    box.fail = False  # the next run sends both
    result = cave_trips.check(session, box, planned + timedelta(minutes=70))
    assert result.reminders == 1 and result.alerts == 1 and len(box.take()) == 2


def test_alert_goes_to_fallback_address_without_chair(session):
    from ess.services import settings

    club_id = _club(session)
    caver = _member(session, club_id, first_name="Jaskyniar", card_number="2", email="jaskyniar@example.org")
    box = Outbox()
    trip = cave_trips.start(session, caver, "Jaskyňa", "", NOW + timedelta(hours=1))
    session.flush()
    planned = trip.planned_return_at
    result = cave_trips.check(session, box, planned + timedelta(minutes=65))  # no chair, no fallback set
    assert result.alerts == 0 and result.failed == 1 and trip.alert_sent_at is None
    box.take()
    settings.set_setting(session, SYSTEM, "cave_alert_email", "zachranari@example.org")
    result = cave_trips.check(session, box, planned + timedelta(minutes=70))
    assert result.alerts == 1 and result.no_chair == 1
    [alert] = box.take()
    assert alert.to == "zachranari@example.org" and alert.context["fallback"]
    with pytest.raises(DomainError):
        settings.set_setting(session, SYSTEM, "cave_alert_email", "a@b.sk, c@d.sk")  # one address only


def test_finish_and_extend(session):
    caver = _setup(session)
    box = Outbox()
    trip = cave_trips.start(session, caver, "Jaskyňa", "", NOW + timedelta(hours=1))
    session.flush()
    cave_trips.check(session, box, trip.planned_return_at + timedelta(minutes=65))
    assert trip.alert_sent_at is not None and len(box.take()) == 2
    cave_trips.extend(session, caver, NOW + timedelta(hours=4))  # reminder and alert start over
    assert trip.reminder_sent_at is None and trip.alert_sent_at is None
    assert _open_task(session, caver) is None
    result = cave_trips.check(session, box, trip.planned_return_at + timedelta(minutes=65))
    assert result.reminders == 1 and result.alerts == 1  # the chair is alerted again after the new time
    cave_trips.finish(session, caver)
    assert cave_trips.open_trip(session, caver) is None
    assert cave_trips.check(session, box, NOW + timedelta(days=1)).reminders == 0
    cave_trips.start(session, caver, "Ďalšia", "", NOW + timedelta(hours=2))  # a new trip is possible


def test_bad_address_does_not_stop_other_mails():
    from ess.mail import Mail, MemoryMailer, is_valid_address
    from ess.web.mailing import send

    assert is_valid_address("jan.novak+js@sub.example.sk")
    for bad in ("a@b.sk, c@d.sk", "a@b.sk\r\nBcc: x@y.sk", "Ján <a@b.sk>", "a b@c.sk", "a@b", ""):
        assert not is_valid_address(bad), bad
    mailer = MemoryMailer()
    assert send(mailer, Mail(to="a@b.sk\nBcc: x@y.sk", subject="x", text="x")) is False
    assert send(mailer, Mail(to="ok@example.org", subject="x", text="x")) is True


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
    mailer.fail = True  # SMTP down: the tick reports it and the next one tries again
    r = client.post("/internal/tick", headers={"x-ess-scheduler-token": "t" * 32})
    assert r.json()["reminders"] == 0 and r.json()["failed"] == 1
    mailer.fail = False
    r = client.post("/internal/tick", headers={"x-ess-scheduler-token": "t" * 32})
    assert r.json()["reminders"] == 1 and mailer.sent[0].subject == "Ste už vonku z jaskyne?"
    assert "/portal" in mailer.sent[0].text
    r = client.post("/portal/cave/finish", data={"csrf_token": token})
    assert "Vitajte späť" in r.text
