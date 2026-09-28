"""Club logo URL.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clubs", sa.Column("logo_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("clubs", "logo_url")
