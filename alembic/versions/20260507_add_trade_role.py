"""add trade role column

Revision ID: 20260507_add_trade_role
Revises: 20260507_create_clob_events
Create Date: 2026-05-07
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '20260507_add_trade_role'
down_revision = '20260507_create_clob_events'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('trades', sa.Column('role', sa.String(), server_default='unknown', nullable=False))

def downgrade():
    op.drop_column('trades', 'role')
