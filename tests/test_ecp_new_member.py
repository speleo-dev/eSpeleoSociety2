"""New member proposed with "issue eCP" from the paper application form (R23)."""

import re
from datetime import date

import pytest
from sqlalchemy import select

from ess.mail import MemoryMailer, get_mailer
from ess.models import Consent, EcpApplication, MembershipStatus, Task
from ess.services import ecp_applications as apps
from ess.services import memberships, outbox, tasks
from ess.services.access import SYSTEM, DomainError
from ess.services.members import MemberData
from ess.storage import MemoryMediaStore, get_media_store
from tests.test_ecp_application import _club, _photo

pytestmark = pytest.mark.db


def _new(session, club_id, status, email="novy@example.org"):
    data = MemberData(first_name="Nový", last_name="Člen", email=email, birth_date=date(2000, 1, 1))
    return memberships.add_new_member_to_club(session, SYSTEM, data, club_id, status).member_id


def test_active_member_is_invited_at_once(session):
    club_id = _club(session)
    member_id = _new(session, club_id, MembershipStatus.MEMBER)
    apps.request_for_new_member(session, SYSTEM, member_id, club_id)
    app = session.scalar(select(EcpApplication))
    assert app.source == "club_chair" and app.status == "photo_pending" and app.member_id == member_id
    consent = session.scalar(select(Consent))
    assert consent.source == "paper_form" and consent.kind == "gdpr_ecp"
    [mail] = outbox.take(session)
    assert mail.to == "novy@example.org" and mail.context["link_path"].startswith("/ecp/photo/")
    token = mail.context["link_path"].rsplit("/", 1)[1]
    opened = apps.open_photo_invite(session, token)
    assert opened.id == app.id and opened.email_verified_at
    assert apps.open_photo_invite(session, token) is None  # single use
    apps.submit_photo(session, app.id, _photo(), None, True, True, False, MemoryMediaStore())
    assert app.status == "submitted"


def test_proposed_member_is_invited_after_activation(session):
    club_id = _club(session)
    member_id = _new(session, club_id, MembershipStatus.PENDING_ACTIVATION)
    apps.request_for_new_member(session, SYSTEM, member_id, club_id)
    assert session.scalar(select(EcpApplication)) is None and outbox.take(session) == []
    task = session.scalar(select(Task).where(Task.task_type == "member_activation"))
    assert task.context["issue_ecp"] is True
    tasks.activate(session, SYSTEM, task.id)
    session.flush()
    assert session.scalar(select(EcpApplication)).status == "photo_pending"
    assert len(outbox.take(session)) == 1


def test_candidate_or_missing_email_is_refused(session):
    club_id = _club(session)
    candidate = _new(session, club_id, MembershipStatus.CANDIDATE)
    with pytest.raises(DomainError) as exc:
        apps.request_for_new_member(session, SYSTEM, candidate, club_id)
    assert exc.value.code == "ecp_member_not_eligible"
    no_email = _new(session, club_id, MembershipStatus.MEMBER, email=None)
    with pytest.raises(DomainError) as exc:
        apps.request_for_new_member(session, SYSTEM, no_email, club_id)
    assert exc.value.code == "ecp_needs_email"


def test_web_admin_creates_member_with_ecp(migrated_db, monkeypatch):
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
    mailer, store = MemoryMailer(), MemoryMediaStore()
    app = create_app()
    app.dependency_overrides.update({get_mailer: lambda: mailer, get_media_store: lambda: store})
    client = TestClient(app)
    with migrated_db() as s:
        club_id = _club(s)
        s.commit()
    google.userinfo = {"email": "super@example.org", "email_verified": True, "name": "Admin"}
    client.get("/admin/auth/callback")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/admin").text).group(1)
    page = client.post("/admin/members/new", data={
        "csrf_token": csrf, "first_name": "Nový", "last_name": "Člen", "email": "novy@example.org",
        "club_id": str(club_id), "status": "member", "issue_ecp": "on"}).text
    assert "Poslali sme mu e-mail" in page
    [mail] = mailer.sent
    link = re.search(r"https?://\S+/ecp/photo/\S+", mail.text).group(0)
    response = client.get(link[link.index("/ecp/photo/"):], follow_redirects=False)
    assert response.headers["location"] == "/ecp/apply/photo"
    html = client.get("/ecp/apply/photo").text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    response = client.post("/ecp/apply/photo", files={"photo": ("f.jpg", _photo(), "image/jpeg")},
                           data={"csrf_token": csrf, "gdpr": "on"}, follow_redirects=False)
    assert response.headers["location"] == "/ecp/apply/done"
    with migrated_db() as s:
        app_id = s.scalar(select(EcpApplication.id))
    page = client.get(f"/admin/ecp-applications/{app_id}").text
    assert "Nový Člen" in page and "Schváliť a vydať eCP" in page

    candidate = client.post("/admin/members/new", data={
        "csrf_token": re.search(r'name="csrf_token" value="([^"]+)"', client.get("/admin").text).group(1),
        "first_name": "Čakateľ", "last_name": "Test", "email": "c@example.org", "club_id": str(club_id),
        "status": "candidate", "issue_ecp": "on"})
    assert candidate.status_code == 400 and "nie čakateľ" in candidate.text and len(mailer.sent) == 1
