"""Review of eCP applications: approve (Google Wallet pass), reject, re-crop."""

import re
import uuid
from datetime import date

import pytest
from sqlalchemy import select

from ess.mail import MemoryMailer, get_mailer
from ess.models import EcpApplication, EcpPass, Member, Task, VerificationToken
from ess.services import ecp_applications as apps
from ess.services import ecp_issuance, members
from ess.services.access import SYSTEM, Actor, DomainError, PermissionDenied
from ess.storage import MemoryMediaStore, get_media_store
from ess.wallet import MemoryWalletClient, PassContent, build_pass_object, get_wallet
from tests.test_ecp_application import _club, _form, _member, _photo

ADMIN = Actor(kind="admin", id="admin-1")


def test_pass_object_follows_original_design(monkeypatch):
    from ess.config import get_settings

    monkeypatch.setenv("ESS_MEDIA_BUCKET", "bucket-x")
    get_settings.cache_clear()
    obj = build_pass_object(PassContent(
        object_id="3388000000022877308.abc", member_name="Ing. Ján Vzorový", club_name="JS Demänová",
        card_number="1234", member_since=date(1995, 1, 1), birth_date=date(1980, 5, 17),
        photo_url="https://storage.googleapis.com/bucket-x/photos/p.jpg", check_url="https://ess/v/tok"))
    assert obj["classId"] == "3388000000022877308.member" and obj["state"] == "ACTIVE"
    assert obj["barcode"] == {"type": "QR_CODE", "value": "https://ess/v/tok"}
    assert [m["id"] for m in obj["textModulesData"]] == ["primary_club", "member_from", "member_id", "birth_date"]
    assert obj["textModulesData"][1]["body"] == "01.01.1995"
    assert obj["logo"]["sourceUri"]["uri"] == "https://storage.googleapis.com/bucket-x/static/Logo_sss.png"


def _submitted(session, store, **member_kw):
    club_id = _club(session)
    member_id = _member(session, club_id, **member_kw)
    mail = apps.start_public(session, _form(club_id))
    app = apps.verify_email(session, mail.token)
    apps.submit_photo(session, app.id, _photo(), None, True, True, None, store)
    return app, member_id


@pytest.mark.db
def test_approve_issues_pass_and_fills_register(session):
    store, wallet = MemoryMediaStore(), MemoryWalletClient()
    app, member_id = _submitted(session, store, card_number=None, member_since=None)
    original, portrait = app.photo_original, app.photo_cropped
    with pytest.raises(PermissionDenied):
        ecp_issuance.approve(session, Actor(kind="member", id="x"), app.id, store, wallet, "https://ess")
    decision = ecp_issuance.approve(session, ADMIN, app.id, store, wallet, "https://ess/")
    assert app.status == "approved" and decision.cleanup == [original] and app.photo_original is None
    assert decision.save_url.startswith("https://pay.google.com/gp/v/save/")
    assert decision.email == "Rodina@example.org" and decision.member_name == "Ján Žiadateľ"
    ecp_pass = session.scalar(select(EcpPass))
    assert ecp_pass.member_id == member_id and ecp_pass.photo == portrait and ecp_pass.state == "active"
    obj = wallet.objects[ecp_pass.wallet_object_id]
    assert obj["imageModulesData"][0]["mainImage"]["sourceUri"]["uri"] == store.url(portrait)
    assert re.fullmatch(r"https://ess/v/[\w-]+", obj["barcode"]["value"])
    token = obj["barcode"]["value"].rsplit("/", 1)[1]
    assert session.scalar(select(VerificationToken.token_hash)) == ecp_issuance.hash_token(token)
    data = members.read_member(session.get(Member, member_id))
    assert data.card_number == "12 34" and data.member_since == date(1995, 1, 1)  # filled from the application
    task = session.scalar(select(Task).where(Task.task_type == "ecp_issue"))
    assert task.status == "done" and task.resolution == "approved"
    with pytest.raises(DomainError):
        ecp_issuance.approve(session, ADMIN, app.id, store, wallet, "https://ess")


@pytest.mark.db
def test_approve_refuses_duplicate_card_number(session):
    store = MemoryMediaStore()
    app, _ = _submitted(session, store, card_number=None)
    members.create_member(session, SYSTEM, members.MemberData(first_name="Iný", last_name="Člen", card_number="12 34"))
    with pytest.raises(DomainError) as exc:
        ecp_issuance.approve(session, ADMIN, app.id, store, MemoryWalletClient(), "https://ess")
    assert exc.value.code == "card_number_in_use"


@pytest.mark.db
def test_reject_and_recrop(session):
    store = MemoryMediaStore()
    app, _ = _submitted(session, store)
    old_portrait = app.photo_cropped
    decision = ecp_issuance.recrop(session, ADMIN, app.id, (0.2, 0.1, 0.5, 0.5), store)
    assert decision.cleanup == [old_portrait] and app.photo_cropped != old_portrait
    assert app.photo_cropped in store.objects
    with pytest.raises(DomainError):
        ecp_issuance.reject(session, ADMIN, app.id, "  ")
    decision = ecp_issuance.reject(session, ADMIN, app.id, "Nevyhovujúca fotka")
    assert app.status == "rejected" and app.reject_reason == "Nevyhovujúca fotka"
    assert len(decision.cleanup) == 2 and app.photo_cropped is None
    task = session.scalar(select(Task).where(Task.task_type == "ecp_issue"))
    assert task.status == "rejected"


@pytest.mark.db
def test_web_review_approve(migrated_db, monkeypatch):
    from ess.config import get_settings
    from tests.test_web_admin import FakeGoogle, client as _client_fixture  # noqa: F401
    from ess.web import auth
    from fastapi.testclient import TestClient

    from ess.main import create_app

    monkeypatch.setenv("ESS_GOOGLE_CLIENT_ID", "123-test.apps.googleusercontent.com")
    monkeypatch.setenv("ESS_GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("ESS_MEDIA_BUCKET", "test-bucket")
    get_settings.cache_clear()
    google = FakeGoogle()
    monkeypatch.setattr(auth, "_google", lambda: google)
    store, wallet, mailer = MemoryMediaStore(), MemoryWalletClient(), MemoryMailer()
    app = create_app()
    app.dependency_overrides.update({get_media_store: lambda: store, get_wallet: lambda: wallet,
                                     get_mailer: lambda: mailer})
    client = TestClient(app)
    with migrated_db() as s:
        application, _ = _submitted(s, store)
        application_id = application.id
        s.commit()
    google.userinfo = {"email": "super@example.org", "email_verified": True, "name": "Admin"}
    client.get("/admin/auth/callback")
    tasks_page = client.get("/admin/tasks").text
    assert f"/admin/ecp-applications/{application_id}" in tasks_page
    page = client.get(f"/admin/ecp-applications/{application_id}").text
    assert "Ján Žiadateľ" in page and "Schváliť a vydať eCP" in page
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    page = client.post(f"/admin/ecp-applications/{application_id}/approve", data={"csrf_token": csrf}).text
    assert "eCP bol vydaný." in page
    assert len(wallet.objects) == 1 and len(mailer.sent) == 1
    mail = mailer.sent[0]
    assert mail.to == "Rodina@example.org" and "pay.google.com/gp/v/save/" in mail.html
    assert "test-bucket/static/sk_add_to_google_wallet_add-wallet-badge.png" in mail.html
    with migrated_db() as s:
        assert s.get(EcpApplication, application_id).status == "approved"
    assert client.get(f"/admin/ecp-applications/{uuid.uuid4()}").status_code in (200, 404)
