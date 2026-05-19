"""add rehab_allocation_pct to strategy_config

Revision ID: rehab_alloc_001
Revises: head
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "rehab_alloc_001"
down_revision = None  # will be set by merge head resolution
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_config",
        sa.Column("rehab_allocation_pct", sa.Float(), nullable=True, default=None),
    )


def downgrade() -> None:
    op.drop_column("strategy_config", "rehab_allocation_pct")
