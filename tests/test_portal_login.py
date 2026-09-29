"""Member portal login (R38): eCP link, e-mail code bound to the browser, 90-day session, active eCP only."""

import json
import re

import pytest
from sqlalchemy import select

from ess.mail import MemoryMailer, get_mailer
from ess.models import EcpPass, MemberLoginCode, MembershipStatus
from ess.services import memberships, outbox, portal_auth
from ess.services.access import SYSTEM, Actor, DomainError, PermissionDenied
from tests.test_ecp_verification import _issued
from tests.test_web_admin import client, csrf, google, login  # noqa: F401 (fixtures)

pytestmark = pytest.mark.db


def _code(session) -> str:
    [mail] = outbox.take(session)
    assert mail.template == "portal_code"
    return mail.context["code"]


def test_new_pass_has_portal_link(session):
    wallet, ecp_pass, _ = _issued(session)
    links = {u["id"]: u["uri"] for u in wallet.objects[ecp_pass.wallet_object_id]["linksModuleData"]["uris"]}
    assert ecp_pass.portal_key and links["portal"] == f"https://ess/p/{ecp_pass.portal_key}"


def test_code_login_bound_to_browser(session):
    _, ecp_pass, member_id = _issued(session)
    key = ecp_pass.portal_key
    portal_auth.send_code(session, key, "browser-a")
    code = _code(session)
    row = session.scalar(select(MemberLoginCode))
    assert code.encode() not in row.code_hash and len(code) == 6

    assert portal_auth.verify_code(session, key, "browser-b", code) == "code_expired"  # another browser
    wrong = "000000" if code != "000000" else "111111"
    assert portal_auth.verify_code(session, key, "browser-a", wrong) == "code_wrong"
    new = portal_auth.verify_code(session, key, "browser-a", code[:3] + " " + code[3:])
    assert new.member_id == member_id and portal_auth.current_member(session, new.token).id == member_id
    assert portal_auth.verify_code(session, key, "browser-a", code) == "code_expired"  # used once

    portal_auth.log_out(session, new.token)
    assert portal_auth.current_member(session, new.token) is None


def test_attempts_and_rate_limit(session):
    _, ecp_pass, _ = _issued(session)
    key = ecp_pass.portal_key
    portal_auth.send_code(session, key, "b")
    code = _code(session)
    wrong = "000000" if code != "000000" else "111111"
    results = [portal_auth.verify_code(session, key, "b", wrong) for _ in range(5)]
    assert results[-1] == "code_expired" and portal_auth.verify_code(session, key, "b", code) == "code_expired"
    for _ in range(4):
        portal_auth.send_code(session, key, "b")
    with pytest.raises(DomainError) as exc:
        portal_auth.send_code(session, key, "b")
    assert exc.value.code == "too_many_codes"


def test_only_active_ecp(session):
    _, ecp_pass, member_id = _issued(session)
    portal_auth.send_code(session, ecp_pass.portal_key, "b")
    new = portal_auth.verify_code(session, ecp_pass.portal_key, "b", _code(session))
    ms = memberships.open_memberships(session, member_id)[0]
    memberships.change_status(session, SYSTEM, ms.id, MembershipStatus.SUSPENDED)
    session.flush()
    assert ecp_pass.state == "inactive"
    assert portal_auth.current_member(session, new.token) is None and portal_auth.pass_for_key(session, ecp_pass.portal_key) is None
    with pytest.raises(DomainError):
        portal_auth.send_code(session, ecp_pass.portal_key, "b")
    memberships.change_status(session, SYSTEM, memberships.open_memberships(session, member_id)[0].id,
                              MembershipStatus.MEMBER)
    session.flush()
    assert portal_auth.current_member(session, new.token).id == member_id  # access returns with the membership


def test_admin_logs_member_out_everywhere(session):
    _, ecp_pass, member_id = _issued(session)
    portal_auth.send_code(session, ecp_pass.portal_key, "b")
    new = portal_auth.verify_code(session, ecp_pass.portal_key, "b", _code(session))
    assert portal_auth.active_sessions(session, member_id) == 1
    with pytest.raises(PermissionDenied):
        portal_auth.log_out_everywhere(session, Actor(kind="member", id=str(member_id)), member_id)
    assert portal_auth.log_out_everywhere(session, SYSTEM, member_id) == 1
    assert portal_auth.current_member(session, new.token) is None


