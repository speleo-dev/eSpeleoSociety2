"""Phase 3 payments: fees, payment references, bank statements and transactions; payment tasks.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "payment_references",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(12), nullable=False, unique=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("club_id", UUID(as_uuid=True), sa.ForeignKey("clubs.id")),
        sa.Column("created_by", sa.String(64)),
        sa.Column("expected_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("paid_amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(10), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("kind IN ('member', 'bulk')", name="ck_payment_references_kind"),
        sa.CheckConstraint("status IN ('open', 'partial', 'paid', 'cancelled')", name="ck_payment_references_status"),
    )
    op.create_index("ix_payment_references_status", "payment_references", ["status"])
    op.create_table(
        "fees",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("member_id", UUID(as_uuid=True), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("reduced", sa.Boolean(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("payment_reference_id", UUID(as_uuid=True), sa.ForeignKey("payment_references.id")),
        sa.Column("paid_manually_by", sa.String(64)),
        sa.Column("note", sa.Text()),
        *_timestamps(),
    )
    op.create_index("ix_fees_member_id", "fees", ["member_id"])
    op.create_index("uq_fees_member_year", "fees", ["member_id", "year"], unique=True)
    op.create_table(
        "payment_reference_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("reference_id", UUID(as_uuid=True), sa.ForeignKey("payment_references.id"), nullable=False),
        sa.Column("fee_id", UUID(as_uuid=True), sa.ForeignKey("fees.id"), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
    )
    op.create_index("ix_payment_reference_items_reference_id", "payment_reference_items", ["reference_id"])
    op.create_index("ix_payment_reference_items_fee_id", "payment_reference_items", ["fee_id"])
    op.create_table(
        "bank_statements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("file_hash", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column("file_format", sa.String(16), nullable=False),
        sa.Column("uploaded_by", sa.String(64)),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "bank_transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("statement_id", UUID(as_uuid=True), sa.ForeignKey("bank_statements.id"), nullable=False),
        sa.Column("bank_ref", sa.String(100), nullable=False, unique=True),
        sa.Column("booked_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("payer_reference", sa.String(140)),
        sa.Column("payer_name_enc", sa.LargeBinary()),
        sa.Column("payer_iban_enc", sa.LargeBinary()),
        sa.Column("payment_reference_id", UUID(as_uuid=True), sa.ForeignKey("payment_references.id")),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_bank_transactions_statement_id", "bank_transactions", ["statement_id"])
    # Payment tasks may have no member (unknown reference).
    op.alter_column("tasks", "member_id", nullable=True)
    op.add_column("tasks", sa.Column("bank_transaction_id", UUID(as_uuid=True),
                                     sa.ForeignKey("bank_transactions.id"), nullable=True))
    op.execute("""
        INSERT INTO settings (key, value) VALUES ('payment_iban', ''), ('payment_account_name', 'Slovenská speleologická spoločnosť')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key IN ('payment_iban', 'payment_account_name')")
    op.drop_column("tasks", "bank_transaction_id")
    op.execute("DELETE FROM tasks WHERE member_id IS NULL")
    op.alter_column("tasks", "member_id", nullable=False)
    op.drop_table("bank_transactions")
    op.drop_table("bank_statements")
    op.drop_table("payment_reference_items")
    op.drop_table("fees")
    op.drop_table("payment_references")
