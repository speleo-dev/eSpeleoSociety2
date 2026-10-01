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