def test_web_login_flow(migrated_db, client):
    mailer = MemoryMailer()
    client.app.dependency_overrides[get_mailer] = lambda: mailer
    with migrated_db() as session:
        _, ecp_pass, _ = _issued(session)
        session.commit()
        key = ecp_pass.portal_key
    assert client.get("/p/neexistuje").status_code == 404
    assert client.get("/portal").status_code == 401
    page = client.get(f"/p/{key}").text
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    r = client.post(f"/p/{key}/code", data={"csrf_token": token})
    assert "Zadajte kód z e-mailu" in r.text
    code = re.search(r"je: (\d{6})", mailer.sent[0].text).group(1)
    r = client.post(f"/p/{key}/code/verify", data={"csrf_token": token, "code": "12345x"})
    assert r.status_code == 400 and "Nesprávny kód" in r.text
    r = client.post(f"/p/{key}/code/verify", data={"csrf_token": token, "code": code}, follow_redirects=False)
    cookie = r.headers["set-cookie"]
    assert r.headers["location"] == "/portal" and "ess_member=" in cookie and "HttpOnly" in cookie
    assert "Max-Age=7776000" in cookie  # 90 days
    home = client.get("/portal").text
    assert "Ján Žiadateľ" in home and "JS Žiadosť (primárna)" in home
    assert client.get(f"/p/{key}", follow_redirects=False).headers["location"] == "/portal"
    r = client.post("/portal/logout", data={"csrf_token": token})
    assert "Boli ste odhlásený" in r.text and client.get("/portal").status_code == 401


def _login(session, key, browser, device):
    portal_auth.send_code(session, key, browser)
    return portal_auth.verify_code(session, key, browser, _code(session), device)


def test_at_most_two_devices(session):
    from ess.services import passkeys, settings
    from tests.soft_authenticator import SoftAuthenticator

    _, ecp_pass, member_id = _issued(session)
    key = ecp_pass.portal_key
    phone = _login(session, key, "a", "Chrome, Android")
    laptop = _login(session, key, "b", "Firefox, Windows")
    device = SoftAuthenticator("https://ess.example.org", "ess.example.org")
    member = session.get(passkeys.Member, member_id)
    options, challenge = passkeys.registration_options(session, member, "https://ess.example.org")
    passkeys.register(session, member, json.dumps(device.create(options)), challenge, "https://ess.example.org",
                      session_id=phone.session_id)

    third = _login(session, key, "c", "Safari, iPhone")
    assert isinstance(third, portal_auth.TooManyDevices)
    assert [d.device for d in third.devices] == ["Chrome, Android", "Firefox, Windows"]
    with pytest.raises(DomainError):  # only one's own device
        portal_auth.open_session(session, member_id, "email_code", "Safari, iPhone", replace=ecp_pass.id)
    new = portal_auth.open_session(session, member_id, "email_code", "Safari, iPhone", replace=phone.session_id)
    assert portal_auth.current_member(session, phone.token) is None and portal_auth.current_member(session, new.token)
    assert passkeys.count(session, member_id) == 0  # the phone's passkey went with it
    assert portal_auth.current_member(session, laptop.token).id == member_id

    settings.set_setting(session, SYSTEM, "portal_max_devices", "3")
    assert not isinstance(_login(session, key, "d", "Edge, Windows"), portal_auth.TooManyDevices)
    portal_auth.log_out_device(session, member_id, laptop.session_id)
    assert portal_auth.current_member(session, laptop.token) is None


def test_web_choose_device_to_log_out(migrated_db, client):
    from ess.services import settings

    mailer = MemoryMailer()
    client.app.dependency_overrides[get_mailer] = lambda: mailer
    with migrated_db() as session:
        _, ecp_pass, member_id = _issued(session)
        settings.set_setting(session, SYSTEM, "portal_max_devices", "1")
        other = portal_auth.open_session(session, member_id, "email_code", "Chrome, Android")
        session.commit()
        key = ecp_pass.portal_key
    page = client.get(f"/p/{key}").text
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    client.post(f"/p/{key}/code", data={"csrf_token": token})
    code = re.search(r"je: (\d{6})", mailer.sent[0].text).group(1)
    r = client.post(f"/p/{key}/code/verify", data={"csrf_token": token, "code": code},
                    headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0) Firefox/130.0"})
    assert "Chrome, Android" in r.text and "Odhlásiť toto zariadenie" in r.text
    assert client.get("/portal").status_code == 401
    r = client.post("/portal/devices/choose", data={"csrf_token": token, "device_id": str(other.session_id)},
                    headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0) Firefox/130.0"})
    assert "Firefox, Windows" in r.text and "(toto zariadenie)" in r.text
