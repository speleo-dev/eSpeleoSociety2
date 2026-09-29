"""Public eCP application, step 1: exact match with the register and e-mail verification (R22)."""

import re
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from ess.mail import MemoryMailer, get_mailer
from ess.models import Club, EcpApplication, EcpPass, MembershipStatus, OneTimeToken
from ess.services import ecp_applications as apps
from ess.services import memberships, members
from ess.services.access import SYSTEM, DomainError
from ess.services.ecp_applications import ApplicationForm
from ess.services.members import MemberData

pytestmark = pytest.mark.db

BIRTH = date(1980, 5, 17)


def _club(session, name="JS Žiadosť") -> uuid.UUID:
    club = Club(id=uuid.uuid4(), name=name, is_unaffiliated=False, uses_candidates=True, active=True)
    session.add(club)
    session.flush()
    return club.id


def _member(session, club_id, status=MembershipStatus.MEMBER, **kw) -> uuid.UUID:
    data = MemberData(**{"first_name": "Ján", "last_name": "Žiadateľ", "birth_date": BIRTH,
                         "email": "rodina@example.org", "card_number": "1234",
                         "member_since": date(1995, 1, 1), **kw})
    return memberships.add_new_member_to_club(session, SYSTEM, data, club_id, status).member_id


def _form(club_id=None, **kw) -> ApplicationForm:
    values = {"first_name": "jan", "last_name": "ZIADATEL", "birth_date": BIRTH, "email": "Rodina@example.org",
              "card_number": "12 34", "member_since_year": 1995, "club_id": club_id, **kw}
    return ApplicationForm(**values)


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_exact_match_creates_application_and_hashed_token(session):
    club_id = _club(session)
    member_id = _member(session, club_id)
    mail = apps.start_public(session, _form(club_id))
    assert mail is not None and mail.email == "Rodina@example.org"
    app = session.scalar(select(EcpApplication))
    assert app.member_id == member_id and app.status == "email_pending"
    assert b"Rodina" not in app.email_enc
    token_row = session.scalar(select(OneTimeToken))
    assert token_row.token_hash == apps.hash_token(mail.token) and mail.token.encode() not in token_row.token_hash


@pytest.mark.parametrize("change", [
    {"birth_date": date(1980, 5, 18)}, {"email": "iny@example.org"}, {"card_number": "9999"},
    {"member_since_year": 1996}, {"first_name": "Jana"},
])
def test_mismatch_is_silent(session, change):
    club_id = _club(session)
    _member(session, club_id)
    assert apps.start_public(session, _form(club_id, **change)) is None
    assert _count(session, EcpApplication) == 0


def test_missing_card_number_and_member_since_in_register_are_accepted(session):
    club_id = _club(session)
    _member(session, club_id, card_number=None, member_since=None)
    assert apps.start_public(session, _form(club_id, card_number="777", member_since_year=2001)) is not None


def test_only_active_member_of_the_chosen_club(session):
    club_id, other = _club(session), _club(session, "JS Iná")
    _member(session, club_id, status=MembershipStatus.CANDIDATE)
    assert apps.start_public(session, _form(club_id)) is None
    _member(session, other, first_name="Peter", card_number="2")
    assert apps.start_public(session, _form(club_id, first_name="Peter", card_number="2")) is None
    assert apps.start_public(session, _form(other, first_name="Peter", card_number="2")) is not None


def test_spouses_sharing_email_are_told_apart(session):
    club_id = _club(session)
    _member(session, club_id)
    eva = _member(session, club_id, first_name="Eva", birth_date=date(1982, 1, 2), card_number="5678")
    mail = apps.start_public(session, _form(club_id, first_name="Eva", birth_date=date(1982, 1, 2),
                                            card_number="5678"))
    assert mail and session.scalar(select(EcpApplication.member_id)) == eva


def test_expelled_or_with_current_pass_gets_nothing(session):
    club_id = _club(session)
    member_id = _member(session, club_id)
    session.add(EcpPass(member_id=member_id, wallet_object_id="i.x", state="active"))
    session.flush()
    assert apps.start_public(session, _form(club_id)) is None
    other = _member(session, club_id, first_name="Karol", card_number="3")
    members.expel_member(session, SYSTEM, other, "test")
    assert apps.start_public(session, _form(club_id, first_name="Karol", card_number="3")) is None


