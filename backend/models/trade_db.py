"""Domain model: trade — split from database.py.
Keeps backward compatibility via database.py re-exports.
"""
import json
from enum import Enum
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Boolean,
    JSON,
    Text,
    ForeignKey,
    Index,
    text,
)

from backend.models.engine import Base

class TradeRole(str, Enum):
    MAKER = "maker"
    TAKER = "taker"
    UNKNOWN = "unknown"


class Trade(Base):
    """Simulated and live trades for tracking P&L."""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(
        Integer,
        ForeignKey("signals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    market_ticker = Column(String, index=True)
    platform = Column(String)
    strategy = Column(String, nullable=True, index=True)
    trading_mode = Column(String, default="paper", index=True)
    market_type = Column(String, default="btc", index=True)  # "btc" or "weather"
    event_slug = Column(String, nullable=True)
    market_end_date = Column(DateTime, nullable=True)
    token_id = Column(String, nullable=True, index=True)
    condition_id = Column(String, nullable=True, index=True)

    direction = Column(String)  # "up" or "down"
    entry_price = Column(Float)
    size = Column(Float)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    source = Column(String, default="bot", index=True)  # "bot", "user", "import"
    role = Column(String(10), default="unknown", index=True)  # maker, taker, unknown
    maker_size = Column(Float, nullable=True)
    taker_size = Column(Float, nullable=True)
    clob_order_id = Column(String, nullable=True, index=True)
    clob_idempotency_key = Column(String, nullable=True)
    filled_size = Column(Float, nullable=True)
    fill_price = Column(Float, nullable=True)
    fill_ratio = Column(Float, nullable=True)
    fee = Column(Float, nullable=True)
    slippage = Column(Float, nullable=True)

    signal_source = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    model_probability = Column(Float, nullable=True)
    market_price_at_entry = Column(Float, nullable=True)
    edge_at_entry = Column(Float, nullable=True)
    data_quality_flags = Column(Text, nullable=True)

    blockchain_verified = Column(Boolean, default=False)
    settlement_source = Column(String, nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    external_import_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=True)

    settled = Column(Boolean, default=False)
    settlement_time = Column(DateTime, nullable=True)
    settlement_value = Column(Float, nullable=True)  # 1.0=Up won, 0.0=Down won
    result = Column(
        String, default="pending"
    )  # pending, win, loss, expired, push, closed
    pnl = Column(Float, nullable=True)

    # Arb bundle tracking for multi-leg arbitrage positions
    arb_bundle_id = Column(String, nullable=True, index=True)
    arb_leg_index = Column(Integer, nullable=True)
    arb_leg_count = Column(Integer, nullable=True)

    journal_notes = Column(Text, nullable=True)
    journal_tags = Column(JSON, nullable=True)  # list of tag strings


class HFTExecutionRecord(Base):
    """Audit trail for HFT strategy executions."""

    __tablename__ = "hft_execution_records"

    execution_id = Column(String, primary_key=True)
    signal_id = Column(String, index=True)
    order_id = Column(String, nullable=True)
    side = Column(String)  # "BUY" or "SELL"
    size = Column(Float)
    price = Column(Float)
    execution_latency_ms = Column(Float)
    status = Column(String)  # "pending", "filled", "failed", "queued", "cancelled"
    error = Column(String, nullable=True)
    timestamp = Column(Float)  # unix timestamp
    created_at = Column(
        DateTime, server_default=text("(CURRENT_TIMESTAMP)"), index=True
    )

    # Model performance tracking
    model_probability = Column(Float)
    market_price_at_entry = Column(Float)
    edge_at_entry = Column(Float)

    # Trading mode this trade was placed in
    trading_mode = Column(String, default="paper", index=True)
    role = Column(String, default="unknown", index=True)  # maker, taker, unknown

    # Strategy tracking
    strategy = Column(String, nullable=True)
    signal_source = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)

    # Partial fill tracking
    filled_size = Column(
        Float, nullable=True
    )  # actual fill amount, None = assumed full fill
    fill_price = Column(
        Float, nullable=True
    )  # actual fill price, None = assumed entry_price
    fill_ratio = Column(
        Float, nullable=True
    )  # fill_ratio = filled_size / size, None = assumed 1.0

    # On-chain order tracking (testnet / live modes)
    clob_order_id = Column(
        String, nullable=True
    )  # Order ID returned by Polymarket CLOB
    clob_idempotency_key = Column(
        String, nullable=True
    )  # UUID idempotency key per order attempt

    # Market end date for settlement tracking (when the market expires)
    market_end_date = Column(DateTime, nullable=True, index=True)

    # Fee and slippage tracking
    fee = Column(Float, nullable=True)
    slippage = Column(Float, nullable=True)

    # Reconciliation fields for blockchain sync
    source = Column(String, nullable=False, default="bot", index=True)
    blockchain_verified = Column(Boolean, nullable=False, default=False)
    settlement_source = Column(String, nullable=True, default=None)
    last_sync_at = Column(DateTime, nullable=True, default=None, index=True)
    external_import_at = Column(DateTime, nullable=True, default=None)



class TradeAttempt(Base):
    """Durable execution-attempt ledger for explaining why trades happen or stop."""

    __tablename__ = "trade_attempts"

    id = Column(Integer, primary_key=True, index=True)
    attempt_id = Column(String, nullable=False, unique=True, index=True)
    correlation_id = Column(String, nullable=False, index=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
    )

    strategy = Column(String, nullable=False, index=True)
    mode = Column(String, nullable=False, index=True)
    market_ticker = Column(String, nullable=False, index=True)
    platform = Column(String, nullable=True)
    direction = Column(String, nullable=True)
    decision = Column(String, nullable=True)

    status = Column(String, nullable=False, default="STARTED", index=True)
    phase = Column(String, nullable=False, default="created", index=True)
    reason_code = Column(String, nullable=False, default="ATTEMPT_STARTED", index=True)
    reason = Column(Text, nullable=True)

    confidence = Column(Float, nullable=True)
    edge = Column(Float, nullable=True)
    requested_size = Column(Float, nullable=True)
    adjusted_size = Column(Float, nullable=True)
    entry_price = Column(Float, nullable=True)
    bankroll = Column(Float, nullable=True)
    current_exposure = Column(Float, nullable=True)
    risk_allowed = Column(Boolean, nullable=True)
    risk_reason = Column(Text, nullable=True)

    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=True, index=True)
    order_id = Column(String, nullable=True, index=True)
    latency_ms = Column(Float, nullable=True)

    factors_json = Column(Text, nullable=True)
    decision_data = Column(Text, nullable=True)
    signal_data = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_trade_attempts_mode_status_created", "mode", "status", "created_at"),
        Index("idx_trade_attempts_strategy_created", "strategy", "created_at"),
        Index("idx_trade_attempts_reason_created", "reason_code", "created_at"),
    )



class TradeContext(Base):
    __tablename__ = "trade_context"
    trade_id = Column(Integer, ForeignKey("trades.id"), primary_key=True)
    strategy = Column(String, nullable=True)
    signal_source = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    entry_signal = Column(Text, nullable=True)  # JSON string
    exit_signal = Column(Text, nullable=True)  # JSON string
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

