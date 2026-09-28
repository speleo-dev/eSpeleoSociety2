"""Phase 2 schema: migrations match the models, constraints, eCP settings."""

import uuid

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError

from ess.db import Base, get_engine
from ess.models import EcpApplication, EcpPass, Member, Task, TaskType
from ess.services import settings
from ess.services.access import SYSTEM, Actor, DomainError, PermissionDenied

pytestmark = pytest.mark.db


def test_migrations_match_models(migrated_db):
    with get_engine().connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_downgrade_and_upgrade_phase2(migrated_db):
    config = Config("alembic.ini")
    command.downgrade(config, "0007")  # through 0009 and 0008
    command.upgrade(config, "head")


def _member(s) -> uuid.UUID:
    m = Member(id=uuid.uuid4(), first_name_enc=b"x", last_name_enc=b"y")
    s.add(m)
    s.flush()
    return m.id


def test_one_open_application_and_one_current_pass(session):
    member_id = _member(session)
    session.add(EcpApplication(source="public", status="submitted", member_id=member_id))
    session.add(EcpApplication(source="public", status="rejected", member_id=member_id))
    session.flush()
    session.add(EcpApplication(source="public", status="email_pending", member_id=member_id))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    member_id = _member(session)
    session.add(EcpPass(member_id=member_id, wallet_object_id="i.a", state="revoked"))
    session.add(EcpPass(member_id=member_id, wallet_object_id="i.b", state="active"))
    session.flush()
    session.add(EcpPass(member_id=member_id, wallet_object_id="i.c", state="inactive"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_one_open_ecp_issue_task(session):
    member_id = _member(session)
    session.add(Task(task_type=TaskType.ECP_ISSUE.value, status="open", member_id=member_id))
    session.flush()
    session.add(Task(task_type=TaskType.ECP_ISSUE.value, status="open", member_id=member_id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_ecp_settings_defaults_and_validation(session):
    assert settings.get_int(session, "ecp_link_valid_hours") == 24
    assert settings.get_int(session, "ecp_application_expiry_days") == 14
    assert settings.get_int(session, "ecp_qr_grace_minutes") == 15
    assert settings.get_int(session, "ecp_qr_daily_limit") == 10
    settings.set_setting(session, SYSTEM, "ecp_link_valid_hours", "48")
    assert settings.get_int(session, "ecp_link_valid_hours") == 48
    for bad in ("0", "-1", "abc", "1.5"):
        with pytest.raises(DomainError):
            settings.set_setting(session, SYSTEM, "ecp_link_valid_hours", bad)
    with pytest.raises(PermissionDenied):
        settings.set_setting(session, Actor(kind="admin", id="x"), "ecp_link_valid_hours", "12")
