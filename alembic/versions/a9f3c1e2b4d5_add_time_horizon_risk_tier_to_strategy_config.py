"""add time_horizon and risk_tier to strategy_config

Revision ID: a9f3c1e2b4d5
Revises: f993aa61ad7d
Create Date: 2026-05-09 00:00:00.000000

Adds two classification columns to strategy_config:
  - time_horizon: short / mid / long  (default "mid")
  - risk_tier: safe / conservative / moderate / aggressive / extreme / crazy  (default "moderate")

These drive tier-aware bankroll allocation and relaxed fronttest gates for
crazy-tier strategies.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a9f3c1e2b4d5'
down_revision: Union[str, Sequence[str], None] = 'f993aa61ad7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('strategy_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('time_horizon', sa.String(), nullable=True, server_default='mid'))
        batch_op.add_column(sa.Column('risk_tier', sa.String(), nullable=True, server_default='moderate'))


def downgrade() -> None:
    with op.batch_alter_table('strategy_config', schema=None) as batch_op:
        batch_op.drop_column('risk_tier')
        batch_op.drop_column('time_horizon')
