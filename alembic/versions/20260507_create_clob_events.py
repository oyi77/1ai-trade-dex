"""Create clob_events table

Revision ID: 20260507_create_clob_events
Revises: f993aa61ad7d
Create Date: 2026-05-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '20260507_create_clob_events'
down_revision = 'f993aa61ad7d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'clob_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.String(), nullable=False),
        sa.Column('maker', sa.String(), nullable=False),
        sa.Column('taker', sa.String(), nullable=False),
        sa.Column('market_id', sa.String(), nullable=False),
        sa.Column('side', sa.String(), nullable=False),
        sa.Column('size', sa.Float(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('fee', sa.Float(), nullable=False),
        sa.Column('block_number', sa.Integer(), nullable=False),
        sa.Column('tx_hash', sa.String(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tx_hash', name='uq_clob_events_tx_hash'),
    )
    op.create_index('ix_clob_events_id', 'clob_events', ['id'], unique=False)
    op.create_index('ix_clob_events_market_id', 'clob_events', ['market_id'], unique=False)
    op.create_index('ix_clob_events_block_number', 'clob_events', ['block_number'], unique=False)
    op.create_index('ix_clob_events_timestamp', 'clob_events', ['timestamp'], unique=False)
    op.create_index('ix_clob_events_tx_hash', 'clob_events', ['tx_hash'], unique=True)


def downgrade():
    op.drop_index('ix_clob_events_tx_hash', table_name='clob_events')
    op.drop_index('ix_clob_events_timestamp', table_name='clob_events')
    op.drop_index('ix_clob_events_block_number', table_name='clob_events')
    op.drop_index('ix_clob_events_market_id', table_name='clob_events')
    op.drop_index('ix_clob_events_id', table_name='clob_events')
    op.drop_table('clob_events')
