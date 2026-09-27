"""Alembic environment: runs migrations against ESS_DATABASE_URL."""

from logging.config import fileConfig

from alembic import context

import ess.audit  # noqa: F401  (registers models on Base.metadata)
import ess.models  # noqa: F401
from ess.db import Base, get_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline mode is not supported; set ESS_DATABASE_URL and run online.")
run_migrations_online()
