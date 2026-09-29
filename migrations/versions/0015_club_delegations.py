"""Club chair delegation: another member manages the club instead of the chair (R37).

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "club_delegations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("club_id", UUID(as_uuid=True), sa.ForeignKey("clubs.id"), nullable=False),
        sa.Column("chair_member_id", UUID(as_uuid=True), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("delegate_member_id", UUID(as_uuid=True), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("created_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("ended_by", sa.String(64)),
        sa.Column("end_reason", sa.String(16)),
    )
    op.create_index("ix_club_delegations_club_id", "club_delegations", ["club_id"])
    op.create_index("ix_club_delegations_delegate_member_id", "club_delegations", ["delegate_member_id"])
    op.create_index("uq_club_delegations_active", "club_delegations", ["club_id"], unique=True,
                    postgresql_where=sa.text("ended_at IS NULL"))


def downgrade() -> None:
    op.drop_table("club_delegations")
