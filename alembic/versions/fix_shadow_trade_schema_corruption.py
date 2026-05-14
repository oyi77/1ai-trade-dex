"""Fix shadow_trade schema corruption

Revision ID: fix_shadow_trade_schema_corruption
Revises: 2c10e32ae3fa
Create Date: 2026-05-14 21:30:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'fix_shadow_trade_schema_corruption'
down_revision = '2c10e32ae3fa'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Drop corrupted table
    op.drop_table('shadow_trade')
    
    # Recreate with correct schema
    op.create_table(
        'shadow_trade',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column('genome_id', sa.String(255), nullable=False, index=True),
        sa.Column('strategy_name', sa.String(255), nullable=False),
        sa.Column('market_id', sa.String(255), nullable=False),
        sa.Column('entry_price', sa.Float(), nullable=False),
        sa.Column('target_price', sa.Float(), nullable=False),
        sa.Column('direction', sa.String(10), nullable=False),
        sa.Column('size_usd', sa.Float(), nullable=False),
        sa.Column('leverage', sa.Float(), nullable=False),
        sa.Column('entry_signal', sa.String(255), nullable=False),
        sa.Column('exit_signal', sa.String(255), nullable=True),
        sa.Column('stage', sa.String(50), nullable=False, index=True),
        sa.Column('outcome', sa.String(50), nullable=True),
        sa.Column('pnl_usd', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['genome_id'], ['genome_registry.genome_id'], ondelete='CASCADE'),
    )
    op.create_index('ix_shadow_trade_genome_id', 'shadow_trade', ['genome_id'])
    op.create_index('ix_shadow_trade_strategy_name', 'shadow_trade', ['strategy_name'])
    op.create_index('ix_shadow_trade_stage', 'shadow_trade', ['stage'])

def downgrade() -> None:
    op.drop_table('shadow_trade')
    # Restore corrupted version (for rollback only)
    op.create_table(
        'shadow_trade',
        sa.Column('id', sa.Integer(), nullable=False),
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
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('metadata_json', sa.TEXT(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
