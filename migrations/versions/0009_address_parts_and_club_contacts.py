"""Member address in parts (street, postal code, city, country), club contact details, renewal setting.

The former one-line address is kept: the column is renamed to street_enc (same encryption context),
so existing values stay readable and can be split by hand.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('clubs', sa.Column('street', sa.String(length=200), nullable=True))
    op.add_column('clubs', sa.Column('city', sa.String(length=100), nullable=True))
    op.add_column('clubs', sa.Column('postal_code', sa.String(length=10), nullable=True))
    op.add_column('clubs', sa.Column('country', sa.String(length=2), server_default='SK', nullable=False))
    op.add_column('clubs', sa.Column('email', sa.String(length=254), nullable=True))
    op.add_column('clubs', sa.Column('phone', sa.String(length=50), nullable=True))
    op.add_column('clubs', sa.Column('web', sa.String(length=300), nullable=True))
    op.add_column('clubs', sa.Column('founded_on', sa.Date(), nullable=True))
    op.alter_column('members', 'address_enc', new_column_name='street_enc')
    op.add_column('members', sa.Column('city_enc', sa.LargeBinary(), nullable=True))
    op.add_column('members', sa.Column('postal_code_enc', sa.LargeBinary(), nullable=True))
    op.add_column('members', sa.Column('country', sa.String(length=2), server_default='SK', nullable=False))
    op.execute("INSERT INTO settings (key, value) VALUES ('renewal_window_days', '60') ON CONFLICT (key) DO NOTHING")


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'renewal_window_days'")
    op.drop_column('members', 'country')
    op.drop_column('members', 'postal_code_enc')
    op.drop_column('members', 'city_enc')
    op.alter_column('members', 'street_enc', new_column_name='address_enc')
    op.drop_column('clubs', 'founded_on')
    op.drop_column('clubs', 'web')
    op.drop_column('clubs', 'phone')
    op.drop_column('clubs', 'email')
    op.drop_column('clubs', 'country')
    op.drop_column('clubs', 'postal_code')
    op.drop_column('clubs', 'city')
    op.drop_column('clubs', 'street')
