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
