"""Tasks waiting for an administrator ("Na vybavenie"); backfill from the current state.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('tasks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('task_type', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('member_id', sa.UUID(), nullable=False),
    sa.Column('membership_id', sa.UUID(), nullable=True),
    sa.Column('club_id', sa.UUID(), nullable=True),
    sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('requested_by', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_by', sa.String(length=64), nullable=True),
    sa.Column('resolution', sa.String(length=32), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['club_id'], ['clubs.id'], ),
    sa.ForeignKeyConstraint(['member_id'], ['members.id'], ),
    sa.ForeignKeyConstraint(['membership_id'], ['memberships.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tasks_member_id'), 'tasks', ['member_id'], unique=False)
    op.create_index('ix_tasks_open', 'tasks', ['status', 'task_type'], unique=False)
    op.create_index('uq_tasks_open_activation', 'tasks', ['membership_id'], unique=True, postgresql_where=sa.text("status = 'open' AND task_type = 'member_activation'"))
    op.create_index('uq_tasks_open_sss_decision', 'tasks', ['member_id'], unique=True, postgresql_where=sa.text("status = 'open' AND task_type = 'sss_decision'"))

    # Backfill: proposed members waiting for activation.
    op.execute("""
        INSERT INTO tasks (id, task_type, status, member_id, membership_id, club_id, context, requested_by, created_at)
        SELECT gen_random_uuid(), 'member_activation', 'open', m.member_id, m.id, m.club_id,
               CASE WHEN EXISTS (
                   SELECT 1 FROM memberships p
                   WHERE p.member_id = m.member_id AND p.club_id = m.club_id
                     AND p.valid_to = m.valid_from AND p.status = 'candidate'
               ) THEN '{"from_status": "candidate"}'::jsonb END,
               m.created_by, m.created_at
        FROM memberships m
        WHERE m.valid_to IS NULL AND m.status = 'pending_activation'
    """)
    # Backfill: members without any club waiting for the presidium's decision.
    op.execute("""
        INSERT INTO tasks (id, task_type, status, member_id, club_id, requested_by)
        SELECT gen_random_uuid(), 'sss_decision', 'open', mb.id,
               (SELECT x.club_id FROM memberships x WHERE x.member_id = mb.id ORDER BY x.valid_to DESC NULLS LAST LIMIT 1),
               'system'
        FROM members mb
        WHERE mb.expelled_at IS NULL AND mb.sss_ended_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM memberships o WHERE o.member_id = mb.id AND o.valid_to IS NULL)
          AND EXISTS (SELECT 1 FROM memberships a WHERE a.member_id = mb.id)
    """)


def downgrade() -> None:
    op.drop_index('uq_tasks_open_sss_decision', table_name='tasks', postgresql_where=sa.text("status = 'open' AND task_type = 'sss_decision'"))
    op.drop_index('uq_tasks_open_activation', table_name='tasks', postgresql_where=sa.text("status = 'open' AND task_type = 'member_activation'"))
    op.drop_index('ix_tasks_open', table_name='tasks')
    op.drop_index(op.f('ix_tasks_member_id'), table_name='tasks')
    op.drop_table('tasks')
