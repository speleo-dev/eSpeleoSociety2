"""Administrator linked to a member: signs in with the eCP (R51); the Google e-mail becomes optional.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("admin_users", sa.Column("member_id", postgresql.UUID(as_uuid=True),
                                           sa.ForeignKey("members.id"), nullable=True))
    op.create_index("uq_admin_users_member", "admin_users", ["member_id"], unique=True,
                    postgresql_where=sa.text("member_id IS NOT NULL"))
    op.alter_column("admin_users", "google_email_enc", nullable=True)
    op.alter_column("admin_users", "google_email_bidx", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM admin_users WHERE google_email_bidx IS NULL")
    op.alter_column("admin_users", "google_email_bidx", nullable=False)
    op.alter_column("admin_users", "google_email_enc", nullable=False)
    op.drop_index("uq_admin_users_member", table_name="admin_users")
    op.drop_column("admin_users", "member_id")
