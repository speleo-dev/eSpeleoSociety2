import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ess import audit
from ess.main import create_app


def test_index_page():
    response = TestClient(create_app()).get("/")
    assert response.status_code == 200
    assert "eSpeleoSociety" in response.text


def test_healthz():
    assert TestClient(create_app()).get("/healthz").json() == {"status": "ok"}


def test_readyz_without_database():
    response = TestClient(create_app()).get("/readyz")
    assert response.status_code == 503


def test_docs_hidden_in_production(monkeypatch):
    from ess.config import get_settings

    monkeypatch.setenv("ESS_ENVIRONMENT", "prod")
    monkeypatch.setenv("ESS_SESSION_SECRET", "x" * 48)
    get_settings.cache_clear()
    assert TestClient(create_app()).get("/docs").status_code == 404


def test_production_requires_session_secret(monkeypatch):
    from ess.config import get_settings

    monkeypatch.setenv("ESS_ENVIRONMENT", "prod")
    monkeypatch.delenv("ESS_SESSION_SECRET", raising=False)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="ESS_SESSION_SECRET"):
        create_app()


@pytest.mark.db
def test_readyz_with_database(migrated_db):
    assert TestClient(create_app()).get("/readyz").json() == {"status": "ok", "database": "ok"}


@pytest.mark.db
def test_audit_entry_is_part_of_transaction(migrated_db):
    with migrated_db() as session:
        audit.record(session, actor_type="system", actor_id=None, action="test.rollback")
        session.rollback()
        audit.record(session, actor_type="system", actor_id=None, action="test.commit", details={"field": "x"})
        session.commit()
        actions = session.scalars(select(audit.AuditLog.action)).all()
    assert actions == ["test.commit"]


def test_static_icons_and_logo_are_served():
    client = TestClient(create_app())
    assert client.get("/static/icons/member.png").headers["content-type"] == "image/png"
    assert client.get("/static/logo-app.png").status_code == 200
    assert "/static/logo-sss.png" in client.get("/").text


def test_error_messages_have_no_duplicate_keys():
    import ast
    import collections
    from pathlib import Path

    import ess.web.templates as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            assert [k for k, n in collections.Counter(keys).items() if n > 1] == []
