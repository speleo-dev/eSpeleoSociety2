"""eCP application: the SSS card format chosen by the applicant (pdf / png); empty = no card.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ecp_applications", sa.Column("card_format", sa.String(3), nullable=True))
    op.execute("UPDATE ecp_applications SET card_format = 'pdf' WHERE wants_card")


def downgrade() -> None:
    op.drop_column("ecp_applications", "card_format")
