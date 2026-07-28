"""Domain model: botstate — split from database.py.
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
    Boolean,
    JSON,
    Text,
    UniqueConstraint,
    ForeignKey,
    Index,
    event,
)
from sqlalchemy.orm import (
    Session as SQLAlchemySession,
    relationship,
)
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy import inspect

from backend.models.base_db import Base

class BotState(Base):
    """Bot state and statistics."""

    __tablename__ = "bot_state"

    id = Column(Integer, primary_key=True)
    mode = Column(String, unique=True, index=True, default="paper")
    bankroll = Column(Float, default=100.0)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    last_run = Column(DateTime, nullable=True)
    is_running = Column(Boolean, default=False)

    # Sync metadata for reconciliation tracking
    last_sync_at = Column(DateTime, nullable=True, default=None)
    last_live_sync_error = Column(String, nullable=True, default=None)

    # Active wallet for multi-wallet management
    active_wallet = Column(String, nullable=True, index=True)

    # Paper trading tracking
    paper_bankroll = Column(Float, default=100.0)
    paper_pnl = Column(Float, default=0.0)
    paper_trades = Column(Integer, default=0)
    paper_wins = Column(Integer, default=0)
    paper_initial_bankroll = Column(
        Float,
        nullable=True,
        default=None,
        doc="Effective initial bankroll for paper mode including top-ups. "
        "None means use settings.INITIAL_BANKROLL.",
    )

    # Testnet trading tracking (isolated from live)
    testnet_bankroll = Column(Float, default=100.0)
    testnet_pnl = Column(Float, default=0.0)
    testnet_trades = Column(Integer, default=0)
    testnet_wins = Column(Integer, default=0)
    testnet_initial_bankroll = Column(
        Float,
        nullable=True,
        default=None,
        doc="Effective initial bankroll for testnet mode including top-ups. "
        "None means use 100.",
    )

    # Live trading tracking
    live_initial_bankroll = Column(
        Float,
        nullable=True,
        default=None,
        doc="Effective initial bankroll for live mode. "
        "Set on first sync from settings.INITIAL_BANKROLL. "
        "Deposits do NOT update this — it stays anchored so PnL "
        "reflects only trading performance, never capital injections.",
    )

    # Per-track bankroll and PNL tracking (for isolation mode)
    track_bankroll_realtime = Column(Float, default=100.0)
    track_bankroll_whale = Column(Float, default=100.0)
    track_bankroll_commodity = Column(Float, default=100.0)
    track_pnl_realtime = Column(Float, default=0.0)
    track_pnl_whale = Column(Float, default=0.0)
    track_pnl_commodity = Column(Float, default=0.0)
    track_loss_limit_realtime = Column(Float, default=50.0)
    track_loss_limit_whale = Column(Float, default=50.0)
    track_loss_limit_commodity = Column(Float, default=50.0)

    # Generic JSON blob for strategy heartbeats and ad-hoc state
    misc_data = Column(Text, nullable=True)

    # Settlement verification tracking
    settlement_last_check_at = Column(DateTime, nullable=True, default=None)

    # Wallet reconciliation tracking
    total_deposits = Column(Float, default=0.0)
    total_withdrawals = Column(Float, default=0.0)
    last_wallet_sync_at = Column(DateTime, nullable=True)
    wallet_pnl = Column(Float, default=0.0)

    def __repr__(self):
        return (
            f"<BotState(id={self.id}, mode={self.mode}, bankroll={self.bankroll}, "
            f"total_pnl={self.total_pnl}, total_trades={self.total_trades}, "
            f"winning_trades={self.winning_trades})>"
        )



class PlatformBalance(Base):
    """Per-platform balance snapshot — updated by platform_balance_sync_job."""

    __tablename__ = "platform_balances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(50), nullable=False, index=True)
    mode = Column(String(20), nullable=False, default="live")
    available_cash = Column(Float, default=0.0)
    locked_margin = Column(Float, default=0.0)
    total_equity = Column(Float, default=0.0)
    currency = Column(String(10), default="USDC")
    raw_response = Column(Text, nullable=True)
    synced_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    error = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("platform", "mode", name="uq_platform_balance_mode"),
    )



@event.listens_for(SQLAlchemySession, "before_flush")
def protect_live_bot_state_financial_fields(session, flush_context, instances):
    """Prevent stale ORM sessions from overwriting live equity caches.

    Live bankroll and total_pnl are derived from external account equity via
    bankroll_reconciliation. Normal runtime sessions may still update live
    metadata and counters, but direct ORM changes to these financial fields are
    reverted unless a caller explicitly opts in with
    session.info["allow_live_financial_update"] = True.
    """

    if session.info.get("allow_live_financial_update"):
        return

    for obj in session.dirty:
        if not isinstance(obj, BotState) or obj.mode != "live":
            continue

        inspected = inspect(obj)
        for field_name in ("bankroll", "total_pnl"):
            history = inspected.attrs[field_name].history
            if not history.has_changes():
                continue
            previous = history.deleted[0] if history.deleted else None
            set_committed_value(obj, field_name, previous)
            logger.warning(
                "Blocked unauthorized live BotState.%s ORM mutation; use bankroll_reconciliation instead",
                field_name,
            )

