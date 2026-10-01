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