def test_reapply_replaces_unfinished_and_rate_limit(session):
    club_id = _club(session)
    _member(session, club_id)
    for _ in range(apps.MAX_APPLICATIONS_PER_EMAIL_PER_DAY):
        assert apps.start_public(session, _form(club_id)) is not None
    statuses = sorted(session.scalars(select(EcpApplication.status)))
    assert statuses == ["cancelled", "cancelled", "email_pending"]
    assert apps.start_public(session, _form(club_id)) is None


def test_submitted_application_is_not_replaced(session):
    club_id = _club(session)
    _member(session, club_id)
    apps.start_public(session, _form(club_id))
    session.scalar(select(EcpApplication)).status = "submitted"
    session.flush()
    assert apps.start_public(session, _form(club_id)) is None


def test_form_validation():
    for change, code in (({"birth_date": None}, "birth_date_required"), ({"email": "x"}, "invalid_email"),
                         ({"card_number": " "}, "card_number_required"), ({"member_since_year": 1800},
                         "member_since_required"), ({"club_id": None}, "club_required")):
        with pytest.raises(DomainError) as exc:
            apps.validate_form(_form(**{"club_id": uuid.uuid4(), **change}))
        assert exc.value.code == code


def test_verify_email_once_and_expiry(session):
    club_id = _club(session)
    _member(session, club_id)
    mail = apps.start_public(session, _form(club_id))
    app = apps.verify_email(session, mail.token)
    assert app.status == "photo_pending" and app.email_verified_at
    assert apps.verify_email(session, mail.token) is None  # single use

    other = _member(session, club_id, first_name="Karol", card_number="3")
    mail = apps.start_public(session, _form(club_id, first_name="Karol", card_number="3"))
    session.scalar(select(OneTimeToken).where(OneTimeToken.used_at.is_(None))).expires_at = \
        datetime.now(UTC) - timedelta(minutes=1)
    assert apps.verify_email(session, mail.token) is None
    assert apps.verify_email(session, "nonsense") is None
    assert other


def test_stale_applications_expire(session):
    club_id = _club(session)
    _member(session, club_id)
    mail = apps.start_public(session, _form(club_id))
    app = session.scalar(select(EcpApplication))
    app.created_at = datetime.now(UTC) - timedelta(days=15)
    session.flush()
    assert apps.verify_email(session, mail.token) is None
    session.refresh(app)
    assert app.status == "expired"


# --- web ---------------------------------------------------------------------------------------------

@pytest.fixture
def web(migrated_db):
    from fastapi.testclient import TestClient

    from ess.main import create_app

    app = create_app()
    mailer = MemoryMailer()
    app.dependency_overrides[get_mailer] = lambda: mailer
    client = TestClient(app)
    with migrated_db() as s:
        club_id = _club(s)
        _member(s, club_id)
        s.commit()
    return client, mailer, club_id


def _post(client, club_id, **change):
    html = client.get("/ecp/apply").text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    data = {"csrf_token": csrf, "first_name": "Ján", "last_name": "Žiadateľ", "birth_date": "1980-05-17",
            "email": "rodina@example.org", "card_number": "1234", "member_since": "1995", "club_id": str(club_id),
            **change}
    return client.post("/ecp/apply", data=data, follow_redirects=False)


def test_web_application_flow(web):
    client, mailer, club_id = web
    response = _post(client, club_id)
    assert response.status_code == 303 and response.headers["location"] == "/ecp/apply/sent"
    assert len(mailer.sent) == 1
    link = re.search(r"https?://\S+/ecp/email/\S+", mailer.sent[0].text).group(0)
    token_path = link[link.index("/ecp/email/"):]
    assert "Skontrolujte si e-mail" in client.get("/ecp/apply/sent").text
    response = client.get(token_path, follow_redirects=False)
    assert response.headers["location"] == "/ecp/apply/photo"
    page = client.get("/ecp/apply/photo").text
    assert "E-mail je overený" in page  # photo step
    assert 'id="camera-open"' in page and "/static/camera.js" in page  # photo from a notebook or phone camera
    assert "getUserMedia" in client.get("/static/camera.js").text
    assert client.get(token_path).status_code == 410  # used link


