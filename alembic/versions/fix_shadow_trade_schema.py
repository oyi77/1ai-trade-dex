"""Fix shadow_trade schema corruption

Revision ID: fix_shadow_trade_schema
Revises: 2c10e32ae3fa
Create Date: 2026-05-14 21:30:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'fix_shadow_trade_schema'
down_revision = '2c10e32ae3fa'
branch_labels = None
depends_on = None

def upgrade() -> None:
    """No-op: shadow_trade was manually fixed via psql."""
    pass

def downgrade() -> None:
    pass
