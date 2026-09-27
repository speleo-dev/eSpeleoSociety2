"""Phase 1 data model: clubs, members, memberships, organisation structure, admin access.

See docs/data-model.md.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27
"""

import uuid

import sqlalchemy as sa
from alembic import op


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('admin_users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('display_name_enc', sa.LargeBinary(), nullable=False),
    sa.Column('google_email_enc', sa.LargeBinary(), nullable=False),
    sa.Column('google_email_bidx', sa.LargeBinary(), nullable=False),
    sa.Column('role', sa.Enum('admin', 'system_admin', name='admin_role'), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('granted_by', sa.String(length=64), nullable=True),
    sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('google_email_bidx')
    )
    op.create_table('certificate_types',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('clubs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('short_name', sa.String(length=50), nullable=True),
    sa.Column('is_unaffiliated', sa.Boolean(), nullable=False),
    sa.Column('uses_candidates', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_index('uq_clubs_unaffiliated', 'clubs', ['is_unaffiliated'], unique=True, postgresql_where=sa.text('is_unaffiliated'))
    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('url', sa.String(length=1000), nullable=False),
    sa.Column('valid_until', sa.Date(), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('members',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('first_name_enc', sa.LargeBinary(), nullable=False),
    sa.Column('last_name_enc', sa.LargeBinary(), nullable=False),
    sa.Column('title_before_enc', sa.LargeBinary(), nullable=True),
    sa.Column('title_after_enc', sa.LargeBinary(), nullable=True),
    sa.Column('birth_date_enc', sa.LargeBinary(), nullable=True),
    sa.Column('email_enc', sa.LargeBinary(), nullable=True),
    sa.Column('address_enc', sa.LargeBinary(), nullable=True),
    sa.Column('phone_enc', sa.LargeBinary(), nullable=True),
    sa.Column('card_number_enc', sa.LargeBinary(), nullable=True),
    sa.Column('lookup_bidx', sa.LargeBinary(), nullable=True),
    sa.Column('email_bidx', sa.LargeBinary(), nullable=True),
    sa.Column('card_number_bidx', sa.LargeBinary(), nullable=True),
    sa.Column('member_since', sa.Date(), nullable=True),
    sa.Column('reduced_fee', sa.Boolean(), nullable=False),
    sa.Column('expelled_at', sa.Date(), nullable=True),
    sa.Column('expelled_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_members_lookup_bidx'), 'members', ['lookup_bidx'], unique=False)
    op.create_index('uq_members_card_number_bidx', 'members', ['card_number_bidx'], unique=True, postgresql_where=sa.text('card_number_bidx IS NOT NULL'))
    op.create_index('uq_members_email_bidx', 'members', ['email_bidx'], unique=True, postgresql_where=sa.text('email_bidx IS NOT NULL'))
    op.create_table('org_positions',
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('is_single', sa.Boolean(), nullable=False),
    sa.Column('is_club_bound', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('code')
    )
    op.create_table('settings',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('member_certificates',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('member_id', sa.UUID(), nullable=False),
    sa.Column('certificate_type_id', sa.UUID(), nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=True),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['certificate_type_id'], ['certificate_types.id'], ),
    sa.ForeignKeyConstraint(['member_id'], ['members.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_member_certificates_member_id'), 'member_certificates', ['member_id'], unique=False)
    op.create_table('memberships',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('member_id', sa.UUID(), nullable=False),
    sa.Column('club_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.Enum('candidate', 'pending_activation', 'member', 'suspended', name='membership_status'), nullable=False),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('end_reason', sa.Enum('status_change', 'terminated', 'expelled', name='membership_end_reason'), nullable=True),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('activated_by', sa.String(length=64), nullable=True),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['club_id'], ['clubs.id'], ),
    sa.ForeignKeyConstraint(['member_id'], ['members.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.CheckConstraint('valid_to IS NULL OR valid_to >= valid_from', name='ck_memberships_period'),
    sa.CheckConstraint('(valid_to IS NULL) = (end_reason IS NULL)', name='ck_memberships_end_reason'),
    sa.CheckConstraint('valid_to IS NULL OR NOT is_primary', name='ck_memberships_closed_not_primary')
    )
    op.create_index(op.f('ix_memberships_club_id'), 'memberships', ['club_id'], unique=False)
    op.create_index(op.f('ix_memberships_member_id'), 'memberships', ['member_id'], unique=False)
    op.create_index('uq_memberships_open_member_club', 'memberships', ['member_id', 'club_id'], unique=True, postgresql_where=sa.text('valid_to IS NULL'))
    op.create_index('uq_memberships_open_primary', 'memberships', ['member_id'], unique=True, postgresql_where=sa.text('valid_to IS NULL AND is_primary'))
    op.create_table('position_holders',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('position_code', sa.String(length=32), nullable=False),
    sa.Column('member_id', sa.UUID(), nullable=False),
    sa.Column('club_id', sa.UUID(), nullable=True),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['club_id'], ['clubs.id'], ),
    sa.ForeignKeyConstraint(['member_id'], ['members.id'], ),
    sa.ForeignKeyConstraint(['position_code'], ['org_positions.code'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.CheckConstraint('valid_to IS NULL OR valid_to >= valid_from', name='ck_position_holders_period')
    )
    op.create_index(op.f('ix_position_holders_member_id'), 'position_holders', ['member_id'], unique=False)
    op.create_index('uq_position_holders_club_chair', 'position_holders', ['club_id'], unique=True, postgresql_where=sa.text("valid_to IS NULL AND position_code = 'club_chair'"))
    op.create_index('uq_position_holders_single', 'position_holders', ['position_code'], unique=True, postgresql_where=sa.text("valid_to IS NULL AND position_code IN ('sss_chair', 'sss_vice_chair', 'audit_chair')"))

    _seed()


def _seed() -> None:
    clubs = sa.table("clubs", sa.column("id", sa.UUID), sa.column("name", sa.String),
                     sa.column("short_name", sa.String), sa.column("is_unaffiliated", sa.Boolean),
                     sa.column("uses_candidates", sa.Boolean), sa.column("active", sa.Boolean))
    op.bulk_insert(clubs, [{"id": uuid.uuid4(), "name": "SSS – nezaradení", "short_name": "SSS",
                            "is_unaffiliated": True, "uses_candidates": False, "active": True}])

    positions = sa.table("org_positions", sa.column("code", sa.String), sa.column("name", sa.String),
                         sa.column("is_single", sa.Boolean), sa.column("is_club_bound", sa.Boolean),
                         sa.column("sort_order", sa.Integer))
    op.bulk_insert(positions, [
        {"code": "sss_chair", "name": "Predseda SSS", "is_single": True, "is_club_bound": False, "sort_order": 10},
        {"code": "sss_vice_chair", "name": "Podpredseda SSS", "is_single": True, "is_club_bound": False, "sort_order": 20},
        {"code": "board_member", "name": "Člen výboru", "is_single": False, "is_club_bound": False, "sort_order": 30},
        {"code": "audit_chair", "name": "Predseda kontrolnej komisie", "is_single": True, "is_club_bound": False, "sort_order": 40},
        {"code": "audit_member", "name": "Člen kontrolnej komisie", "is_single": False, "is_club_bound": False, "sort_order": 50},
        {"code": "club_chair", "name": "Predseda skupiny", "is_single": True, "is_club_bound": True, "sort_order": 60},
    ])

    cert_types = sa.table("certificate_types", sa.column("id", sa.UUID), sa.column("code", sa.String),
                          sa.column("name", sa.String), sa.column("active", sa.Boolean))
    op.bulk_insert(cert_types, [
        {"id": uuid.uuid4(), "code": code, "name": name, "active": True}
        for code, name in (("srt1", "SRT1"), ("srt2", "SRT2"), ("rescuer", "Záchranár"), ("firefighter", "Hasič"))
    ])

    settings = sa.table("settings", sa.column("key", sa.String), sa.column("value", sa.Text))
    op.bulk_insert(settings, [
        {"key": "fee_amount", "value": "15.00"},
        {"key": "fee_currency", "value": "EUR"},
        {"key": "reduced_fee_age", "value": "62"},
    ])


def downgrade() -> None:
    op.drop_index('uq_position_holders_single', table_name='position_holders', postgresql_where=sa.text("valid_to IS NULL AND position_code IN ('sss_chair', 'sss_vice_chair', 'audit_chair')"))
    op.drop_index('uq_position_holders_club_chair', table_name='position_holders', postgresql_where=sa.text("valid_to IS NULL AND position_code = 'club_chair'"))
    op.drop_index(op.f('ix_position_holders_member_id'), table_name='position_holders')
    op.drop_table('position_holders')
    op.drop_index('uq_memberships_open_primary', table_name='memberships', postgresql_where=sa.text('valid_to IS NULL AND is_primary'))
    op.drop_index('uq_memberships_open_member_club', table_name='memberships', postgresql_where=sa.text('valid_to IS NULL'))
    op.drop_index(op.f('ix_memberships_member_id'), table_name='memberships')
    op.drop_index(op.f('ix_memberships_club_id'), table_name='memberships')
    op.drop_table('memberships')
    op.drop_index(op.f('ix_member_certificates_member_id'), table_name='member_certificates')
    op.drop_table('member_certificates')
    op.drop_table('settings')
    op.drop_table('org_positions')
    op.drop_index('uq_members_email_bidx', table_name='members', postgresql_where=sa.text('email_bidx IS NOT NULL'))
    op.drop_index('uq_members_card_number_bidx', table_name='members', postgresql_where=sa.text('card_number_bidx IS NOT NULL'))
    op.drop_index(op.f('ix_members_lookup_bidx'), table_name='members')
    op.drop_table('members')
    op.drop_table('documents')
    op.drop_index('uq_clubs_unaffiliated', table_name='clubs', postgresql_where=sa.text('is_unaffiliated'))
    op.drop_table('clubs')
    op.drop_table('certificate_types')
    op.drop_table('admin_users')
    for enum_name in ('membership_status', 'membership_end_reason', 'admin_role'):
        op.execute(f'DROP TYPE IF EXISTS {enum_name}')
