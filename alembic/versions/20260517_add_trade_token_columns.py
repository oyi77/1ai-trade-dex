"""
Add token_id and condition_id columns to trades table.

Allows settlement resolution to use token_id for Gamma/CLOB API lookups
instead of relying on market slugs (which often fail for closed markets).
"""

from typing import Sequence
from alembic import op
import sqlalchemy as sa

revision = "20260517_add_trade_token_columns"
down_revision = "20260507_create_clob_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("token_id", sa.String(), nullable=True))
    op.add_column("trades", sa.Column("condition_id", sa.String(), nullable=True))
    op.create_index("ix_trades_token_id", "trades", ["token_id"])
    op.create_index("ix_trades_condition_id", "trades", ["condition_id"])


def downgrade() -> None:
    op.drop_index("ix_trades_condition_id", table_name="trades")
    op.drop_index("ix_trades_token_id", table_name="trades")
    op.drop_column("trades", "condition_id")
    op.drop_column("trades", "token_id")

