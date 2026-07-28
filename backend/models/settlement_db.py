"""Domain model: settlement — split from database.py.
Keeps backward compatibility via database.py re-exports.
"""
import json
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    JSON,
    UniqueConstraint,
    ForeignKey,
    Enum,
)

from backend.models.base_db import Base

class SettlementEvent(Base):
    __tablename__ = "settlement_events"

    id = Column(Integer, primary_key=True)
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=False)
    market_ticker = Column(String, nullable=False, index=True)
    resolved_outcome = Column(String)  # "up", "down", "yes", "no"
    pnl = Column(Float)
    settled_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    source = Column(String, default="polymarket")  # "polymarket" or "kalshi"



class TransactionEvent(Base):
    """Immutable ledger of all bankroll movements.

    Captures every deposit, withdrawal, trade P&L, reconciliation adjustment,
    and allocation change. Serves as the single source of truth for bankroll
    audit trails, profit analysis, and regulatory reporting.
    """

    __tablename__ = "transaction_events"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True, nullable=False
    )
    # Event type discriminator
    type = Column(
        Enum(
            "deposit",
            "settlement_win",
            "settlement_loss",
            "reconciliation_adjustment",
            "allocation",
            "fee",
            "withdrawal",
            name="transaction_event_type",
        ),
        nullable=False,
        index=True,
    )
    # Amount change (positive for inflow, negative for outflow)
    amount = Column(Float, nullable=False)
    # Bankroll balance immediately after this event (null if not yet reconciled)
    balance_after = Column(Float, nullable=True)
    # Optional context: strategy, market_ticker, trade_id, experiment_id, etc.
    context = Column(JSON, nullable=True)
    # Human-readable reason/note (optional)
    note = Column(String, nullable=True)



class ClobEvent(Base):
    __tablename__ = "clob_events"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String, nullable=False)
    maker = Column(String, nullable=False)
    taker = Column(String, nullable=False)
    market_id = Column(String, nullable=False)
    side = Column(String, nullable=False)  # "BUY" or "SELL"
    size = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fee = Column(Float, nullable=False)
    block_number = Column(Integer, nullable=False)
    tx_hash = Column(String, nullable=False, unique=True)
    timestamp = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        # Only the unique constraint lives here; individual column indexes are
        # declared via index=True on the Column definitions above to avoid
        # duplicate index creation errors when create_all() is called more than
        # once on the same database.
        UniqueConstraint("tx_hash", name="uq_clob_events_tx_hash"),
    )

