"""Yearly sticker: generation, template check, preview and deployment, hero image of new passes."""

import io
import re
from datetime import date

import pytest
from PIL import Image

from ess.services import sticker
from ess.services.access import SYSTEM, Actor, DomainError, PermissionDenied
from ess.stickers import SIZE, check_template, default_template, generate_sticker
from ess.storage import MemoryMediaStore, get_media_store

YEAR = date.today().year


def test_same_seed_same_sticker_and_colours_differ():
    a = generate_sticker(default_template(), 2027, "#FFFFFF", "transparent", seed=1)
    assert a == generate_sticker(default_template(), 2027, "#FFFFFF", "transparent", seed=1)
    assert a != generate_sticker(default_template(), 2027, "#FFFFFF", "transparent", seed=2)
    with Image.open(io.BytesIO(a)) as img:
        assert img.size == SIZE and img.mode == "RGBA" and img.getpixel((0, 0))[3] == 0  # transparent corner
    with Image.open(io.BytesIO(generate_sticker(default_template(), 2027, "#FFFFFF", "#0B4A46", 1))) as img:
        assert img.getpixel((0, 0)) == (11, 74, 70, 255)


def test_template_check():
    assert check_template(default_template()).startswith(b"\x89PNG")
    out = io.BytesIO()
    Image.new("RGBA", (100, 100)).save(out, format="PNG")
    for bad in (out.getvalue(), b"not an image"):
        with pytest.raises(DomainError):
            check_template(bad)


@pytest.mark.db
def test_deploy_sets_hero_for_new_passes(session):
    store = MemoryMediaStore()
    with pytest.raises(PermissionDenied):
        sticker.deploy(session, Actor(kind="admin", id="a"), store, YEAR, "#FFFFFF", "transparent", 5)
    with pytest.raises(DomainError):
        sticker.deploy(session, SYSTEM, store, YEAR, "white", "transparent", 5)
    url = sticker.deploy(session, SYSTEM, store, YEAR, "#ffffff", "transparent", 5)
    assert url.startswith(store.base_url + "/stickers/") and len(store.objects) == 1
    assert sticker.hero_url(session) == url
    assert sticker.hero_url(session, YEAR + 1) is None  # a sticker for another year is not used

    from ess.models import EcpPass
    from ess.services import ecp_issuance
    from ess.wallet import MemoryWalletClient
    from sqlalchemy import select
    from tests.test_ecp_issuance import ADMIN, _submitted

    wallet = MemoryWalletClient()
    app, _ = _submitted(session, store)
    ecp_issuance.approve(session, ADMIN, app.id, store, wallet, "https://ess")
    obj = wallet.objects[session.scalar(select(EcpPass.wallet_object_id))]
    assert obj["heroImage"]["sourceUri"]["uri"] == url


@pytest.mark.db
def test_web_preview_and_deploy(migrated_db, monkeypatch):
    from fastapi.testclient import TestClient

    from ess.config import get_settings
    from ess.main import create_app
    from ess.web import auth
    from tests.test_web_admin import FakeGoogle

    monkeypatch.setenv("ESS_GOOGLE_CLIENT_ID", "123-test.apps.googleusercontent.com")
    monkeypatch.setenv("ESS_GOOGLE_CLIENT_SECRET", "test-secret")
    get_settings.cache_clear()
    google = FakeGoogle()
    monkeypatch.setattr(auth, "_google", lambda: google)
    store = MemoryMediaStore()
    app = create_app()
    app.dependency_overrides[get_media_store] = lambda: store
    client = TestClient(app)
    google.userinfo = {"email": "super@example.org", "email_verified": True, "name": "Admin"}
    client.get("/admin/auth/callback")
    page = client.get("/admin/settings").text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    page = client.post("/admin/settings/sticker", data={"csrf_token": csrf, "year": YEAR, "text_color": "#ffffff",
                                                        "transparent": "on", "action": "preview"}).text
    assert "data:image/png;base64," in page and store.objects == {}
    seed = re.search(r'name="seed" value="(\d+)"', page).group(1)
    page = client.post("/admin/settings/sticker", data={"csrf_token": csrf, "year": YEAR, "text_color": "#ffffff",
                                                        "transparent": "on", "action": "deploy", "seed": seed}).text
    assert f"Ročná známka na rok {YEAR} je nasadená" in page and len(store.objects) == 1
    [(data, _)] = store.objects.values()
    assert data == generate_sticker(default_template(), YEAR, "#FFFFFF", "transparent", int(seed))  # = preview

    files = {"template": ("t.png", default_template(), "image/png")}
    page = client.post("/admin/settings/sticker/template", data={"csrf_token": csrf}, files=files).text
    assert "Šablóna známky bola nahraná" in page and "nahratá" in page
