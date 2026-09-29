"""Initial data: the real SSS clubs with logos (ess/data/clubs), loaded idempotently."""

import pytest
from sqlalchemy import select

from ess.models import Club
from ess.storage import MemoryMediaStore
from ess.tools import load_clubs

def test_data_file_is_valid():
    rows = load_clubs.rows()
    assert len(rows) == 53 and len({r["kod"] for r in rows}) == 53
    for row in rows:
        assert row["kod"] and row["nazov"]
        if row["logo_subor"]:
            assert (load_clubs.DATA / "logos" / row["logo_subor"]).is_file()


@pytest.mark.db
def test_load_is_idempotent_and_keeps_existing_logo(session):
    session.add(Club(name="Speleoklub Cassovia", code="CASS", is_unaffiliated=False, uses_candidates=True, active=True,
                     logo_url="https://storage.googleapis.com/b/clubs/own.png"))
    session.flush()
    store = MemoryMediaStore()
    first = load_clubs.load(session, store)
    assert (first.created, first.existing, first.logos) == (52, 1, 40)  # Cassovia exists and has its own logo
    cassovia = session.scalar(select(Club).where(Club.code == "CASS"))
    assert cassovia.logo_url.endswith("/own.png")
    again = load_clubs.load(session, store)
    assert (again.created, again.existing, again.logos) == (0, 53, 0)
