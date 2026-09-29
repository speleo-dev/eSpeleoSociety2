"""Member: SSS card format (pdf / png); the next year's card is sent automatically after payment (R33).

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("members", sa.Column("card_format", sa.String(length=3), nullable=True))
    op.execute("""
        UPDATE members SET card_format = 'pdf'
        WHERE id IN (SELECT member_id FROM sss_cards WHERE revoked_at IS NULL)
    """)


def downgrade() -> None:
    op.drop_column("members", "card_format")