def test_web_mismatch_looks_the_same_and_sends_nothing(web):
    client, mailer, club_id = web
    response = _post(client, club_id, birth_date="1980-05-18")
    assert response.headers["location"] == "/ecp/apply/sent" and mailer.sent == []
    assert _post(client, club_id, website="http://spam").headers["location"] == "/ecp/apply/sent"
    assert mailer.sent == []


def test_web_validation_and_csrf(web):
    client, mailer, club_id = web
    response = _post(client, club_id, member_since="")
    assert response.status_code == 400 and "Zadajte rok" in response.text and 'value="1234"' in response.text
    assert client.post("/ecp/apply", data={"first_name": "x"}).status_code == 400
    assert client.get("/ecp/apply/photo").status_code == 410  # no verified application in this session


# --- step 3: photo and consents ------------------------------------------------------------------------

def _verified(session):
    club_id = _club(session)
    member_id = _member(session, club_id)
    mail = apps.start_public(session, _form(club_id))
    return apps.verify_email(session, mail.token), member_id


def _photo() -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (600, 800), "gray").save(out, format="JPEG")
    return out.getvalue()


def test_submit_photo_opens_task_and_records_consents(session):
    from ess.models import Consent, Task
    from ess.storage import MemoryMediaStore

    app, member_id = _verified(session)
    store = MemoryMediaStore()
    upload = apps.submit_photo(session, app.id, _photo(), None, True, False, True, store)
    assert app.status == "submitted" and app.wants_card and app.submitted_at
    assert sorted(store.objects) == sorted(upload.objects) and len(upload.objects) == 2
    assert all(len(n.split("/")[1]) == 64 + len(".jpg") for n in upload.objects)
    task = session.scalar(select(Task).where(Task.task_type == "ecp_issue"))
    assert task.member_id == member_id and task.context == {"application_id": str(app.id)}
    consents = {c.kind: c.granted for c in session.scalars(select(Consent))}
    assert consents == {"gdpr_ecp": True, "notifications": False}
    with pytest.raises(DomainError) as exc:  # only once
        apps.submit_photo(session, app.id, _photo(), None, True, False, False, store)
    assert exc.value.code == "application_not_open"


def test_submit_photo_requires_consent_and_store(session):
    from ess.storage import MemoryMediaStore

    app, _ = _verified(session)
    for args, code in (((False, MemoryMediaStore()), "gdpr_consent_required"), ((True, None), "media_store_not_configured")):
        with pytest.raises(DomainError) as exc:
            apps.submit_photo(session, app.id, _photo(), None, args[0], True, False, args[1])
        assert exc.value.code == code
    assert app.status == "photo_pending"


def test_web_photo_step(web):
    from ess.storage import MemoryMediaStore, get_media_store

    client, mailer, club_id = web
    store = MemoryMediaStore()
    client.app.dependency_overrides[get_media_store] = lambda: store
    _post(client, club_id)
    link = re.search(r"https?://\S+/ecp/email/\S+", mailer.sent[0].text).group(0)
    client.get(link[link.index("/ecp/email/"):])
    html = client.get("/ecp/apply/photo").text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    files = {"photo": ("tvar.jpg", _photo(), "image/jpeg")}
    response = client.post("/ecp/apply/photo", data={"csrf_token": csrf}, files=files)
    assert response.status_code == 400 and "Bez súhlasu" in response.text and store.objects == {}
    response = client.post("/ecp/apply/photo", files=files, follow_redirects=False, data={
        "csrf_token": csrf, "gdpr": "on", "crop_x": "0.1", "crop_y": "0.1", "crop_w": "0.6", "crop_h": "0.6"})
    assert response.headers["location"] == "/ecp/apply/done" and len(store.objects) == 2
    assert "Žiadosť je odoslaná" in client.get("/ecp/apply/done").text
    assert client.get("/ecp/apply/photo").status_code == 410  # the session no longer holds the application
