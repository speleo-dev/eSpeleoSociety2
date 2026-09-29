"""eCP: flag for content changes (paid year, sticker) still to be sent to Google Wallet.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ecp_passes", sa.Column("content_stale", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("ecp_passes", "content_stale")
