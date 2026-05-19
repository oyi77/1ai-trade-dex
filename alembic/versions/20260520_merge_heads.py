"""merge heads

Revision ID: merge_heads_001
Revises: 20260519_merge_and_add_journal, wallet_recon_001, a1b2c3d4misc0
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa

revision = 'merge_heads_001'
down_revision = None
branch_labels = ('merge_heads_001',)
depends_on = (
    '20260519_merge_and_add_journal',
    'wallet_recon_001',
    'a1b2c3d4misc0',
)


def upgrade():
    pass


def downgrade():
    pass
