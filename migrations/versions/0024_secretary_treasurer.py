"""Positions of the SSS board as on sss.sk/vybor: secretary and treasurer (one holder each).

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

OLD = "valid_to IS NULL AND position_code IN ('sss_chair', 'sss_vice_chair', 'audit_chair')"
NEW = ("valid_to IS NULL AND position_code IN "
       "('sss_chair', 'sss_vice_chair', 'sss_secretary', 'sss_treasurer', 'audit_chair')")


def upgrade() -> None:
    op.execute("""
        INSERT INTO org_positions (code, name, is_single, is_club_bound, sort_order) VALUES
          ('sss_secretary', 'Tajomník SSS', true, false, 22),
          ('sss_treasurer', 'Hospodár SSS', true, false, 24)
        ON CONFLICT (code) DO NOTHING
    """)
    op.drop_index("uq_position_holders_single", table_name="position_holders")
    op.create_index("uq_position_holders_single", "position_holders", ["position_code"], unique=True,
                    postgresql_where=sa.text(NEW))


def downgrade() -> None:
    op.drop_index("uq_position_holders_single", table_name="position_holders")
    op.create_index("uq_position_holders_single", "position_holders", ["position_code"], unique=True,
                    postgresql_where=sa.text(OLD))
    op.execute("DELETE FROM position_holders WHERE position_code IN ('sss_secretary', 'sss_treasurer')")
    op.execute("DELETE FROM org_positions WHERE code IN ('sss_secretary', 'sss_treasurer')")
