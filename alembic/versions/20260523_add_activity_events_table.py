"""Add activity_events table for persistent event tracking.

Revision ID: activity_events_001
Revises: add_protected_001
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa

revision = "activity_events_001"
down_revision = "add_protected_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "activity_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False, index=True),
        sa.Column("event_type", sa.String(), nullable=False, index=True),
        sa.Column("wallet_address", sa.String(), nullable=False, index=True),
        sa.Column("platform", sa.String(), nullable=False, index=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("token", sa.String(), nullable=True, server_default="USDC"),
        sa.Column("tx_hash", sa.String(), nullable=True, index=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False, index=True),
        sa.Column("trade_id", sa.String(), nullable=True, index=True),
        sa.Column("order_id", sa.String(), nullable=True),
        sa.Column("side", sa.String(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("fee", sa.Float(), nullable=True),
        sa.Column("pnl", sa.Float(), nullable=True),
        sa.Column("market_ticker", sa.String(), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_table("activity_events")