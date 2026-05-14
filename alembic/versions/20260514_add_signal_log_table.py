"""add signal_log table with tuned composite indexes

Revision ID: 20260514_add_signal_log
Revises: 4e6c9a19200f
Create Date: 2026-05-14

Performance notes:
    - 4 indexes are intentional; each maps to a measured query pattern.
    - On PG, ix_signal_log_filled_pnl is a partial-style index used by the
      settlement worker; on SQLite it falls back to a normal composite.
"""
from alembic import op
import sqlalchemy as sa


revision = '20260514_add_signal_log'
down_revision = '4e6c9a19200f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'signal_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'timestamp',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.Column('market_id', sa.String(), nullable=False),
        sa.Column('market_mid', sa.Float(), nullable=False),
        sa.Column('btc_spot', sa.Float(), nullable=True),
        sa.Column('rsi', sa.Float(), nullable=True),
        sa.Column('momentum_5m', sa.Float(), nullable=True),
        sa.Column('vwap_deviation', sa.Float(), nullable=True),
        sa.Column('sma_crossover', sa.Float(), nullable=True),
        sa.Column('proposed_side', sa.String(), nullable=True),
        sa.Column('edge_pp', sa.Float(), nullable=True),
        sa.Column('oracle_implied', sa.Float(), nullable=True),
        sa.Column('filled', sa.Boolean(), nullable=True),
        sa.Column('pnl', sa.Float(), nullable=True),
        sa.Column(
            'strategy',
            sa.String(),
            nullable=False,
            server_default=sa.text("'btc_oracle'"),
        ),
    )

    # Single-column timestamp index (full-table chronological scans / ORDER BY)
    op.create_index(
        'ix_signal_log_timestamp',
        'signal_log',
        ['timestamp'],
    )

    # Calibration: per-strategy price-bucket scans
    op.create_index(
        'ix_signal_log_strategy_market_mid',
        'signal_log',
        ['strategy', 'market_mid'],
    )

    # Per-market time series
    op.create_index(
        'ix_signal_log_market_id_timestamp',
        'signal_log',
        ['market_id', 'timestamp'],
    )

    # Recent activity per strategy
    op.create_index(
        'ix_signal_log_strategy_timestamp',
        'signal_log',
        ['strategy', 'timestamp'],
    )

    # Settlement worker: filled signals awaiting pnl backfill.
    # On Postgres, use a partial index for selectivity.
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute(
            "CREATE INDEX ix_signal_log_filled_pnl "
            "ON signal_log (filled, pnl) "
            "WHERE filled IS TRUE AND pnl IS NULL"
        )
    else:
        op.create_index(
            'ix_signal_log_filled_pnl',
            'signal_log',
            ['filled', 'pnl'],
        )


def downgrade() -> None:
    op.drop_index('ix_signal_log_filled_pnl', table_name='signal_log')
    op.drop_index('ix_signal_log_strategy_timestamp', table_name='signal_log')
    op.drop_index('ix_signal_log_market_id_timestamp', table_name='signal_log')
    op.drop_index('ix_signal_log_strategy_market_mid', table_name='signal_log')
    op.drop_index('ix_signal_log_timestamp', table_name='signal_log')
    op.drop_table('signal_log')
