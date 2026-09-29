"""Notifications to the eCP (R41): messages and their delivery to each pass.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ecp_notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("header", sa.String(100), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("recipients", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "ecp_notification_deliveries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("notification_id", UUID(as_uuid=True), sa.ForeignKey("ecp_notifications.id"), nullable=False),
        sa.Column("pass_id", UUID(as_uuid=True), sa.ForeignKey("ecp_passes.id"), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_ecp_notification_deliveries_notification_id", "ecp_notification_deliveries",
                    ["notification_id"])
    op.create_index("uq_ecp_notification_deliveries", "ecp_notification_deliveries",
                    ["notification_id", "pass_id"], unique=True)
    op.create_index("ix_ecp_notification_deliveries_waiting", "ecp_notification_deliveries", ["notification_id"],
                    postgresql_where=sa.text("sent_at IS NULL AND failed_at IS NULL"))


def downgrade() -> None:
    op.drop_table("ecp_notification_deliveries")
    op.drop_table("ecp_notifications")
