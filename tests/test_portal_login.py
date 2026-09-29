"""Member portal login (R38): eCP link, e-mail code bound to the browser, 90-day session, active eCP only."""

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
