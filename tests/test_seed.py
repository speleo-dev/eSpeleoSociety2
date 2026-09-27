import pytest
from sqlalchemy import func, select

from ess.models import Member, Membership
from ess.tools.seed_test_data import seed


@pytest.mark.db
def test_seed_creates_consistent_data(migrated_db, capsys):
    seed(member_count=60, rng_seed=1)
    with migrated_db() as session:
        assert session.scalar(select(func.count()).select_from(Member)) == 60
        # Every member with an open membership has exactly one primary one (also enforced by the DB).
        open_members = session.scalars(select(Membership.member_id).where(Membership.valid_to.is_(None))).all()
        primaries = session.scalars(
            select(Membership.member_id).where(Membership.valid_to.is_(None), Membership.is_primary)
        ).all()
        assert set(open_members) == set(primaries)
    with pytest.raises(SystemExit):
        seed(member_count=10, rng_seed=1)
