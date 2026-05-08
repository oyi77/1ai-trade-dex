"""
Database models for backtesting results.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    JSON,
    Boolean,
    Text,
    ForeignKey,
    Index
)
from sqlalchemy.orm import relationship
from backend.models.database import Base

class BacktestRun(Base):
    """Stores information about each backtest run."""

    __tablename__ = "backtest_runs"

    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String, nullable=False, index=True)

    # Test parameters
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    initial_bankroll = Column(Float, nullable=False)
    params = Column(JSON, default=dict)

    # Results summary
    final_equity = Column(Float, nullable=False)
    total_pnl = Column(Float, nullable=False)
    total_return_pct = Column(Float, nullable=False)
    win_rate = Column(Float, nullable=False)
    total_trades = Column(Integer, nullable=False)
    winning_trades = Column(Integer, nullable=False)
    losing_trades = Column(Integer, nullable=False)
    sharpe_ratio = Column(Float, nullable=True)

    # Status
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    # Relationship to individual trades
    trades = relationship("BacktestTrade", back_populates="run", cascade="all, delete-orphan")

class BacktestTrade(Base):
    """Stores individual trades from a backtest run."""

    __tablename__ = "backtest_trades"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("backtest_runs.id"), nullable=False, index=True)

    # Trade details
    signal_id = Column(Integer, nullable=True)  # Reference to original signal
    market_ticker = Column(String, nullable=False)
    platform = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    size = Column(Float, nullable=False)
    pnl = Column(Float, nullable=False)
    result = Column(String, nullable=False)  # 'win', 'loss', 'pending'

    # Performance metrics
    edge_at_entry = Column(Float, nullable=False)
    market_probability_at_entry = Column(Float, nullable=True)
    model_probability_at_entry = Column(Float, nullable=True)

    # Timestamps
    timestamp = Column(DateTime, nullable=False)
    executed = Column(Boolean, default=False)

    # Relationship
    run = relationship("BacktestRun", back_populates="trades")

# Indexes for performance
Index('idx_backtest_runs_strategy_date', 'strategy_name', 'start_date', 'end_date')
Index('idx_backtest_trades_run_result', 'run_id', 'result')
Index('idx_backtest_trades_timestamp', 'timestamp')
