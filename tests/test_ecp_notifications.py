"""Notifications to the eCP (R41): administrators only, members with consent, 3 a day, sent in batches."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from ess.models import Consent, EcpPass
from ess.services import ecp_notifications as notifications
from ess.services.access import SYSTEM, Actor, DomainError, PermissionDenied
from ess.wallet import MemoryWalletClient, WalletError
from tests.test_ecp_verification import _issued
from tests.test_web_admin import client, csrf, google, login  # noqa: F401 (fixtures)

pytestmark = pytest.mark.db


def test_send_to_consenting_members(session):
    wallet, ecp_pass, member_id = _issued(session)  # agreed to notifications in the application
    with pytest.raises(PermissionDenied):
        notifications.send(session, Actor(kind="member", id=str(member_id)), "A", "B")
    with pytest.raises(DomainError):
        notifications.send(session, SYSTEM, "A", "x" * 501)
    n = notifications.send(session, SYSTEM, "Speleomíting 2027", "Prihlasovanie je otvorené.")
    assert n.recipients == 1 and notifications.pending_count(session) == 1
    session.commit()
    assert notifications.push_pending(session, wallet) == 1
    [message] = wallet.objects[ecp_pass.wallet_object_id]["messages"]
    assert message["header"] == "Speleomíting 2027" and message["messageType"] == "TEXT_AND_NOTIFY"
    assert notifications.history(session)[0].sent == 1

    session.add(Consent(id=uuid.uuid4(), member_id=member_id, kind="notifications", text_version="x",
                        granted=False, source="portal",
                        created_at=datetime.now(UTC) + timedelta(minutes=1)))  # withdrawn later
    session.flush()
    assert notifications.send(session, SYSTEM, "Ďalšia", "text").recipients == 0


def test_daily_limit_and_retries(session):
    wallet, ecp_pass, _ = _issued(session)
    for i in range(3):
        notifications.send(session, SYSTEM, f"Správa {i}", "text")
    with pytest.raises(DomainError) as exc:
        notifications.send(session, SYSTEM, "Štvrtá", "text")
    assert exc.value.code == "notification_limit"
    session.commit()

    class Broken(MemoryWalletClient):
        def add_message(self, *args):
            raise WalletError("message: HTTP 503")

    for _ in range(4):
        notifications.push_pending(session, Broken())
    assert notifications.pending_count(session) == 3
    notifications.push_pending(session, Broken())  # fifth failure: given up
    assert notifications.pending_count(session) == 0 and notifications.history(session)[0].failed == 1


def test_admin_page(migrated_db, google, client):
    with migrated_db() as session:
        _issued(session)
        session.commit()
    login(client, google)
    page = client.get("/admin/notifications").text
    assert "teraz <strong>1</strong>" in page
    r = client.post("/admin/notifications", data={"csrf_token": csrf(client), "header": "Test", "body": "Ahoj"})
    assert "sa odosiela" in r.text
    with migrated_db() as session:
        assert session.query(EcpPass).count() == 1
