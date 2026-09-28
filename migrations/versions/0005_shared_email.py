"""E-mail is not unique: spouses may share one address.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_members_email_bidx", table_name="members")
    op.create_index("ix_members_email_bidx", "members", ["email_bidx"], unique=False)


def downgrade() -> None:
    # Fails if some members already share an e-mail - that is intended (no silent data loss).
    op.drop_index("ix_members_email_bidx", table_name="members")
    op.create_index("uq_members_email_bidx", "members", ["email_bidx"], unique=True,
                    postgresql_where=sa.text("email_bidx IS NOT NULL"))
