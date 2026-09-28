"""Phase 2: eCP applications, passes, QR tokens, SSS cards, consents; eCP settings.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('ecp_applications',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('member_id', sa.UUID(), nullable=True),
    sa.Column('club_id', sa.UUID(), nullable=True),
    sa.Column('first_name_enc', sa.LargeBinary(), nullable=True),
    sa.Column('last_name_enc', sa.LargeBinary(), nullable=True),
    sa.Column('birth_date_enc', sa.LargeBinary(), nullable=True),
    sa.Column('email_enc', sa.LargeBinary(), nullable=True),
    sa.Column('email_bidx', sa.LargeBinary(), nullable=True),
    sa.Column('card_number_enc', sa.LargeBinary(), nullable=True),
    sa.Column('member_since_enc', sa.LargeBinary(), nullable=True),
    sa.Column('photo_original', sa.String(length=200), nullable=True),
    sa.Column('photo_cropped', sa.String(length=200), nullable=True),
    sa.Column('wants_wallet', sa.Boolean(), nullable=False),
    sa.Column('wants_card', sa.Boolean(), nullable=False),
    sa.Column('reject_reason', sa.Text(), nullable=True),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_by', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['club_id'], ['clubs.id'], ),
    sa.ForeignKeyConstraint(['member_id'], ['members.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ecp_applications_email_bidx'), 'ecp_applications', ['email_bidx'], unique=False)
    op.create_index(op.f('ix_ecp_applications_member_id'), 'ecp_applications', ['member_id'], unique=False)
    op.create_index('ix_ecp_applications_status', 'ecp_applications', ['status'], unique=False)
    op.create_index('uq_ecp_applications_open', 'ecp_applications', ['member_id'], unique=True, postgresql_where=sa.text("status IN ('email_pending', 'photo_pending', 'submitted')"))
    op.create_table('sss_cards',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('member_id', sa.UUID(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('code_hash', sa.LargeBinary(), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('issued_by', sa.String(length=64), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['member_id'], ['members.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code_hash')
    )
    op.create_index(op.f('ix_sss_cards_member_id'), 'sss_cards', ['member_id'], unique=False)
    op.create_index('uq_sss_cards_member_year', 'sss_cards', ['member_id', 'year'], unique=True, postgresql_where=sa.text('revoked_at IS NULL'))
    op.create_table('consents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('member_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('text_version', sa.String(length=32), nullable=False),
    sa.Column('granted', sa.Boolean(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=True),
    sa.Column('recorded_by', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['ecp_applications.id'], ),
    sa.ForeignKeyConstraint(['member_id'], ['members.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_consents_member_id'), 'consents', ['member_id'], unique=False)
    op.create_table('ecp_passes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('member_id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=True),
    sa.Column('wallet_object_id', sa.String(length=120), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('photo', sa.String(length=200), nullable=True),
    sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['ecp_applications.id'], ),
    sa.ForeignKeyConstraint(['member_id'], ['members.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('wallet_object_id')
    )
    op.create_index(op.f('ix_ecp_passes_member_id'), 'ecp_passes', ['member_id'], unique=False)
    op.create_index('uq_ecp_passes_current', 'ecp_passes', ['member_id'], unique=True, postgresql_where=sa.text("state <> 'revoked'"))
    op.create_table('one_time_tokens',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.LargeBinary(), nullable=False),
    sa.Column('purpose', sa.String(length=32), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['application_id'], ['ecp_applications.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_one_time_tokens_application_id'), 'one_time_tokens', ['application_id'], unique=False)
    op.create_table('verification_tokens',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('pass_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('first_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['pass_id'], ['ecp_passes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_verification_tokens_pass_id'), 'verification_tokens', ['pass_id'], unique=False)
    op.create_index('uq_tasks_open_ecp_issue', 'tasks', ['member_id'], unique=True, postgresql_where=sa.text("status = 'open' AND task_type = 'ecp_issue'"))
    op.execute(
        "INSERT INTO settings (key, value) VALUES ('ecp_link_valid_hours', '24'), ('ecp_application_expiry_days', '14'),"
        " ('ecp_qr_grace_minutes', '15'), ('ecp_qr_daily_limit', '10') ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key LIKE 'ecp\\_%'")
    op.execute("DELETE FROM tasks WHERE task_type = 'ecp_issue'")
    op.drop_index('uq_tasks_open_ecp_issue', table_name='tasks', postgresql_where=sa.text("status = 'open' AND task_type = 'ecp_issue'"))
    op.drop_index(op.f('ix_verification_tokens_pass_id'), table_name='verification_tokens')
    op.drop_table('verification_tokens')
    op.drop_index(op.f('ix_one_time_tokens_application_id'), table_name='one_time_tokens')
    op.drop_table('one_time_tokens')
    op.drop_index('uq_ecp_passes_current', table_name='ecp_passes', postgresql_where=sa.text("state <> 'revoked'"))
    op.drop_index(op.f('ix_ecp_passes_member_id'), table_name='ecp_passes')
    op.drop_table('ecp_passes')
    op.drop_index(op.f('ix_consents_member_id'), table_name='consents')
    op.drop_table('consents')
    op.drop_index('uq_sss_cards_member_year', table_name='sss_cards', postgresql_where=sa.text('revoked_at IS NULL'))
    op.drop_index(op.f('ix_sss_cards_member_id'), table_name='sss_cards')
    op.drop_table('sss_cards')
    op.drop_index('uq_ecp_applications_open', table_name='ecp_applications', postgresql_where=sa.text("status IN ('email_pending', 'photo_pending', 'submitted')"))
    op.drop_index('ix_ecp_applications_status', table_name='ecp_applications')
    op.drop_index(op.f('ix_ecp_applications_member_id'), table_name='ecp_applications')
    op.drop_index(op.f('ix_ecp_applications_email_bidx'), table_name='ecp_applications')
    op.drop_table('ecp_applications')
