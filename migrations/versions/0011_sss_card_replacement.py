"""SSS card: encrypted code (download / send again) and the reason of replacement (lost, stolen, damaged).

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sss_cards", sa.Column("code_enc", sa.LargeBinary(), nullable=True))
    op.add_column("sss_cards", sa.Column("revoke_reason", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("sss_cards", "revoke_reason")
    op.drop_column("sss_cards", "code_enc")
