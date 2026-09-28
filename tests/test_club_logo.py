"""Club logo upload in the administration."""

import pytest
from sqlalchemy import select

from ess.audit import AuditLog
from ess.models import Club
from ess.storage import MemoryMediaStore, get_media_store
from tests.test_admin_forms import _club
from tests.test_images import image_bytes
from tests.test_web_admin import client, csrf, google, login  # noqa: F401  (fixtures and helpers)

pytestmark = pytest.mark.db


@pytest.fixture
def store(client):
    memory = MemoryMediaStore("ess-media-test")
    client.app.dependency_overrides[get_media_store] = lambda: memory
    return memory


def _upload(client, club_id, data, name="logo.png"):
    return client.post(f"/admin/clubs/{club_id}/logo", data={"csrf_token": csrf(client)},
                       files={"logo": (name, data, "image/png")}, follow_redirects=False)


def _logo_url(migrated_db, club_id):
    with migrated_db() as s:
        return s.get(Club, club_id).logo_url


def test_upload_replace_and_remove_logo(client, google, migrated_db, store):
    login(client, google)
    club_id = _club(migrated_db)

    assert _upload(client, club_id, image_bytes()).status_code == 303
    first = _logo_url(migrated_db, club_id)
    assert first.startswith("https://storage.googleapis.com/ess-media-test/clubs/")
    assert list(store.objects) == [store.name_from_url(first)]
    assert first in client.get(f"/admin/clubs/{club_id}").text

    _upload(client, club_id, image_bytes("JPEG"))
    second = _logo_url(migrated_db, club_id)
    assert second != first
    assert list(store.objects) == [store.name_from_url(second)]  # the replaced logo is deleted

    client.post(f"/admin/clubs/{club_id}/logo/remove", data={"csrf_token": csrf(client)})
    assert _logo_url(migrated_db, club_id) is None and store.objects == {}

    with migrated_db() as s:
        actions = s.scalars(select(AuditLog.action).where(AuditLog.entity_id == str(club_id))).all()
    assert actions.count("club.logo_upload") == 2 and "club.logo_remove" in actions


def test_invalid_upload_keeps_old_logo(client, google, migrated_db, store):
    login(client, google)
    club_id = _club(migrated_db)
    _upload(client, club_id, image_bytes())
    before = _logo_url(migrated_db, club_id)

    _upload(client, club_id, b"<svg></svg>", "logo.svg")
    page = client.get(f"/admin/clubs/{club_id}").text
    assert "Súbor nie je podporovaný obrázok" in page
    assert _logo_url(migrated_db, club_id) == before and len(store.objects) == 1


def test_foreign_logo_url_is_not_deleted(client, google, migrated_db, store):
    login(client, google)
    club_id = _club(migrated_db)
    with migrated_db() as s:
        s.get(Club, club_id).logo_url = "https://storage.googleapis.com/sss_sk_bucket/old.png"
        s.commit()
    _upload(client, club_id, image_bytes())
    assert _logo_url(migrated_db, club_id).startswith("https://storage.googleapis.com/ess-media-test/")


def test_upload_without_configured_store(client, google, migrated_db):
    login(client, google)
    club_id = _club(migrated_db)
    _upload(client, club_id, image_bytes())
    assert "Úložisko obrázkov nie je nastavené" in client.get(f"/admin/clubs/{club_id}").text
    assert _logo_url(migrated_db, club_id) is None


def test_upload_requires_csrf(client, google, migrated_db, store):
    login(client, google)
    club_id = _club(migrated_db)
    response = client.post(f"/admin/clubs/{club_id}/logo", files={"logo": ("a.png", image_bytes(), "image/png")},
                           follow_redirects=False)
    assert response.status_code != 303 or "/logo" not in response.headers.get("location", "")
    assert _logo_url(migrated_db, club_id) is None and store.objects == {}
