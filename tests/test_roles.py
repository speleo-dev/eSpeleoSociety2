"""R50: what the administrator and the superadmin may do."""

import pytest

from ess.models import CertificateType
from ess.services import certificates, clubs, documents, importing
from ess.services.access import Actor, PermissionDenied
from tests.test_ecp_application import _club, _member
from tests.test_web_admin import client, csrf, google, login  # noqa: F401 (fixtures)

pytestmark = pytest.mark.db
ADMIN = Actor(kind="admin", id="admin-1")
SUPER = Actor(kind="system_admin", id="super-1")


def test_superadmin_runs_the_system_but_not_the_register(session):
    with pytest.raises(PermissionDenied):
        clubs.create_club(session, SUPER, "JS Nová", "", True)
    cert_type = certificates.add_certificate_type(session, SUPER, "diver", "Potápač")
    certificates.deactivate_certificate_type(session, ADMIN, cert_type.id)
    assert not session.get(CertificateType, cert_type.id).active
    documents.save_document(session, SUPER, "Stanovy", "https://example.org/s.pdf", None)
    result = importing.import_clubs(session, SUPER, "kod;nazov\nJS-X;JS Importovaná\n".encode(), dry_run=False)
    assert result.ok


def test_superadmin_sees_member_limited(migrated_db, google, client):  # noqa: F811
    with migrated_db() as s:
        member_id = _member(s, _club(s))
        s.commit()
    login(client, google, email="super@example.org")
    page = client.get(f"/admin/members/{member_id}").text
    assert "Upraviť údaje" not in page and "Dátum narodenia" not in page and "Priradiť funkciu" in page
    assert "Predseda SSS" in page  # the SSS board positions are offered to the superadmin
    login(client, google)  # administrator
    page = client.get(f"/admin/members/{member_id}").text
    assert "Upraviť údaje" in page and "Predseda SSS" not in page and "Predseda skupiny" in page


# --- administrator signing in with the eCP (R51) -----------------------------------------------------


def test_member_with_admin_role_opens_administration_via_ecp(migrated_db, google, client):  # noqa: F811
    from ess.models import EcpPass
    from ess.services import admin_access, portal_auth
    from ess.services.access import SYSTEM

    with migrated_db() as s:
        club_id = _club(s)
        member_id = _member(s, club_id)
        s.add(EcpPass(member_id=member_id, wallet_object_id=f"i.{member_id}", state="active"))
        token = portal_auth.open_session(s, member_id, "email_code").token
        s.commit()
    client.cookies.set("ess_member", token)
    assert client.get("/admin").status_code == 401  # a member without the role

    login(client, google, email="super@example.org")
    page = client.get(f"/admin/members/{member_id}").text
    assert "Udeliť prístup administrátora" in page
    r = client.post(f"/admin/members/{member_id}/admin-access", data={"csrf_token": csrf(client)})
    assert "Prístup administrátora bol udelený" in r.text and "Odobrať prístup" in r.text
    assert "eCP" in client.get("/admin/access").text
    client.post("/admin/logout", data={"csrf_token": csrf(client)})

    client.cookies.set("ess_member", token)
    page = client.get("/admin")
    assert page.status_code == 200 and "Môj portál (eCP)" in page.text and 'action="/portal/logout"' in page.text
    assert client.get("/admin/payments").status_code == 200  # an administrator of the register
    assert client.get("/admin/access").status_code == 403

    with migrated_db() as s:
        admin_access.revoke_access(s, SYSTEM, admin_access.member_access(s, member_id).id)
        s.commit()
    assert client.get("/admin").status_code == 401  # revoked: no access at once


def test_admin_role_badge(client, google):  # noqa: F811
    login(client, google)
    assert 'role-badge role-admin">Administrátor<' in client.get("/admin").text
    login(client, google, email="super@example.org")
    assert 'role-badge role-system_admin">Superadmin<' in client.get("/admin").text


# --- R53: devices, switching roles, link for a computer ---------------------------------------------------


def test_superadmin_logs_member_out_and_switches_to_ecp_admin(migrated_db, google, client):  # noqa: F811
    from ess.mail import MemoryMailer, get_mailer
    from ess.models import EcpPass
    from ess.services import admin_access, portal_auth
    from ess.services.access import SYSTEM

    mailer = MemoryMailer()
    client.app.dependency_overrides[get_mailer] = lambda: mailer
    with migrated_db() as s:
        member_id = _member(s, _club(s))
        s.add(EcpPass(member_id=member_id, wallet_object_id=f"i.{member_id}", state="active", portal_key="k" * 32))
        token = portal_auth.open_session(s, member_id, "email_code").token
        portal_auth.open_session(s, member_id, "email_code")  # another device
        admin_access.grant_member_access(s, SYSTEM, member_id)
        s.commit()

    client.cookies.set("ess_member", token)
    page = client.get("/portal").text
    assert 'href="/admin/ecp"' in page and "Poslať si odkaz na prihlásenie na počítači" in page
    csrf_portal = __import__("re").search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    r = client.post("/portal/send-link", data={"csrf_token": csrf_portal})
    assert "Odkaz na prihlásenie sme poslali" in r.text
    assert mailer.sent[-1].subject.startswith("Prihlásenie do portálu") and "/p/" + "k" * 32 in mailer.sent[-1].text

    login(client, google, email="super@example.org")  # Google session wins …
    page = client.get("/admin").text
    assert "Superadmin" in page and 'href="/admin/ecp"' in page
    r = client.get("/admin/ecp")  # … until the member switches to the eCP administrator
    assert 'role-badge role-admin">Administrátor<' in r.text

    login(client, google, email="super@example.org")
    page = client.get(f"/admin/members/{member_id}").text
    assert "prihlásený na 2 zariadení" in page.lower() or "Prihlásený na 2 zariadení" in page
    r = client.post(f"/admin/members/{member_id}/portal-logout", data={"csrf_token": csrf(client)})
    assert r.status_code == 200
    with migrated_db() as s:
        assert portal_auth.active_sessions(s, member_id) == 0


def test_member_list_icons_by_role(migrated_db, google, client):  # noqa: F811
    from ess.models import EcpPass

    with migrated_db() as s:
        member_id = _member(s, _club(s), reduced_fee=True)
        s.add(EcpPass(member_id=member_id, wallet_object_id=f"i.{member_id}", state="active"))
        s.commit()
    login(client, google)
    page = client.get("/admin/members").text
    assert 'title="vydaný eCP (Google Wallet)"' in page and 'title="zľavnené členské"' in page
    login(client, google, email="super@example.org")
    page = client.get("/admin/members").text
    assert "vydaný eCP" not in page and "zľavnené členské" not in page and 'title="člen"' in page
