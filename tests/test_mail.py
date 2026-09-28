"""Outgoing e-mail: message building and the test e-mail in settings."""

import pytest

from ess.mail import Mail, MemoryMailer, SmtpMailer, get_mailer
from tests.test_web_admin import client, csrf, google, login  # noqa: F401  (fixtures and helpers)


def test_message_has_text_and_html_parts():
    mailer = SmtpMailer("smtp.example.org", 465, "ess@sss.sk", "pw", "SSS <ess@sss.sk>")
    msg = mailer._message(Mail(to="a@example.org", subject="Predmet – ž", text="Text", html="<p>HTML</p>"))
    assert msg["From"] == "SSS <ess@sss.sk>" and msg["To"] == "a@example.org"
    assert msg["Message-ID"].endswith("@sss.sk>") and msg["Date"]
    assert [p.get_content_type() for p in msg.iter_parts()] == ["text/plain", "text/html"]


def test_mailer_not_configured_without_password(monkeypatch):
    from ess.config import get_settings

    monkeypatch.delenv("ESS_SMTP_PASSWORD", raising=False)
    get_settings.cache_clear()
    assert get_mailer() is None


@pytest.mark.db
def test_test_mail_from_settings(client, google, migrated_db):
    memory = MemoryMailer()
    client.app.dependency_overrides[get_mailer] = lambda: memory
    login(client, google)
    page = client.post("/admin/settings/test-mail", data={"csrf_token": csrf(client), "to": "admin@example.org"}).text
    assert [m.to for m in memory.sent] == ["admin@example.org"]
    assert "Testovací e-mail bol odoslaný." in page

    client.post("/admin/settings/test-mail", data={"csrf_token": csrf(client), "to": "a@b.org\r\nBcc: x@y.org"})
    assert len(memory.sent) == 1


@pytest.mark.db
def test_test_mail_only_for_system_admin(client, google, migrated_db):
    from ess.services import admin_access
    from ess.services.access import SYSTEM
    from ess.models import AdminRole

    with migrated_db() as s:
        admin_access.grant_access(s, SYSTEM, "plain@example.org", "Plain", AdminRole.ADMIN)
        s.commit()
    memory = MemoryMailer()
    client.app.dependency_overrides[get_mailer] = lambda: memory
    login(client, google, email="plain@example.org")
    response = client.post("/admin/settings/test-mail", data={"csrf_token": csrf(client), "to": "a@example.org"})
    assert response.status_code == 403 and memory.sent == []


def test_smtp_check_describes_password_without_revealing_it():
    from ess.tools.smtp_check import describe, fingerprint

    text = describe(" tajné%41 ")
    assert "tajné" not in text and "length 10" in text
    assert "whitespace" in text and "non-ASCII" in text and "URL-encoded" in text
    assert fingerprint("a") == fingerprint("a") != fingerprint("b")
