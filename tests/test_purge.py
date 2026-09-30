"""Deleting test data before a real import."""

import pytest
from sqlalchemy import func, select

from ess.models import Club, Member, Setting
from ess.tools.purge_test_data import purge
from tests.test_ecp_verification import _issued

pytestmark = pytest.mark.db


def test_purge_keeps_settings_and_unaffiliated_club(session):
    _issued(session)  # member, club, application, pass, consents, tokens
    session.commit()
    counts = purge(session)
    assert counts["members"] == 1 and counts["clubs"] == 1 and counts["ecp_passes"] == 1
    assert session.scalar(select(func.count()).select_from(Member)) == 0
    assert [c.name for c in session.scalars(select(Club))] == ["SSS – nezaradení"]
    assert session.scalar(select(func.count()).select_from(Setting)) > 0
