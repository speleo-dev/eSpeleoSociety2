"""Club code for CSV imports.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clubs", sa.Column("code", sa.String(length=20), nullable=True))
    op.create_unique_constraint("clubs_code_key", "clubs", ["code"])
    op.execute("UPDATE clubs SET code = 'SSS' WHERE is_unaffiliated")


def downgrade() -> None:
    op.drop_constraint("clubs_code_key", "clubs", type_="unique")
    op.drop_column("clubs", "code")
