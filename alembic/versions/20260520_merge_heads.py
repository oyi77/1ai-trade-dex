"""merge heads

Revision ID: merge_heads_001
Revises: 20260519_merge_and_add_journal, wallet_recon_001, a1b2c3d4misc0
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa

revision = "merge_heads_001"
down_revision = (
    "20260519_merge_and_add_journal",
    "wallet_recon_001",
    "a1b2c3d4misc0",
)
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
