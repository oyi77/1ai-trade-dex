"""Create shadow_trade table

Revision ID: 20260504_create_shadow_trade
Revises: 20260504_add_trade_fill_price_and_ratio
Create Date: 2026-05-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260504_create_shadow_trade'
down_revision = '20260504_add_trade_fill_price_and_ratio'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'shadow_trade',
        sa.Column('id', sa.INTEGER(), nullable=False),
        sa.Column('genome_id', sa.TEXT(), nullable=False),
        sa.Column('strategy_name', sa.TEXT(), nullable=False),
        sa.Column('market_id', sa.TEXT(), nullable=False),
        sa.Column('entry_price', sa.REAL(), nullable=False),
        sa.Column('target_price', sa.REAL(), nullable=False),
        sa.Column('direction', sa.TEXT(), nullable=False),
        sa.Column('size_usd', sa.REAL(), nullable=False),
        sa.Column('leverage', sa.REAL(), nullable=False),
        sa.Column('entry_signal', sa.TEXT(), nullable=False),
        sa.Column('exit_signal', sa.TEXT(), nullable=True),
        sa.Column('stage', sa.TEXT(), nullable=False),
        sa.Column('outcome', sa.TEXT(), nullable=True),
        sa.Column('pnl_usd', sa.REAL(), nullable=True),
        sa.Column('created_at', sa.DATETIME(), nullable=False),
        sa.Column('updated_at', sa.DATETIME(), nullable=False),
        sa.Column('metadata_json', sa.TEXT(), nullable=True),
        sa.ForeignKeyConstraint(['genome_id'], ['genome_registry.genome_id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_shadow_trade_genome_id'), 'shadow_trade', ['genome_id'], unique=False)
    op.create_index(op.f('ix_shadow_trade_strategy_name'), 'shadow_trade', ['strategy_name'], unique=False)
    op.create_index(op.f('ix_shadow_trade_stage'), 'shadow_trade', ['stage'], unique=False)

def downgrade():
    op.drop_index(op.f('ix_shadow_trade_stage'), table_name='shadow_trade')
    op.drop_index(op.f('ix_shadow_trade_strategy_name'), table_name='shadow_trade')
    op.drop_index(op.f('ix_shadow_trade_genome_id'), table_name='shadow_trade')
    op.drop_table('shadow_trade')
