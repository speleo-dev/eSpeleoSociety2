"""Bank transaction: encrypted payment message (manual matching, reference typed into the message).

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bank_transactions", sa.Column("message_enc", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("bank_transactions", "message_enc")
