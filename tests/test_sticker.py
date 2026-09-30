"""Yearly sticker: generation, template check, preview and deployment, hero image of new passes."""

import io
import re
from datetime import date, timedelta

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
def test_publish_locks_sticker_and_opens_payment(session):
    from ess.services import ecp_content, payments, settings

    store = MemoryMediaStore()
    due = sticker.due_year(session)
    assert sticker.edit_year(session) == due
    with pytest.raises(PermissionDenied):
        sticker.publish(session, Actor(kind="member", id="m"), store, due, "#FFFFFF", "transparent", 5)
    with pytest.raises(DomainError, match="sticker_wrong_year"):
        sticker.render(session, SYSTEM, store, due + 1, "#FFFFFF", "transparent", 5)
    with pytest.raises(DomainError):
        sticker.publish(session, SYSTEM, store, due, "white", "transparent", 5)
    with pytest.raises(DomainError, match="sticker_not_published"):
        ecp_content.publish_payment_links(session, SYSTEM)

    url = sticker.publish(session, Actor(kind="admin", id="a"), store, due, "#ffffff", "transparent", 5)
    assert url.startswith(store.base_url + "/stickers/") and len(store.objects) == 1
    assert sticker.hero_url(session, due) == url
    assert sticker.hero_url(session, due + 1) is None  # a sticker for another year is not used
    assert sticker.edit_year(session) is None  # locked until the next payment period
    for call in (lambda: sticker.render(session, SYSTEM, store, due, "#FFFFFF", "transparent", 6),
                 lambda: sticker.upload_template(session, SYSTEM, store, default_template())):
        with pytest.raises(DomainError, match="sticker_locked"):
            call()

    # The next payment period opens the next year's sticker.
    window = settings.get_int(session, "renewal_window_days")
    in_period = date(due, 12, 31) - timedelta(days=window)
    assert payments.payment_years(session, in_period) == [due, due + 1]
    assert sticker.edit_year(session, in_period) == due + 1


@pytest.mark.db
def test_published_sticker_is_hero_of_new_passes(session):
    store = MemoryMediaStore()
    url = sticker.publish(session, SYSTEM, store, sticker.due_year(session), "#ffffff", "transparent", 5)

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
def test_web_preview_and_publish(migrated_db, monkeypatch):
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
    from ess.models import AdminRole
    from ess.services import admin_access

    with migrated_db() as s:  # an ordinary administrator (not a superadmin) designs the sticker
        admin_access.grant_access(s, SYSTEM, "office@example.org", "Kancelária", AdminRole.ADMIN)
        s.commit()
    google.userinfo = {"email": "office@example.org", "email_verified": True, "name": "Admin"}
    client.get("/admin/auth/callback")
    page = client.get("/admin/sticker").text
    year = int(re.search(r'name="year" value="(\d+)"', page).group(1))
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    files = {"template": ("t.png", default_template(), "image/png")}
    page = client.post("/admin/sticker/template", data={"csrf_token": csrf}, files=files).text
    assert "Šablóna známky bola nahraná" in page and "nahratá" in page
    template = next(iter(store.objects))
    page = client.post("/admin/sticker", data={"csrf_token": csrf, "year": year, "text_color": "#ffffff",
                                                "transparent": "on", "action": "preview"}).text
    assert "data:image/png;base64," in page and len(store.objects) == 1
    seed = re.search(r'name="seed" value="(\d+)"', page).group(1)
    page = client.post("/admin/sticker", data={"csrf_token": csrf, "year": year, "text_color": "#ffffff",
                                                "transparent": "on", "action": "publish", "seed": seed}).text
    assert f"Ročná známka na rok {year} je zverejnená" in page and len(store.objects) == 2
    [data] = [d for name, (d, _) in store.objects.items() if name != template]
    assert data == generate_sticker(default_template(), year, "#FFFFFF", "transparent", int(seed))  # = preview
    assert 'name="action"' not in page and "je zverejnená. Známku na ďalší rok" in page  # locked
