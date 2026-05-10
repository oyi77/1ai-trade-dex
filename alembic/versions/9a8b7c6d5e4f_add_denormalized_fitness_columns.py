"""add denormalized fitness columns to genome_registry + indexes

Adds native SQL columns to genome_registry for efficient querying
of composite fitness metrics (previously only stored in fitness_json).

Also adds missing composite indexes to genome_shadow_trade for
forensics and lifecycle queries.

Revision ID: 9a8b7c6d5e4f
Revises: 1badad08bfb2
Create Date: 2026-05-10 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9a8b7c6d5e4f"
down_revision: Union[str, Sequence[str], None] = "1badad08bfb2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # genome_registry: denormalized fitness columns + composite indexes
    with op.batch_alter_table("genome_registry") as batch_op:
        batch_op.add_column(sa.Column("fitness_score", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("fitness_updated_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("total_pnl", sa.Float(), nullable=True, server_default="0.0"))
        batch_op.add_column(sa.Column("win_rate", sa.Float(), nullable=True, server_default="0.0"))
        batch_op.add_column(sa.Column("sharpe_ratio", sa.Float(), nullable=True, server_default="0.0"))
        batch_op.add_column(sa.Column("max_drawdown_pct", sa.Float(), nullable=True, server_default="0.0"))
        batch_op.add_column(sa.Column("trade_count", sa.Integer(), nullable=True, server_default="0"))
        batch_op.add_column(sa.Column("last_evaluated_at", sa.DateTime(), nullable=True))
        batch_op.create_index("idx_genome_stage_score", ["stage", "fitness_score"])
        batch_op.create_index("idx_genome_stage_winrate", ["stage", "win_rate"])
        batch_op.create_index("idx_genome_archetype_stage", ["archetype", "stage"])

    # genome_shadow_trade: forensics and lifecycle indexes
    with op.batch_alter_table("genome_shadow_trade") as batch_op:
        batch_op.create_index("ix_shadow_genome_settled", ["genome_id", "settled"])
        batch_op.create_index("ix_shadow_timestamp", ["timestamp"])
        batch_op.create_index("ix_genome_shadow_trade_signal_data", ["signal_data"])


def downgrade() -> None:
    # genome_shadow_trade indexes
    with op.batch_alter_table("genome_shadow_trade") as batch_op:
        batch_op.drop_index("ix_genome_shadow_trade_signal_data")
        batch_op.drop_index("ix_shadow_timestamp")
        batch_op.drop_index("ix_shadow_genome_settled")

    # genome_registry indexes
    with op.batch_alter_table("genome_registry") as batch_op:
        batch_op.drop_index("idx_genome_archetype_stage")
        batch_op.drop_index("idx_genome_stage_winrate")
        batch_op.drop_index("idx_genome_stage_score")

    # genome_registry columns
    with op.batch_alter_table("genome_registry") as batch_op:
        batch_op.drop_column("last_evaluated_at")
        batch_op.drop_column("trade_count")
        batch_op.drop_column("max_drawdown_pct")
        batch_op.drop_column("sharpe_ratio")
        batch_op.drop_column("win_rate")
        batch_op.drop_column("total_pnl")
        batch_op.drop_column("fitness_updated_at")
        batch_op.drop_column("fitness_score")
