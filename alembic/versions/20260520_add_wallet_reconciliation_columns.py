"""add wallet reconciliation columns to bot_state

Revision ID: wallet_recon_001
Revises: rehab_alloc_001
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa

revision = "wallet_recon_001"
down_revision = "rehab_alloc_001"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _column_exists("bot_state", "total_deposits"):
        op.add_column("bot_state", sa.Column("total_deposits", sa.Float(), server_default="0.0"))
    if not _column_exists("bot_state", "total_withdrawals"):
        op.add_column("bot_state", sa.Column("total_withdrawals", sa.Float(), server_default="0.0"))
    if not _column_exists("bot_state", "last_wallet_sync_at"):
        op.add_column("bot_state", sa.Column("last_wallet_sync_at", sa.DateTime(), nullable=True))
    if not _column_exists("bot_state", "wallet_pnl"):
        op.add_column("bot_state", sa.Column("wallet_pnl", sa.Float(), server_default="0.0"))


def downgrade() -> None:
    op.drop_column("bot_state", "wallet_pnl")
    op.drop_column("bot_state", "last_wallet_sync_at")
    op.drop_column("bot_state", "total_withdrawals")
    op.drop_column("bot_state", "total_deposits")
