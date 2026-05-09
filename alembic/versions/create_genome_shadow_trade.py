"""create genome_shadow_trade table

Revision ID: create_genome_shadow_trade
Revises: create_genome_performance
Create Date: 2026-05-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'create_genome_shadow_trade'
down_revision: Union[str, Sequence[str], None] = 'create_genome_performance'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'genome_shadow_trade',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('genome_id', sa.String(36), nullable=False, index=True),
        sa.Column('genome_registry_id', sa.Integer(), nullable=True, index=True),
        sa.Column('market_ticker', sa.String(200), nullable=False),
        sa.Column('direction', sa.String(10), nullable=False),
        sa.Column('entry_price', sa.Float(), nullable=False),
        sa.Column('size', sa.Float(), nullable=False),
        sa.Column('model_probability', sa.Float(), nullable=True),
        sa.Column('settled', sa.Boolean(), nullable=False, default=False),
        sa.Column('settlement_price', sa.Float(), nullable=True),
        sa.Column('exit_price', sa.Float(), nullable=True),
        sa.Column('pnl', sa.Float(), nullable=True),
        sa.Column('result', sa.String(10), nullable=True),
        sa.Column('predicted_outcome', sa.Float(), nullable=True),
        sa.Column('actual_outcome', sa.Float(), nullable=True),
        sa.Column('accuracy_score', sa.Float(), nullable=True),
        sa.Column('signal_data', sa.JSON(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('settled_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_genome_shadow_trade_genome_id', 'genome_shadow_trade', ['genome_id'])
    op.create_index('ix_genome_shadow_trade_genome_registry_id', 'genome_shadow_trade', ['genome_registry_id'])


def downgrade() -> None:
    op.drop_index('ix_genome_shadow_trade_genome_registry_id', table_name='genome_shadow_trade')
    op.drop_index('ix_genome_shadow_trade_genome_id', table_name='genome_shadow_trade')
    op.drop_table('genome_shadow_trade')