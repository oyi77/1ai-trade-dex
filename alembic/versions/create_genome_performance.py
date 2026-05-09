"""create genome_performance table

Revision ID: create_genome_performance
Revises: add_calibration_price_bucket
Create Date: 2026-05-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'create_genome_performance'
down_revision: Union[str, Sequence[str], None] = 'add_calibration_price_bucket'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'genome_performance',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('genome_id', sa.String(36), nullable=False, index=True),
        sa.Column('trades', sa.JSON(), nullable=True, default=list),
        sa.Column('total_trades', sa.Integer(), nullable=False, default=0),
        sa.Column('winning_trades', sa.Integer(), nullable=False, default=0),
        sa.Column('losing_trades', sa.Integer(), nullable=False, default=0),
        sa.Column('total_pnl', sa.Float(), nullable=False, default=0.0),
        sa.Column('avg_pnl', sa.Float(), nullable=False, default=0.0),
        sa.Column('avg_win', sa.Float(), nullable=False, default=0.0),
        sa.Column('avg_loss', sa.Float(), nullable=False, default=0.0),
        sa.Column('sharpe_ratio', sa.Float(), nullable=False, default=0.0),
        sa.Column('max_drawdown_pct', sa.Float(), nullable=False, default=0.0),
        sa.Column('volatility', sa.Float(), nullable=False, default=0.0),
        sa.Column('profit_factor', sa.Float(), nullable=False, default=0.0),
        sa.Column('last_updated', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_genome_performance_genome_id', 'genome_performance', ['genome_id'])


def downgrade() -> None:
    op.drop_index('ix_genome_performance_genome_id', table_name='genome_performance')
    op.drop_table('genome_performance')