"""Portal devices: at most N signed-in devices per member (setting portal_max_devices, default 2).

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("member_sessions", sa.Column("device", sa.String(60), nullable=True))
    op.add_column("member_sessions", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("member_passkeys", sa.Column("session_id", UUID(as_uuid=True),
                                               sa.ForeignKey("member_sessions.id"), nullable=True))
    op.execute("INSERT INTO settings (key, value) VALUES ('portal_max_devices', '2') ON CONFLICT (key) DO NOTHING")


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'portal_max_devices'")
    op.drop_column("member_passkeys", "session_id")
    op.drop_column("member_sessions", "last_seen_at")
    op.drop_column("member_sessions", "device")
