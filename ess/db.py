"""Database engine and sessions.

The database runs on WebSupport and is reached over the internet (~17 ms per query, ~170 ms to open
a connection), so connections are pooled and reused instead of opened per request.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ess.config import get_settings


class Base(DeclarativeBase):
    """Base class for ORM models."""


def to_sqlalchemy_url(database_url: str) -> str:
    """Use the psycopg 3 driver for plain postgresql:// URLs."""
    for prefix in ("postgresql://", "postgres://"):
        if database_url.startswith(prefix):
            return "postgresql+psycopg://" + database_url[len(prefix) :]
    return database_url


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("ESS_DATABASE_URL is not set")
    return create_engine(
        to_sqlalchemy_url(settings.database_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,  # drop connections closed by the server or a proxy
        pool_recycle=300,
        connect_args={"sslmode": settings.db_sslmode, "connect_timeout": 10},
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with get_sessionmaker()() as session:
        yield session
