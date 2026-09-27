"""SSS membership end (presidium decision) and reduced fee amount.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("members", sa.Column("sss_ended_at", sa.Date(), nullable=True))
    op.add_column("members", sa.Column("sss_ended_note", sa.Text(), nullable=True))
    op.execute(
        "INSERT INTO settings (key, value) VALUES ('reduced_fee_amount', '7.00') ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'reduced_fee_amount'")
    op.drop_column("members", "sss_ended_note")
    op.drop_column("members", "sss_ended_at")
