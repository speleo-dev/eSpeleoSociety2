"""News (administration) and news and documents on the member portal."""

import re
from datetime import date, timedelta

import pytest

from ess.services import documents, news, portal_auth
from ess.services.access import SYSTEM, Actor, DomainError, PermissionDenied
from tests.test_ecp_verification import _issued
from tests.test_web_admin import client, csrf, google, login  # noqa: F401 (fixtures)

pytestmark = pytest.mark.db


def test_published_news(session):
    with pytest.raises(PermissionDenied):
        news.save(session, Actor(kind="member", id="x"), "A", "B")
    with pytest.raises(DomainError):
        news.save(session, SYSTEM, " ", "text")
    old = news.save(session, SYSTEM, "Stará", "text", date.today() - timedelta(days=3))
    news.save(session, SYSTEM, "Nová", "text")
    news.save(session, SYSTEM, "Budúca", "text", date.today() + timedelta(days=2))
    news.save(session, SYSTEM, "Skrytá", "text", visible=False)
    assert [n.title for n in news.published(session)] == ["Nová", "Stará"]
    news.save(session, SYSTEM, "Stará upravená", "text", old.published_on, news_id=old.id)
    news.delete(session, SYSTEM, old.id)
    assert [n.title for n in news.published(session)] == ["Nová"]


def test_admin_news_and_portal(migrated_db, google, client):
    login(client, google)
    token = csrf(client)
    r = client.post("/admin/news", data={"csrf_token": token, "title": "Valné zhromaždenie",
                                         "body": "Prvý odsek.\n\nDruhý odsek.", "visible": "1"})
    assert "Novinka bola uložená" in r.text and "zverejnená" in r.text
    with migrated_db() as session:
        documents.save_document(session, SYSTEM, "Stanovy SSS", "https://sss.sk/stanovy.pdf", None)
        _, ecp_pass, member_id = _issued(session)
        new = portal_auth.open_session(session, member_id, "email_code")
        session.commit()
    client.cookies.set("ess_member", new.token)
    home = client.get("/portal").text
    assert "Valné zhromaždenie" in home and "<p>Druhý odsek.</p>" in home
    assert 'href="https://sss.sk/stanovy.pdf"' in home and re.search(r"Stanovy SSS", home)
