"""Cave trips reported by members on the portal (R41).

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cave_trips",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("member_id", UUID(as_uuid=True), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("cave_enc", sa.LargeBinary(), nullable=False),
        sa.Column("companions_enc", sa.LargeBinary()),
        sa.Column("planned_return_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("returned_at", sa.DateTime(timezone=True)),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True)),
        sa.Column("alert_sent_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_cave_trips_member_id", "cave_trips", ["member_id"])
    op.create_index("uq_cave_trips_open", "cave_trips", ["member_id"], unique=True,
                    postgresql_where=sa.text("returned_at IS NULL"))


def downgrade() -> None:
    op.drop_table("cave_trips")
