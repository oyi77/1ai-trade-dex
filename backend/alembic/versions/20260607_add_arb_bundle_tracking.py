"""Add arb bundle tracking columns to trades

Revision ID: add_arb_bundle_tracking
Revises: add_journal_fields
Create Date: 2026-06-07
"""

from alembic import op
import sqlalchemy as sa

revision = "add_arb_bundle_tracking"
down_revision = "add_journal_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("trades", sa.Column("arb_bundle_id", sa.String(), nullable=True))
    op.create_index("ix_trades_arb_bundle_id", "trades", ["arb_bundle_id"])
    op.add_column("trades", sa.Column("arb_leg_index", sa.Integer(), nullable=True))
    op.add_column("trades", sa.Column("arb_leg_count", sa.Integer(), nullable=True))


def downgrade():
    op.drop_index("ix_trades_arb_bundle_id", table_name="trades")
    op.drop_column("trades", "arb_leg_count")
    op.drop_column("trades", "arb_leg_index")
    op.drop_column("trades", "arb_bundle_id")
