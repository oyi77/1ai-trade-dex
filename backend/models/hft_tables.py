"""HFT Database Models — signals, executions, and performance tracking."""

from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, DateTime, Index, Text

from backend.models.database import Base


class HFTSignal(Base):
    __tablename__ = "hft_signals"

    signal_id = Column(String(64), primary_key=True)
    market_id = Column(String(128), index=True)
    ticker = Column(String(256))
    signal_type = Column(String(32))
    edge = Column(Float)
    confidence = Column(Float)
    latency_ms = Column(Float)
    yes_price = Column(Float)
    no_price = Column(Float)
    volume = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    metadata_json = Column(Text, default="{}")

    __table_args__ = (
        Index("ix_hft_signals_market_created", "market_id", "created_at"),
        Index("ix_hft_signals_type_created", "signal_type", "created_at"),
    )


class HFTExecution(Base):
    __tablename__ = "hft_executions"

    execution_id = Column(String(64), primary_key=True)
    signal_id = Column(String(64), index=True)
    order_id = Column(String(128))
    side = Column(String(8))
    size = Column(Float)
    price = Column(Float)
    execution_latency_ms = Column(Float)
    status = Column(String(32), index=True)
    error = Column(Text)
    market_id = Column(String(128), index=True)
    profit = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_hft_executions_market_status", "market_id", "status"),
        Index("ix_hft_executions_signal", "signal_id"),
    )


class HFTPerformance(Base):
    __tablename__ = "hft_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name = Column(String(64), index=True)
    period = Column(String(16))
    total_signals = Column(Integer, default=0)
    total_executions = Column(Integer, default=0)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    pnl = Column(Float, default=0.0)
    avg_latency_ms = Column(Float, default=0.0)
    max_latency_ms = Column(Float, default=0.0)
    sharpe_ratio = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("ix_hft_perf_strategy_period", "strategy_name", "period"),)


def create_hft_tables(engine):
    """Create all HFT tables. Call once on startup."""
    Base.metadata.create_all(bind=engine)
