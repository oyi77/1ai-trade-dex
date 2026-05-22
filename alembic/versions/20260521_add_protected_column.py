"""Add protected column to strategy_config

Revision ID: add_protected_001
Revises: merge_heads_001
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa

revision = "add_protected_001"
down_revision = "merge_heads_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "strategy_config",
        sa.Column("protected", sa.Boolean(), nullable=True, server_default="false"),
    )
    # Seed protected strategies
    op.execute(
        "UPDATE strategy_config SET protected = true "
        "WHERE strategy_name IN ('copy_trader', 'weather_emos', 'agi_orchestrator', 'btc_oracle', 'crypto_oracle')"
    )


def downgrade():
    op.drop_column("strategy_config", "protected")
