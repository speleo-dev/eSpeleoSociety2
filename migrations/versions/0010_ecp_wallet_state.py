"""eCP: last state sent to Google Wallet (state changes are pushed after commit, R25).

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ecp_passes", sa.Column("wallet_state", sa.String(length=16), nullable=True))
    op.execute("UPDATE ecp_passes SET wallet_state = state")


def downgrade() -> None:
    op.drop_column("ecp_passes", "wallet_state")
