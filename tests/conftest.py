import os

import pytest

from ess.config import get_settings
from ess.db import get_engine, get_sessionmaker
from ess.security import pii
from ess.security.crypto import generate_key

TEST_DATABASE_URL = os.environ.get("ESS_TEST_DATABASE_URL")


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    pii.get_cipher.cache_clear()
    pii.get_blind_index.cache_clear()


@pytest.fixture(autouse=True)
def test_environment(monkeypatch):
    monkeypatch.setenv("ESS_ENVIRONMENT", "test")
    monkeypatch.delenv("ESS_DATABASE_URL", raising=False)
    monkeypatch.setenv("ESS_PII_KEYS", f"test:{generate_key()}")
    monkeypatch.setenv("ESS_BLIND_INDEX_KEY", generate_key())
    monkeypatch.setenv("ESS_SUPER_ADMIN_EMAILS", "super@example.org")
    _clear_caches()
    yield
    _clear_caches()


@pytest.fixture
def migrated_db(monkeypatch):
    """Empty database migrated to the latest revision. Needs ESS_TEST_DATABASE_URL."""
    if not TEST_DATABASE_URL:
        pytest.skip("ESS_TEST_DATABASE_URL is not set")
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("ESS_DATABASE_URL", TEST_DATABASE_URL)
    _clear_caches()
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield get_sessionmaker()
    get_engine().dispose()


@pytest.fixture
def session(migrated_db):
    with migrated_db() as s:
        yield s
