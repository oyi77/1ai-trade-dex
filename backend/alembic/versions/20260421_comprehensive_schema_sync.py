"""comprehensive schema sync

Revision ID: 20260421_schema_sync
Revises: 882388989398
Create Date: 2026-04-21 05:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '20260421_schema_sync'
down_revision = '882388989398'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add missing indexes and foreign key constraints identified in schema audit (Task 2, Task 11)."""

    # Enable foreign key enforcement for SQLite
    try:
        from sqlalchemy import create_engine
        from backend.config import settings
        engine = create_engine(settings.DATABASE_URL)
        if 'sqlite' in settings.DATABASE_URL:
            with engine.connect() as conn:
                conn.execute(sa.text("PRAGMA foreign_keys=ON"))
    except Exception as e:
        print(f"Could not enable foreign keys: {e}")

    # Add indexes
    try:
        op.create_index('ix_trades_settled_mode', 'trades', ['settled', 'trading_mode'], unique=False)
    except Exception as e:
        print(f"Index ix_trades_settled_mode already exists or error: {e}")

    try:
        op.create_index('ix_trades_ticker_settled', 'trades', ['market_ticker', 'settled'], unique=False)
    except Exception as e:
        print(f"Index ix_trades_ticker_settled already exists or error: {e}")

    try:
        op.create_index('idx_trades_blockchain_verified', 'trades', ['blockchain_verified'], unique=False)
    except Exception as e:
        print(f"Index idx_trades_blockchain_verified already exists or error: {e}")

    try:
        op.create_index('idx_trades_clob_order_id', 'trades', ['clob_order_id'], unique=False)
    except Exception as e:
        print(f"Index idx_trades_clob_order_id already exists or error: {e}")

    try:
        op.create_index('ix_settlement_events_trade_id', 'settlement_events', ['trade_id'], unique=False)
    except Exception as e:
        print(f"Index ix_settlement_events_trade_id already exists or error: {e}")

    try:
        op.create_index('ix_pending_approvals_status', 'pending_approvals', ['status'], unique=False)
    except Exception as e:
        print(f"Index ix_pending_approvals_status already exists or error: {e}")

    # Add foreign key constraints
    # trade_context.trade_id → trades.id (CASCADE DELETE)
    try:
        op.create_foreign_key(
            'fk_trade_context_trade_id',
            'trade_context', 'trades',
            ['trade_id'], ['id'],
            ondelete='CASCADE'
        )
    except Exception as e:
        print(f"Foreign key fk_trade_context_trade_id already exists or error: {e}")

    # trade_context.signal_id → signals.id (SET NULL) - Note: signal_id not in TradeContext model
    # Skipping this constraint as signal_id is in Trade model, not TradeContext

    # trades.signal_id → signals.id (SET NULL)
    try:
        op.create_foreign_key(
            'fk_trades_signal_id',
            'trades', 'signals',
            ['signal_id'], ['id'],
            ondelete='SET NULL'
        )
    except Exception as e:
        print(f"Foreign key fk_trades_signal_id already exists or error: {e}")

    # settlement_events.trade_id → trades.id (CASCADE DELETE)
    try:
        op.create_foreign_key(
            'fk_settlement_events_trade_id',
            'settlement_events', 'trades',
            ['trade_id'], ['id'],
            ondelete='CASCADE'
        )
    except Exception as e:
        print(f"Foreign key fk_settlement_events_trade_id already exists or error: {e}")

    # Performance indexes from Task 9 - frequently queried columns
    try:
        op.create_index('ix_trades_market_ticker', 'trades', ['market_ticker'], unique=False)
    except Exception as e:
        print(f"Index ix_trades_market_ticker already exists or error: {e}")

    try:
        op.create_index('ix_trades_trading_mode', 'trades', ['trading_mode'], unique=False)
    except Exception as e:
        print(f"Index ix_trades_trading_mode already exists or error: {e}")

    try:
        op.create_index('ix_trades_market_end_date', 'trades', ['market_end_date'], unique=False)
    except Exception as e:
        print(f"Index ix_trades_market_end_date already exists or error: {e}")

    try:
        op.create_index('ix_trades_source', 'trades', ['source'], unique=False)
    except Exception as e:
        print(f"Index ix_trades_source already exists or error: {e}")

    try:
        op.create_index('ix_bot_state_last_sync_at', 'bot_state', ['last_sync_at'], unique=False)
    except Exception as e:
        print(f"Index ix_bot_state_last_sync_at already exists or error: {e}")

    # Composite index for stats aggregation queries (trading_mode, settled, result)
    try:
        op.create_index('ix_trades_mode_settled_result', 'trades', ['trading_mode', 'settled', 'result'], unique=False)
    except Exception as e:
        print(f"Index ix_trades_mode_settled_result already exists or error: {e}")


def downgrade() -> None:
    """Remove foreign keys and indexes added in upgrade."""

    try:
        op.drop_constraint('fk_settlement_events_trade_id', 'settlement_events', type_='foreignkey')
    except Exception:
        pass

    try:
        op.drop_constraint('fk_trades_signal_id', 'trades', type_='foreignkey')
    except Exception:
        pass

    try:
        op.drop_constraint('fk_trade_context_trade_id', 'trade_context', type_='foreignkey')
    except Exception:
        pass

    try:
        op.drop_index('ix_pending_approvals_status', table_name='pending_approvals')
    except Exception:
        pass

    try:
        op.drop_index('ix_settlement_events_trade_id', table_name='settlement_events')
    except Exception:
        pass

    try:
        op.drop_index('idx_trades_clob_order_id', table_name='trades')
    except Exception:
        pass

    try:
        op.drop_index('idx_trades_blockchain_verified', table_name='trades')
    except Exception:
        pass

    try:
        op.drop_index('ix_trades_ticker_settled', table_name='trades')
    except Exception:
        pass

    try:
        op.drop_index('ix_trades_settled_mode', table_name='trades')
    except Exception:
        pass

    try:
        op.drop_index('ix_bot_state_last_sync_at', table_name='bot_state')
    except Exception:
        pass

    try:
        op.drop_index('ix_trades_source', table_name='trades')
    except Exception:
        pass

    try:
        op.drop_index('ix_trades_market_end_date', table_name='trades')
    except Exception:
        pass

    try:
        op.drop_index('ix_trades_trading_mode', table_name='trades')
    except Exception:
        pass

    try:
        op.drop_index('ix_trades_market_ticker', table_name='trades')
    except Exception:
        pass

    try:
        op.drop_index('ix_pending_approvals_status', table_name='pending_approvals')
    except Exception:
        pass

    try:
        op.drop_index('ix_settlement_events_trade_id', table_name='settlement_events')
    except Exception:
        pass

    try:
        op.drop_index('idx_trades_clob_order_id', table_name='trades')
    except Exception:
        pass

    try:
        op.drop_index('idx_trades_blockchain_verified', table_name='trades')
    except Exception:
        pass

    try:
        op.drop_index('ix_trades_ticker_settled', table_name='trades')
    except Exception:
        pass

    try:
        op.drop_index('ix_trades_settled_mode', table_name='trades')
    except Exception:
        pass
