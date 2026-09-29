"""Member portal login (R38): portal key in the eCP, e-mail login codes, member sessions.

Existing passes get a portal key and are marked stale, so the portal link reaches Google Wallet.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-29
"""

import secrets

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ecp_passes", sa.Column("portal_key", sa.String(43), nullable=True))
    op.create_unique_constraint("ecp_passes_portal_key_key", "ecp_passes", ["portal_key"])
    conn = op.get_bind()
    for (pass_id,) in conn.execute(sa.text("SELECT id FROM ecp_passes WHERE state <> 'revoked'")).all():
        conn.execute(sa.text("UPDATE ecp_passes SET portal_key = :k, content_stale = true WHERE id = :id"),
                     {"k": secrets.token_urlsafe(24), "id": pass_id})
    op.create_table(
        "member_login_codes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("member_id", UUID(as_uuid=True), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("code_hash", sa.LargeBinary(), nullable=False),
        sa.Column("browser_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_member_login_codes_member_id", "member_login_codes", ["member_id"])
    op.create_table(
        "member_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("member_id", UUID(as_uuid=True), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_member_sessions_member_id", "member_sessions", ["member_id"])


def downgrade() -> None:
    op.drop_table("member_sessions")
    op.drop_table("member_login_codes")
    op.drop_constraint("ecp_passes_portal_key_key", "ecp_passes")
    op.drop_column("ecp_passes", "portal_key")
