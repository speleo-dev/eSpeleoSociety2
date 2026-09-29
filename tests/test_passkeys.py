"""Passkeys on the member portal (R38): register after a code login, log in with or without the eCP link."""

import json
import re

import pytest

from ess.mail import MemoryMailer, get_mailer
from ess.models import MembershipStatus
from ess.services import memberships, passkeys, portal_auth
from ess.services.access import SYSTEM
from tests.soft_authenticator import SoftAuthenticator
from tests.test_ecp_verification import _issued
from tests.test_web_admin import client  # noqa: F401 (fixture)

pytestmark = pytest.mark.db
BASE = "https://ess.example.org"


def test_register_and_log_in(session):
    _, ecp_pass, member_id = _issued(session)
    member = session.get(passkeys.Member, member_id)
    device = SoftAuthenticator("https://ess.example.org", "ess.example.org")
    options, challenge = passkeys.registration_options(session, member, BASE)
    assert json.loads(options)["authenticatorSelection"]["residentKey"] == "required"
    passkeys.register(session, member, json.dumps(device.create(options)), challenge, BASE)
    assert passkeys.count(session, member_id) == 1

    options, challenge = passkeys.authentication_options(session, BASE, ecp_pass.portal_key)
    assert len(json.loads(options)["allowCredentials"]) == 1
    new = passkeys.authenticate(session, json.dumps(device.get(options)), challenge, BASE)
    assert portal_auth.current_member(session, new.token).id == member_id

    options, challenge = passkeys.authentication_options(session, BASE)  # without the link: any saved passkey
    assert json.loads(options)["allowCredentials"] == []
    assert not isinstance(passkeys.authenticate(session, json.dumps(device.get(options)), challenge, BASE), str)
    # a replayed answer or another site does not work
    answer = device.get(options)
    assert passkeys.authenticate(session, json.dumps(answer), b"other-challenge", BASE) == "passkey_failed"
    assert passkeys.authenticate(session, json.dumps(answer), challenge, "https://evil.example.org") == "passkey_failed"


def test_inactive_ecp_and_admin_reset(session):
    _, ecp_pass, member_id = _issued(session)
    member = session.get(passkeys.Member, member_id)
    device = SoftAuthenticator(BASE, "ess.example.org")
    options, challenge = passkeys.registration_options(session, member, BASE)
    passkeys.register(session, member, json.dumps(device.create(options)), challenge, BASE)
    memberships.change_status(session, SYSTEM, memberships.open_memberships(session, member_id)[0].id,
                              MembershipStatus.SUSPENDED)
    session.flush()
    options, challenge = passkeys.authentication_options(session, BASE)
    assert passkeys.authenticate(session, json.dumps(device.get(options)), challenge, BASE) == "portal_not_available"
    portal_auth.log_out_everywhere(session, SYSTEM, member_id)
    assert passkeys.count(session, member_id) == 0


def test_web_passkey_flow(migrated_db, client):
    mailer = MemoryMailer()
    client.app.dependency_overrides[get_mailer] = lambda: mailer
    with migrated_db() as session:
        _, ecp_pass, _ = _issued(session)
        session.commit()
        key = ecp_pass.portal_key
    device = SoftAuthenticator("http://testserver", "testserver")
    page = client.get(f"/p/{key}").text
    assert "data-passkey-login" in page
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    headers = {"X-CSRF-Token": token}
    client.post(f"/p/{key}/code", data={"csrf_token": token})
    code = re.search(r"je: (\d{6})", mailer.sent[0].text).group(1)
    client.post(f"/p/{key}/code/verify", data={"csrf_token": token, "code": code})
    assert "Nastaviť prihlásenie odtlačkom" in client.get("/portal").text

    assert client.post("/portal/passkey/register-options", json={}).status_code == 400  # CSRF header missing
    options = client.post("/portal/passkey/register-options", json={}, headers=headers).text
    r = client.post("/portal/passkey/register", json={"credential": device.create(options)}, headers=headers)
    assert r.json() == {"ok": True}
    client.post("/portal/logout", data={"csrf_token": token})
    assert client.get("/portal").status_code == 401

    options = client.post("/portal/passkey/login-options", json={"key": key}, headers=headers).text
    r = client.post("/portal/passkey/login", json={"credential": device.get(options)}, headers=headers)
    assert r.json()["redirect"] == "/portal" and "ess_member=" in r.headers["set-cookie"]
    home = client.get("/portal").text
    assert "Ján Žiadateľ" in home and "Nastaviť prihlásenie odtlačkom" not in home  # already has a passkey
