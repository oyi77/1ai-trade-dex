"""System routes - stats, bot control, backtest, events."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy import func, text
from sqlalchemy.orm import Session
import json as _json
import asyncio
import psutil
import os

from backend.config import settings
from backend.models.database import (
    get_db,
    BotState,
    Trade,
    Signal,
    AILog,
    DecisionLog,
    TradeAttempt,
    StrategyConfig,
    AuditLog,
    engine,
    for_update,
)
from backend.api.auth import require_admin
from backend.core.signals import scan_for_signals
from backend.core.bankroll_reconciliation import (
    fetch_pm_profile_pnl,
    fetch_pm_profile_trade_stats,
    _initial_bankroll_for_mode,
)
from backend.api.validation import (
    StrategyConfigRequest as ValidatedStrategyConfigRequest,
)
from loguru import logger


def _iso(dt) -> str | None:
    """Safely convert a datetime or string to ISO format.

    SQLite stores dates as strings, PostgreSQL as datetime objects.
    This handles both cases without crashing.
    """
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    if isinstance(dt, str):
        return dt  # Already a string from SQLite
    return str(dt)


router = APIRouter(tags=["system"])

_ticker_price_cache = {}
_ticker_price_cache_timestamps = {}
_CACHE_TTL_SECONDS = 60
_hft_enabled_cache: set = {"universal_scanner", "probability_arb", "whale_frontrun"}


# ============================================================================
# Pydantic Response Models
# ============================================================================


class SyncMetadata(BaseModel):
    """Metadata about database synchronization state."""

    last_synced_at: Optional[datetime] = None
    orphaned_count: int = 0
    external_imports_count: int = 0


class BotStats(BaseModel):
    bankroll: float
    available_balance: float = 0.0
    total_balance: float = 0.0
    total_trades: int
    winning_trades: int
    win_rate: float
    total_pnl: float
    realized_pnl: float = 0.0
    account_pnl: float = 0.0
    is_running: bool
    last_run: Optional[datetime]
    initial_bankroll: float = 10000.0
    paper_pnl: float = 0.0
    paper_bankroll: float = 10000.0
    paper_trades: int = 0
    paper_wins: int = 0
    paper_win_rate: float = 0.0
    testnet_pnl: float = 0.0
    testnet_bankroll: float = 100.0
    testnet_trades: int = 0
    testnet_wins: int = 0
    testnet_win_rate: float = 0.0
    mode: str = "paper"
    pnl_source: str = "botstate"
    paper: dict = {}
    testnet: dict = {}
    live: dict = {}
    live_ledger_pnl: float = 0.0
    live_profile_pnl: float = 0.0
    live_profile_traded_count: Optional[int] = None
    live_ledger_trades: int = 0
    live_ledger_wins: int = 0
    live_profile_closed_count: Optional[int] = None
    live_profile_winning_count: Optional[int] = None
    live_profile_open_count: Optional[int] = None
    live_profile_stale_open_count: Optional[int] = None
    live_profile_redeemable_count: Optional[int] = None
    active_mode: List[str] = ["paper"]
    open_exposure: float = 0.0
    open_trades: int = 0
    settled_trades: int = 0
    settled_wins: int = 0
    unrealized_pnl: float = 0.0
    position_cost: float = 0.0
    position_market_value: float = 0.0
    sync_metadata: Optional[SyncMetadata] = None


def _live_cache_values(
    live_state: Optional[BotState],
) -> tuple[float, float, int, int, float]:
    """Return live account-equity cache values and initial capital basis.

    Live mode is externally reconciled.  The historical Trade ledger remains
    useful for learning/analytics, but dashboard account P&L must come from
    BotState.total_pnl (external equity - initial capital), not the sum of old
    imported/backfilled ledger rows.
    """

    initial = float(
        live_state.live_initial_bankroll
        if live_state and live_state.live_initial_bankroll is not None
        else settings.INITIAL_BANKROLL
    )
    bankroll = float(
        live_state.bankroll
        if live_state and live_state.bankroll is not None
        else initial
    )
    pnl = float(
        live_state.total_pnl
        if live_state and live_state.total_pnl is not None
        else bankroll - initial
    )
    trades = int(live_state.total_trades or 0) if live_state else 0
    wins = int(live_state.winning_trades or 0) if live_state else 0
    return bankroll, pnl, trades, wins, initial


def _available_simulated_bankroll(
    raw_bankroll: Optional[float], fallback: float
) -> float:
    """Return non-negative available bankroll for simulated modes.

    Paper/testnet accounts can have negative cumulative PnL, but available cash
    cannot be below zero. Keep historical PnL negative while preventing
    impossible negative balances from driving dashboards and sizing summaries.
    """

    bankroll = fallback if raw_bankroll is None else float(raw_bankroll)
    return max(0.0, bankroll)


class EventResponse(BaseModel):
    timestamp: str
    type: str
    message: str
    data: dict = {}


# ============================================================================
# Stats Endpoint
# ============================================================================


@router.get("/stats", response_model=BotStats)
async def get_stats(db: Session = Depends(get_db), mode: Optional[str] = Query(None)):
    # Query all 3 mode states (read-only: no for_update to avoid lock contention)
    paper_state = db.query(BotState).filter_by(mode="paper").first()
    testnet_state = db.query(BotState).filter_by(mode="testnet").first()
    live_state = db.query(BotState).filter_by(mode="live").first()

    # Use provided mode or current mode as primary
    effective_mode = mode or settings.TRADING_MODE
    if effective_mode == "all":
        effective_mode = settings.TRADING_MODE
    if effective_mode == "paper":
        state = paper_state
    elif effective_mode == "testnet":
        state = testnet_state
    else:
        state = live_state

    if not state:
        raise HTTPException(status_code=404, detail="Bot state not initialized")

    paper_settled_trades = (
        db.query(func.count(Trade.id))
        .filter(Trade.trading_mode == "paper", Trade.settled)
        .scalar()
        or 0
    )
    paper_wins = (
        db.query(func.count(Trade.id))
        .filter(Trade.trading_mode == "paper", Trade.settled, Trade.pnl > 0)
        .scalar()
        or 0
    )
    paper_pnl = (
        db.query(func.sum(Trade.pnl))
        .filter(Trade.trading_mode == "paper", Trade.settled)
        .scalar()
        or 0.0
    )

    paper_open_trades = (
        db.query(func.count(Trade.id))
        .filter(Trade.trading_mode == "paper", not Trade.settled)  # noqa: E712
        .scalar()
        or 0
    )

    paper_trades = paper_settled_trades + paper_open_trades
    paper_bankroll = _available_simulated_bankroll(
        paper_state.bankroll if paper_state else None,
        settings.INITIAL_BANKROLL,
    )
    paper_win_rate = paper_wins / paper_trades if paper_trades > 0 else 0.0

    sync_metadata = None

    (
        live_bankroll,
        live_cached_account_pnl,
        live_cached_trades,
        live_cached_wins,
        live_initial,
    ) = _live_cache_values(live_state)

    # End the read transaction before network I/O so stats polling does not sit
    # idle-in-transaction while waiting on Polymarket profile calls.
    db.rollback()
    if effective_mode == "live" or mode is None:
        live_profile_pnl, live_profile_trade_stats = await asyncio.gather(
            fetch_pm_profile_pnl(),
            fetch_pm_profile_trade_stats(),
        )
        live_profile_traded_count = (
            live_profile_trade_stats.traded_count if live_profile_trade_stats else None
        )
    else:
        live_profile_pnl = None
        live_profile_trade_stats = None
        live_profile_traded_count = None
    live_account_pnl = (
        float(live_profile_pnl)
        if live_profile_pnl is not None
        else live_cached_account_pnl
    )

    # Always query live-mode trades from actual DB for ledger analytics, but do
    # not use that ledger P&L as live account P&L in the dashboard.
    if effective_mode in ("testnet", "live") or mode is None:
        live_settled_trades = (
            db.query(func.count(Trade.id))
            .filter(
                (
                    Trade.trading_mode == effective_mode
                    if mode is not None
                    else Trade.trading_mode == "live"
                ),
                Trade.settled,
            )
            .scalar()
            or 0
        )
        live_wins = (
            db.query(func.count(Trade.id))
            .filter(
                (
                    Trade.trading_mode == effective_mode
                    if mode is not None
                    else Trade.trading_mode == "live"
                ),
                Trade.settled,
                Trade.pnl > 0,
            )
            .scalar()
            or 0
        )
        live_ledger_pnl = (
            db.query(func.sum(Trade.pnl))
            .filter(
                (
                    Trade.trading_mode == effective_mode
                    if mode is not None
                    else Trade.trading_mode == "live"
                ),
                Trade.settled,
            )
            .scalar()
            or 0.0
        )

        live_open_trades_count = (
            db.query(func.count(Trade.id))
            .filter(
                (
                    Trade.trading_mode == effective_mode
                    if mode is not None
                    else Trade.trading_mode == "live"
                ),
                not Trade.settled,  # noqa: E712
            )
            .scalar()
            or 0
        )

        live_trades = live_settled_trades + live_open_trades_count

        live_win_rate = live_wins / live_trades if live_trades > 0 else 0.0
        live_ledger_trades = live_trades
        live_ledger_wins = live_wins
        if live_profile_trade_stats is not None:
            live_trades = live_profile_trade_stats.traded_count
            live_wins = live_profile_trade_stats.winning_count
            live_win_rate = live_profile_trade_stats.win_rate

        orphaned_count = (
            db.query(func.count(Trade.id))
            .filter(
                Trade.trading_mode == (effective_mode if mode is not None else "live"),
                Trade.result == "orphaned",
            )
            .scalar()
            or 0
        )
        external_imports_count = (
            db.query(func.count(Trade.id))
            .filter(
                Trade.trading_mode == (effective_mode if mode is not None else "live"),
                Trade.source == "external",
            )
            .scalar()
            or 0
        )

        sync_metadata = SyncMetadata(
            last_synced_at=live_state.last_sync_at if live_state else None,
            orphaned_count=orphaned_count,
            external_imports_count=external_imports_count,
        )

        if live_state and round(live_ledger_pnl, 2) != round(live_account_pnl, 2):
            logger.warning(
                f"Stat change detected for {effective_mode}: ledger PnL={live_ledger_pnl} vs live account PnL={live_account_pnl}. "
                f"Orphaned={orphaned_count}, External={external_imports_count}"
            )
    else:
        live_ledger_pnl = live_cached_account_pnl
        live_trades = live_cached_trades
        live_wins = live_cached_wins
        live_win_rate = live_wins / live_trades if live_trades > 0 else 0.0
        live_ledger_trades = live_cached_trades
        live_ledger_wins = live_cached_wins

    testnet_settled_trades = (
        db.query(func.count(Trade.id))
        .filter(
            Trade.trading_mode == "testnet",
            Trade.settled,
            Trade.result.in_(["win", "loss", "closed"]),
        )
        .scalar()
        or 0
    )
    testnet_wins = (
        db.query(func.count(Trade.id))
        .filter(Trade.trading_mode == "testnet", Trade.settled, Trade.pnl > 0)
        .scalar()
        or 0
    )
    testnet_pnl = (
        db.query(func.sum(Trade.pnl))
        .filter(Trade.trading_mode == "testnet", Trade.settled)
        .scalar()
        or 0.0
    )

    testnet_open_trades = (
        db.query(func.count(Trade.id))
        .filter(Trade.trading_mode == "testnet", not Trade.settled)  # noqa: E712
        .scalar()
        or 0
    )

    testnet_trades = testnet_settled_trades + testnet_open_trades
    testnet_bankroll = _available_simulated_bankroll(
        testnet_state.bankroll if testnet_state else None,
        100.0,
    )
    testnet_win_rate = testnet_wins / testnet_trades if testnet_trades > 0 else 0.0

    from backend.core.position_valuation import calculate_position_market_value

    async def calculate_mode_unrealized_pnl(mode: str):
        """Calculate unrealized PnL for a specific mode."""
        result = await calculate_position_market_value(mode, db)

        mode_trades = (
            db.query(Trade).filter(~Trade.settled, Trade.trading_mode == mode).all()
        )

        open_trades_count = len(mode_trades)
        open_exposure_amount = sum((t.size or 0.0) for t in mode_trades)

        return {
            "open_trades": open_trades_count,
            "open_exposure": open_exposure_amount,
            "unrealized_pnl": result["unrealized_pnl"],
            "position_cost": result["position_cost"],
            "position_market_value": result["position_market_value"],
        }

    paper_unrealized, testnet_unrealized, live_unrealized = await asyncio.gather(
        calculate_mode_unrealized_pnl("paper"),
        calculate_mode_unrealized_pnl("testnet"),
        calculate_mode_unrealized_pnl("live"),
    )

    paper_available_balance = round(paper_bankroll, 2)
    paper_total_balance = round(
        paper_available_balance + paper_unrealized["position_market_value"], 2
    )
    testnet_available_balance = round(testnet_bankroll, 2)
    testnet_total_balance = round(
        testnet_available_balance + testnet_unrealized["position_market_value"], 2
    )
    live_available_balance = round(
        max(0.0, live_bankroll - live_unrealized["position_market_value"]), 2
    )
    live_total_balance = round(live_bankroll, 2)

    # Use effective_mode's values for top-level fields (backward compatibility)
    if effective_mode == "paper":
        mode_unrealized = paper_unrealized
    elif effective_mode == "testnet":
        mode_unrealized = testnet_unrealized
    else:
        mode_unrealized = live_unrealized

    open_trades_count = mode_unrealized["open_trades"]
    open_exposure_amount = mode_unrealized["open_exposure"]
    unrealized_pnl = mode_unrealized["unrealized_pnl"]
    position_cost = mode_unrealized["position_cost"]
    position_market_value = mode_unrealized["position_market_value"]

    settled_trades_count = (
        db.query(func.count(Trade.id))
        .filter(
            Trade.settled,
            Trade.trading_mode == effective_mode,
        )
        .scalar()
        or 0
    )
    settled_wins_count = (
        db.query(func.count(Trade.id))
        .filter(
            Trade.settled,
            Trade.trading_mode == effective_mode,
            Trade.pnl > 0,
        )
        .scalar()
        or 0
    )

    pnl_source = "botstate"
    if effective_mode == "paper" and paper_pnl == 0 and paper_trades > 0:
        db_pnl = (
            db.query(func.sum(Trade.pnl))
            .filter(Trade.settled.is_(True), Trade.trading_mode == "paper")
            .scalar()
            or 0.0
        )
        if db_pnl != 0:
            paper_pnl = db_pnl
            pnl_source = "recalculated"
    elif effective_mode == "testnet" and testnet_pnl == 0 and testnet_trades > 0:
        db_pnl = (
            db.query(func.sum(Trade.pnl))
            .filter(Trade.settled.is_(True), Trade.trading_mode == "testnet")
            .scalar()
            or 0.0
        )
        if db_pnl != 0:
            testnet_pnl = db_pnl
            pnl_source = "recalculated"
    if mode is None:
        # All-mode view uses live external trades (deduplicated from Polymarket API)
        # Do NOT sum across modes — trades are consolidated into 'live' mode only
        display_bankroll = live_bankroll
        display_trades = live_trades
        display_wins = live_wins
        display_win_rate = live_win_rate
        display_pnl = live_account_pnl
        display_available_balance = live_available_balance
        display_total_balance = live_total_balance
        display_realized_pnl = live_ledger_pnl
        display_account_pnl = live_account_pnl
        # Use Polymarket profile counts when available (source of truth for live)
        # Fall back to DB query if profile stats unavailable
        settled_trades_count = (
            live_profile_trade_stats.closed_count
            if live_profile_trade_stats is not None
            else (
                db.query(func.count(Trade.id))
                .filter(Trade.settled, Trade.trading_mode == "live")
                .scalar()
                or 0
            )
        )
        settled_wins_count = (
            live_profile_trade_stats.winning_count
            if live_profile_trade_stats is not None
            else (
                db.query(func.count(Trade.id))
                .filter(Trade.settled, Trade.trading_mode == "live", Trade.pnl > 0)
                .scalar()
                or 0
            )
        )
        open_trades_count = live_unrealized["open_trades"]
        open_exposure_amount = live_unrealized["open_exposure"]
        if live_profile_trade_stats is not None:
            open_trades_count = live_profile_trade_stats.open_position_count
            open_exposure_amount = live_profile_trade_stats.open_position_value
        unrealized_pnl = live_unrealized["unrealized_pnl"]
        position_cost = live_unrealized["position_cost"]
        position_market_value = live_unrealized["position_market_value"]
    elif effective_mode == "paper":
        display_bankroll = paper_bankroll
        display_available_balance = paper_available_balance
        display_total_balance = paper_total_balance
        display_trades = paper_trades
        display_wins = paper_wins
        display_win_rate = paper_win_rate
        display_pnl = paper_pnl
        display_realized_pnl = paper_pnl
        display_account_pnl = paper_pnl
    elif effective_mode == "testnet":
        display_bankroll = testnet_bankroll
        display_available_balance = testnet_available_balance
        display_total_balance = testnet_total_balance
        display_trades = testnet_trades
        display_wins = testnet_wins
        display_win_rate = testnet_win_rate
        display_pnl = testnet_pnl
        display_realized_pnl = testnet_pnl
        display_account_pnl = testnet_pnl
    else:
        display_bankroll = live_bankroll
        display_available_balance = live_available_balance
        display_total_balance = live_total_balance
        display_trades = live_trades
        display_wins = live_wins
        display_win_rate = live_win_rate
        display_pnl = live_account_pnl
        display_realized_pnl = live_ledger_pnl
        display_account_pnl = live_account_pnl

    if effective_mode == "live" and live_profile_trade_stats is not None:
        open_trades_count = live_profile_trade_stats.open_position_count
        open_exposure_amount = live_profile_trade_stats.open_position_value

    return BotStats(
        bankroll=display_bankroll,
        available_balance=display_available_balance,
        total_balance=display_total_balance,
        total_trades=display_trades,
        winning_trades=display_wins,
        win_rate=display_win_rate,
        total_pnl=display_pnl,
        realized_pnl=display_realized_pnl,
        account_pnl=display_account_pnl,
        is_running=state.is_running,
        last_run=state.last_run,
        initial_bankroll=_initial_bankroll_for_mode(
            effective_mode, live_state or paper_state or testnet_state
        ),
        paper_pnl=paper_pnl,
        paper_bankroll=paper_bankroll,
        paper_trades=paper_trades,
        paper_wins=paper_wins,
        paper_win_rate=paper_win_rate,
        testnet_pnl=testnet_pnl,
        testnet_bankroll=testnet_bankroll,
        testnet_trades=testnet_trades,
        testnet_wins=testnet_wins,
        testnet_win_rate=testnet_win_rate,
        mode="all" if mode is None else effective_mode,
        pnl_source=pnl_source,
        paper={
            "pnl": paper_pnl,
            "realized_pnl": paper_pnl,
            "account_pnl": paper_pnl,
            "bankroll": paper_bankroll,
            "available_balance": paper_available_balance,
            "total_balance": paper_total_balance,
            "trades": paper_trades,
            "wins": paper_wins,
            "win_rate": paper_win_rate,
            "open_trades": paper_unrealized["open_trades"],
            "open_exposure": paper_unrealized["open_exposure"],
            "unrealized_pnl": paper_unrealized["unrealized_pnl"],
            "position_cost": paper_unrealized["position_cost"],
            "position_market_value": paper_unrealized["position_market_value"],
        },
        testnet={
            "pnl": testnet_pnl,
            "realized_pnl": testnet_pnl,
            "account_pnl": testnet_pnl,
            "bankroll": testnet_bankroll,
            "available_balance": testnet_available_balance,
            "total_balance": testnet_total_balance,
            "trades": testnet_trades,
            "wins": testnet_wins,
            "win_rate": testnet_win_rate,
            "open_trades": testnet_unrealized["open_trades"],
            "open_exposure": testnet_unrealized["open_exposure"],
            "unrealized_pnl": testnet_unrealized["unrealized_pnl"],
            "position_cost": testnet_unrealized["position_cost"],
            "position_market_value": testnet_unrealized["position_market_value"],
        },
        live={
            "pnl": live_account_pnl,
            "realized_pnl": live_ledger_pnl,
            "account_pnl": live_account_pnl,
            "bankroll": live_bankroll,
            "available_balance": live_available_balance,
            "total_balance": live_total_balance,
            "trades": live_trades,
            "wins": live_wins,
            "win_rate": live_win_rate,
            "open_trades": live_unrealized["open_trades"],
            "open_exposure": live_unrealized["open_exposure"],
            "unrealized_pnl": live_unrealized["unrealized_pnl"],
            "position_cost": live_unrealized["position_cost"],
            "position_market_value": live_unrealized["position_market_value"],
            "ledger_pnl": live_ledger_pnl,
            "profile_pnl": live_account_pnl,
            "profile_traded_count": live_profile_traded_count,
            "profile_closed_count": (
                live_profile_trade_stats.closed_count
                if live_profile_trade_stats
                else None
            ),
            "profile_winning_count": (
                live_profile_trade_stats.winning_count
                if live_profile_trade_stats
                else None
            ),
            "profile_open_count": (
                live_profile_trade_stats.open_position_count
                if live_profile_trade_stats
                else None
            ),
            "profile_stale_open_count": (
                live_profile_trade_stats.stale_open_position_count
                if live_profile_trade_stats
                else None
            ),
            "profile_redeemable_count": (
                live_profile_trade_stats.redeemable_position_count
                if live_profile_trade_stats
                else None
            ),
            "profile_open_value": (
                live_profile_trade_stats.open_position_value
                if live_profile_trade_stats
                else None
            ),
            "profile_open_initial_value": (
                live_profile_trade_stats.open_position_initial_value
                if live_profile_trade_stats
                else None
            ),
            "ledger_trades": live_ledger_trades,
            "ledger_wins": live_ledger_wins,
            "ledger_open_trades": live_unrealized["open_trades"],
            "ledger_open_exposure": live_unrealized["open_exposure"],
            "initial_bankroll": live_initial,
        },
        live_ledger_pnl=live_ledger_pnl,
        live_profile_pnl=live_account_pnl,
        live_profile_traded_count=live_profile_traded_count,
        live_ledger_trades=live_ledger_trades,
        live_ledger_wins=live_ledger_wins,
        live_profile_closed_count=(
            live_profile_trade_stats.closed_count if live_profile_trade_stats else None
        ),
        live_profile_winning_count=(
            live_profile_trade_stats.winning_count if live_profile_trade_stats else None
        ),
        live_profile_open_count=(
            live_profile_trade_stats.open_position_count
            if live_profile_trade_stats
            else None
        ),
        live_profile_stale_open_count=(
            live_profile_trade_stats.stale_open_position_count
            if live_profile_trade_stats
            else None
        ),
        live_profile_redeemable_count=(
            live_profile_trade_stats.redeemable_position_count
            if live_profile_trade_stats
            else None
        ),
        active_mode=list(settings.active_modes_set),
        open_exposure=open_exposure_amount,
        open_trades=open_trades_count,
        settled_trades=settled_trades_count,
        settled_wins=settled_wins_count,
        unrealized_pnl=unrealized_pnl,
        position_cost=position_cost,
        position_market_value=position_market_value,
        sync_metadata=sync_metadata,
    )


# ============================================================================
# AI Status & Control
# ============================================================================


@router.get("/stats/strategies")
async def get_strategy_stats(
    db: Session = Depends(get_db),
):
    """Return P&L breakdown per strategy."""
    from sqlalchemy import case

    results = (
        db.query(
            Trade.strategy,
            func.count(Trade.id).label("total_trades"),
            func.sum(
                case(
                    (Trade.settled.is_(True), case((Trade.pnl > 0, 1), else_=0)),
                    else_=0,
                )
            ).label("wins"),
            func.sum(
                case(
                    (Trade.settled.is_(True), case((Trade.pnl <= 0, 1), else_=0)),
                    else_=0,
                )
            ).label("losses"),
            func.sum(case((Trade.settled, Trade.pnl), else_=0)).label("total_pnl"),
            func.avg(Trade.edge_at_entry).label("avg_edge"),
            func.avg(Trade.size).label("avg_size"),
        )
        .filter(Trade.strategy.isnot(None), Trade.source == "bot")
        .group_by(Trade.strategy)
        .all()
    )

    strategies = []
    for r in results:
        total = r.wins + r.losses
        strategies.append(
            {
                "strategy": r.strategy or "unknown",
                "total_trades": r.total_trades,
                "wins": r.wins,
                "losses": r.losses,
                "pending": r.total_trades - r.wins - r.losses,
                "win_rate": r.wins / total if total > 0 else 0,
                "total_pnl": round(r.total_pnl or 0, 2),
                "avg_edge": round(r.avg_edge or 0, 4),
                "avg_size": round(r.avg_size or 0, 2),
            }
        )

    return {
        "strategies": sorted(strategies, key=lambda s: s["total_pnl"], reverse=True)
    }


@router.get("/ai/status")
async def get_ai_status(
    db: Session = Depends(get_db),
):
    """Return AI system status: enabled, provider, budget usage."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    spent_today = (
        db.query(func.coalesce(func.sum(AILog.cost_usd), 0.0))
        .filter(AILog.timestamp >= today_start)
        .scalar()
        or 0.0
    )
    calls_today = (
        db.query(func.count(AILog.id)).filter(AILog.timestamp >= today_start).scalar()
        or 0
    )

    return {
        "enabled": settings.AI_ENABLED,
        "provider": settings.AI_PROVIDER,
        "model": settings.AI_MODEL or settings.GROQ_MODEL,
        "daily_budget": settings.AI_DAILY_BUDGET_USD,
        "spent_today": round(spent_today, 4),
        "remaining": round(max(0, settings.AI_DAILY_BUDGET_USD - spent_today), 4),
        "calls_today": calls_today,
        "signal_weight": settings.AI_SIGNAL_WEIGHT,
    }


@router.post("/ai/toggle")
async def toggle_ai(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    """Toggle AI-enhanced signals on/off."""
    from backend.models.audit_logger import log_audit_event

    old_value = settings.AI_ENABLED
    settings.AI_ENABLED = not settings.AI_ENABLED

    log_audit_event(
        db=db,
        event_type="AI_TOGGLE",
        entity_type="CONFIG",
        entity_id="ai_enabled",
        old_value={"enabled": old_value},
        new_value={"enabled": settings.AI_ENABLED},
        user_id="admin",
    )
    db.commit()

    logger.info("AI signals %s", "ENABLED" if settings.AI_ENABLED else "DISABLED")
    return {"enabled": settings.AI_ENABLED}


# ============================================================================
# Bot Control Endpoints
# ============================================================================


@router.post("/bot/start")
async def start_bot(
    body: dict | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    from backend.core.scheduler import start_scheduler, log_event, is_scheduler_running

    mode = (body or {}).get("mode", settings.TRADING_MODE)
    state = for_update(db, db.query(BotState).filter_by(mode=mode)).first()
    if state and state.is_running:
        raise HTTPException(
            status_code=409, detail={"error": "already_running", "is_running": True}
        )

    if state:
        state.is_running = True
        db.commit()

    if not is_scheduler_running():
        start_scheduler()

    log_event("success", f"Trading bot started for mode={mode}")
    return {"status": "started", "is_running": True, "mode": mode}


@router.post("/bot/stop")
async def stop_bot(
    body: dict | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    from backend.core.scheduler import log_event

    mode = (body or {}).get("mode", settings.TRADING_MODE)
    state = for_update(db, db.query(BotState).filter_by(mode=mode)).first()
    if state and not state.is_running:
        raise HTTPException(
            status_code=409, detail={"error": "already_stopped", "is_running": False}
        )

    if state:
        state.is_running = False
        db.commit()

    log_event("info", f"Trading bot paused for mode={mode}")
    return {"status": "stopped", "is_running": False, "mode": mode}


class ResetRequest(BaseModel):
    confirm: bool = False


@router.post("/bot/reset")
async def reset_bot(
    body: ResetRequest, db: Session = Depends(get_db), _: None = Depends(require_admin)
):
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to confirm reset. This deletes ALL trades and resets bankroll.",
        )
    from backend.core.scheduler import log_event

    try:
        trades_deleted = db.query(Trade).delete()

        for mode in ["paper", "testnet", "live"]:
            state = for_update(db, db.query(BotState).filter_by(mode=mode)).first()
            if state:
                state.bankroll = settings.INITIAL_BANKROLL
                state.total_trades = 0
                state.winning_trades = 0
                state.total_pnl = 0.0
                state.is_running = True

        ai_logs_deleted = db.query(AILog).delete()
        db.commit()

        log_event(
            "success",
            f"Bot reset: {trades_deleted} trades deleted. Fresh start with ${settings.INITIAL_BANKROLL:,.2f}",
        )

        return {
            "status": "reset",
            "trades_deleted": trades_deleted,
            "ai_logs_deleted": ai_logs_deleted,
            "new_bankroll": settings.INITIAL_BANKROLL,
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Reset failed: {e}")


class PaperTopupRequest(BaseModel):
    amount: float = Field(gt=0, description="USDC to add to paper bankroll")
    confirm: bool = False


@router.post("/bot/paper-topup")
async def paper_topup(
    body: PaperTopupRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to confirm topup.",
        )
    if not settings.is_mode_active("paper"):
        raise HTTPException(
            status_code=409,
            detail="paper-topup only available when paper mode is active",
        )

    from backend.core.scheduler import log_event
    from backend.models.audit_logger import log_audit_event

    state = for_update(db, db.query(BotState).filter_by(mode="paper")).first()
    if state is None:
        raise HTTPException(status_code=404, detail="Paper bot state not found")

    previous = float(state.paper_bankroll or 0.0)
    state.paper_bankroll = previous + body.amount

    # Also bump the effective initial bankroll so reconciliation preserves the top-up.
    # Without this, the next reconcile cycle would recalculate bankroll as
    # INITIAL_BANKROLL + pnl - exposure, wiping the top-up.
    prev_initial = float(state.paper_initial_bankroll or settings.INITIAL_BANKROLL)
    state.paper_initial_bankroll = prev_initial + body.amount

    db.commit()

    log_event(
        "info",
        f"Paper bankroll topped up by ${body.amount:,.2f} (${previous:,.2f} → ${state.paper_bankroll:,.2f}); "
        f"initial_bankroll ${prev_initial:,.2f} → ${state.paper_initial_bankroll:,.2f}",
    )
    log_audit_event(
        db,
        event_type="PAPER_TOPUP",
        entity_type="BOT_STATE",
        entity_id="paper",
        old_value={"paper_bankroll": previous, "paper_initial_bankroll": prev_initial},
        new_value={
            "paper_bankroll": float(state.paper_bankroll),
            "paper_initial_bankroll": float(state.paper_initial_bankroll),
            "added": body.amount,
        },
        user_id="admin_topup",
    )
    db.commit()

    return {
        "status": "topped_up",
        "previous_bankroll": previous,
        "added": body.amount,
        "new_bankroll": state.paper_bankroll,
        "new_initial_bankroll": state.paper_initial_bankroll,
    }


class LiveAdjustRequest(BaseModel):
    amount: float = Field(
        description="USDC amount (positive=deposit, negative=withdraw)"
    )
    confirm: bool = False


@router.post("/bot/live-adjust")
async def live_adjust(
    body: LiveAdjustRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Adjust live bankroll initial capital on deposit/withdraw."""
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to confirm.")
    if not settings.is_mode_active("live"):
        raise HTTPException(
            status_code=409,
            detail="live-adjust only available when live mode is active",
        )

    from backend.core.scheduler import log_event
    from backend.models.audit_logger import log_audit_event

    state = for_update(db, db.query(BotState).filter_by(mode="live")).first()
    if state is None:
        raise HTTPException(status_code=404, detail="Live bot state not found")

    prev_initial = float(state.live_initial_bankroll or settings.INITIAL_BANKROLL)
    new_initial = prev_initial + body.amount
    if new_initial < 0:
        raise HTTPException(
            status_code=400, detail="Cannot withdraw more than initial capital"
        )

    state.live_initial_bankroll = new_initial
    db.commit()

    action = "deposit" if body.amount > 0 else "withdrawal"
    log_event(
        "info",
        f"Live {action} ${abs(body.amount):,.2f} — initial_bankroll ${prev_initial:,.2f} → ${new_initial:,.2f}",
    )
    log_audit_event(
        db,
        event_type=f"LIVE_{action.upper()}",
        entity_type="BOT_STATE",
        entity_id="live",
        old_value={"live_initial_bankroll": prev_initial},
        new_value={"live_initial_bankroll": new_initial, action: abs(body.amount)},
        user_id="admin_adjust",
    )
    db.commit()

    return {
        "status": action,
        "previous_initial": prev_initial,
        "adjusted": body.amount,
        "new_initial": new_initial,
    }


# ============================================================================


class BacktestRequest(BaseModel):
    initial_bankroll: float = 1000.0
    max_trade_size: float = 100.0
    min_edge_threshold: float = 0.02
    start_date: str | None = None  # ISO format datetime
    end_date: str | None = None  # ISO format datetime
    market_types: list[str] = ["BTC", "Weather", "CopyTrader"]
    slippage_bps: int = 5  # basis points


@router.post("/backtest")
async def run_backtest(
    body: BacktestRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Run backtest against historical signals."""
    from backend.core.backtesting import BacktestEngine, BacktestConfig

    try:
        # Parse dates
        start_date = (
            datetime.fromisoformat(body.start_date) if body.start_date else None
        )
        end_date = datetime.fromisoformat(body.end_date) if body.end_date else None

        # Create config
        config = BacktestConfig(
            initial_bankroll=body.initial_bankroll,
            max_trade_size=body.max_trade_size,
            min_edge_threshold=body.min_edge_threshold,
            start_date=start_date,
            end_date=end_date,
            market_types=body.market_types,
            slippage_bps=body.slippage_bps,
        )

        # Run backtest
        engine = BacktestEngine(config)
        result = engine.run(db)

        return {
            "strategy_name": "signal_replay",
            "start_date": (start_date.isoformat() if start_date else body.start_date),
            "end_date": (end_date.isoformat() if end_date else body.end_date),
            "initial_bankroll": body.initial_bankroll,
            "results": {
                "summary": {
                    "total_signals": result.total_trades,
                    "total_trades": result.total_trades,
                    "winning_trades": result.winning_trades,
                    "losing_trades": result.losing_trades,
                    "win_rate": result.win_rate,
                    "initial_bankroll": body.initial_bankroll,
                    "final_equity": result.final_bankroll,
                    "total_pnl": result.total_pnl,
                    "total_return_pct": result.roi * 100,
                    "sharpe_ratio": result.sharpe_ratio,
                },
                "trade_log": [],
                "equity_curve": [],
            },
        }

    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        raise HTTPException(
            status_code=500, detail="Backtest failed — check server logs"
        )


@router.get("/backtest/quick")
async def quick_backtest(
    days_back: int = 30,
    initial_bankroll: float = 1000.0,
    db: Session = Depends(get_db),
):
    """Quick backtest for recent N days."""
    from backend.core.backtesting import run_quick_backtest

    try:
        result = run_quick_backtest(
            db, days_back=days_back, initial_bankroll=initial_bankroll
        )

        return {
            "status": "success",
            "result": {
                "total_trades": result.total_trades,
                "winning_trades": result.winning_trades,
                "losing_trades": result.losing_trades,
                "total_pnl": result.total_pnl,
                "final_bankroll": result.final_bankroll,
                "win_rate": result.win_rate,
                "avg_win": result.avg_win,
                "avg_loss": result.avg_loss,
                "max_drawdown": result.max_drawdown,
                "sharpe_ratio": result.sharpe_ratio,
                "trades_per_day": result.trades_per_day,
                "roi": result.roi,
            },
        }

    except Exception as e:
        logger.error(f"Quick backtest failed: {e}")
        raise HTTPException(
            status_code=500, detail="Quick backtest failed — check server logs"
        )


# ============================================================================
# Events Endpoints
# ============================================================================


@router.get("/events", response_model=List[EventResponse])
async def get_events(limit: int = 50):
    from backend.core.scheduler import get_recent_events

    limit = min(limit, 500)
    events = get_recent_events(limit)
    return [
        EventResponse(
            timestamp=e["timestamp"],
            type=e["type"],
            message=e["message"],
            data=e.get("data", {}),
        )
        for e in events
    ]


@router.post("/run-scan")
async def run_scan(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    from backend.core.scheduler import run_manual_scan, log_event

    # Iterate over all active modes to update last_run
    for mode in settings.active_modes_set:
        state = for_update(db, db.query(BotState).filter_by(mode=mode)).first()
        if state:
            state.last_run = datetime.now(timezone.utc)
    db.commit()

    log_event("info", "Manual scan triggered (BTC + Weather)")
    await run_manual_scan()

    signals = await scan_for_signals()
    actionable = [s for s in signals if s.passes_threshold]

    result = {
        "status": "ok",
        "total_signals": len(signals),
        "actionable_signals": len(actionable),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Also run weather scan if enabled
    if settings.WEATHER_ENABLED:
        try:
            from backend.core.weather_signals import scan_for_weather_signals

            wx_signals = await scan_for_weather_signals()
            wx_actionable = [s for s in wx_signals if s.passes_threshold]
            result["weather_signals"] = len(wx_signals)
            result["weather_actionable"] = len(wx_actionable)
        except Exception:
            logger.exception("Failed to scan for weather signals in run_scan")
            result["weather_signals"] = 0
            result["weather_actionable"] = 0

    return result


# ============================================================================
# Trade Attempt Control Room Endpoints
# ============================================================================


_ALLOWED_ATTEMPT_SORT = {
    "id",
    "created_at",
    "updated_at",
    "strategy",
    "mode",
    "market_ticker",
    "status",
    "phase",
    "reason_code",
    "confidence",
    "edge",
    "requested_size",
    "adjusted_size",
    "latency_ms",
}


def _parse_json_text(raw: str | None):
    if not raw:
        return None
    try:
        return _json.loads(raw)
    except Exception:
        logger.exception(
            "Failed to parse JSON in _parse_json_text, returning raw value"
        )
        return raw


def _attempt_to_dict(attempt: TradeAttempt) -> dict:
    return {
        "id": attempt.id,
        "attempt_id": attempt.attempt_id,
        "correlation_id": attempt.correlation_id,
        "created_at": _iso(attempt.created_at),
        "updated_at": _iso(attempt.updated_at),
        "strategy": attempt.strategy,
        "mode": attempt.mode,
        "market_ticker": attempt.market_ticker,
        "platform": attempt.platform,
        "direction": attempt.direction,
        "decision": attempt.decision,
        "status": attempt.status,
        "phase": attempt.phase,
        "reason_code": attempt.reason_code,
        "reason": attempt.reason,
        "confidence": attempt.confidence,
        "edge": attempt.edge,
        "requested_size": attempt.requested_size,
        "adjusted_size": attempt.adjusted_size,
        "entry_price": attempt.entry_price,
        "bankroll": attempt.bankroll,
        "current_exposure": attempt.current_exposure,
        "risk_allowed": attempt.risk_allowed,
        "risk_reason": attempt.risk_reason,
        "trade_id": attempt.trade_id,
        "order_id": attempt.order_id,
        "latency_ms": attempt.latency_ms,
        "factors": _parse_json_text(attempt.factors_json),
        "decision_data": _parse_json_text(attempt.decision_data),
        "signal_data": _parse_json_text(attempt.signal_data),
    }


@router.get("/trade-attempts")
async def list_trade_attempts(
    mode: str | None = None,
    status: str | None = None,
    strategy: str | None = None,
    reason_code: str | None = None,
    market: str | None = None,
    since: str | None = None,
    until: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List trade execution attempts with operator-focused filtering."""
    if sort not in _ALLOWED_ATTEMPT_SORT:
        sort = "created_at"
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    query = db.query(TradeAttempt)
    if mode and mode != "all":
        query = query.filter(TradeAttempt.mode == mode)
    if status and status != "all":
        query = query.filter(TradeAttempt.status == status.upper())
    if strategy:
        query = query.filter(TradeAttempt.strategy == strategy)
    if reason_code:
        query = query.filter(TradeAttempt.reason_code == reason_code)
    if market:
        query = query.filter(TradeAttempt.market_ticker.contains(market))
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            query = query.filter(TradeAttempt.created_at >= since_dt)
        except ValueError:
            logger.debug("Invalid trade-attempt since filter ignored: %s", since)
    if until:
        try:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            query = query.filter(TradeAttempt.created_at <= until_dt)
        except ValueError:
            logger.debug("Invalid trade-attempt until filter ignored: %s", until)

    total = query.count()
    col = getattr(TradeAttempt, sort, TradeAttempt.created_at)
    if order.lower() == "desc":
        col = col.desc()
    items = query.order_by(col).offset(offset).limit(limit).all()
    return {"items": [_attempt_to_dict(item) for item in items], "total": total}


@router.get("/trade-attempts/summary")
async def trade_attempts_summary(
    mode: str | None = None,
    db: Session = Depends(get_db),
):
    """Summarize current execution blockers for the Trade Control Room."""
    query = db.query(TradeAttempt)
    if mode and mode != "all":
        query = query.filter(TradeAttempt.mode == mode)

    total = query.count()
    executed = query.filter(TradeAttempt.status == "EXECUTED").count()
    blocked = query.filter(
        TradeAttempt.status.in_(["BLOCKED", "REJECTED", "FAILED"])
    ).count()

    by_status = [
        {"status": status, "count": count}
        for status, count in db.query(TradeAttempt.status, func.count(TradeAttempt.id))
        .filter(TradeAttempt.mode == mode if mode and mode != "all" else text("1=1"))
        .group_by(TradeAttempt.status)
        .order_by(func.count(TradeAttempt.id).desc())
        .all()
    ]
    by_mode = [
        {"mode": row_mode, "count": count}
        for row_mode, count in db.query(TradeAttempt.mode, func.count(TradeAttempt.id))
        .group_by(TradeAttempt.mode)
        .order_by(func.count(TradeAttempt.id).desc())
        .all()
    ]
    top_blockers = [
        {"reason_code": reason_code, "count": count}
        for reason_code, count in db.query(
            TradeAttempt.reason_code, func.count(TradeAttempt.id)
        )
        .filter(TradeAttempt.status.in_(["BLOCKED", "REJECTED", "FAILED"]))
        .filter(TradeAttempt.mode == mode if mode and mode != "all" else text("1=1"))
        .group_by(TradeAttempt.reason_code)
        .order_by(func.count(TradeAttempt.id).desc())
        .limit(8)
        .all()
    ]
    recent_blockers = (
        query.filter(TradeAttempt.status.in_(["BLOCKED", "REJECTED", "FAILED"]))
        .order_by(TradeAttempt.created_at.desc())
        .limit(5)
        .all()
    )
    latest = query.order_by(TradeAttempt.created_at.desc()).first()

    return {
        "total": total,
        "executed": executed,
        "blocked": blocked,
        "execution_rate": executed / total if total else 0.0,
        "last_attempt_at": (
            _iso(latest.created_at) if latest and latest.created_at else None
        ),
        "by_status": by_status,
        "by_mode": by_mode,
        "top_blockers": top_blockers,
        "recent_blockers": [_attempt_to_dict(item) for item in recent_blockers],
    }


# ============================================================================
# Decision Log Endpoints
# ============================================================================


_ALLOWED_DECISION_SORT = {
    "id",
    "created_at",
    "strategy",
    "market_ticker",
    "confidence",
    "decision",
}


@router.get("/decisions")
async def list_decisions(
    strategy: str | None = None,
    decision: str | None = None,
    market: str | None = None,
    since: str | None = None,
    until: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List decision log entries with filtering."""
    if sort not in _ALLOWED_DECISION_SORT:
        sort = "created_at"
    limit = min(limit, 500)
    query = db.query(DecisionLog)
    if strategy:
        query = query.filter(DecisionLog.strategy == strategy)
    if decision:
        query = query.filter(DecisionLog.decision == decision.upper())
    if market:
        query = query.filter(DecisionLog.market_ticker.contains(market))
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            query = query.filter(DecisionLog.created_at >= since_dt)
        except ValueError as e:
            logger.debug(f"Strategy status check error: {e}")
    if until:
        try:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            query = query.filter(DecisionLog.created_at <= until_dt)
        except ValueError as e:
            logger.debug(f"Strategy status check error: {e}")
    total = query.count()
    col = getattr(DecisionLog, sort, DecisionLog.created_at)
    if order == "desc":
        col = col.desc()
    items = query.order_by(col).offset(offset).limit(limit).all()
    import json as _json

    def _parse_signal_data(raw):
        if not raw:
            return None
        try:
            return _json.loads(raw)
        except Exception:
            logger.exception("Failed to parse signal_data JSON in list_decisions")
            return raw

    return {
        "items": [
            {
                "id": d.id,
                "strategy": d.strategy,
                "market_ticker": d.market_ticker,
                "decision": d.decision,
                "confidence": d.confidence,
                "reason": d.reason,
                "outcome": d.outcome,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "signal_data": _parse_signal_data(d.signal_data),
            }
            for d in items
        ],
        "total": total,
    }


@router.get("/decisions/export")
async def export_decisions(
    format: str = "jsonl",
    strategy: str | None = None,
    decision: str | None = None,
    limit: int = 10000,
    db: Session = Depends(get_db),
):
    """Export decision log as JSONL for ML training."""
    limit = min(limit, 5000)
    from fastapi.responses import StreamingResponse
    import json as _json

    query = db.query(DecisionLog)
    if strategy:
        query = query.filter(DecisionLog.strategy == strategy)
    if decision:
        query = query.filter(DecisionLog.decision == decision.upper())
    items = query.order_by(DecisionLog.created_at.desc()).limit(limit).all()

    def generate():
        for d in items:
            signal_data = None
            if d.signal_data:
                try:
                    signal_data = _json.loads(d.signal_data)
                except Exception:
                    logger.exception(
                        f"Failed to parse signal_data for decision export {d.id}"
                    )
                    signal_data = d.signal_data
            row = {
                "id": d.id,
                "strategy": d.strategy,
                "market_ticker": d.market_ticker,
                "decision": d.decision,
                "confidence": d.confidence,
                "signal_data": signal_data,
                "reason": d.reason,
                "outcome": d.outcome,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            yield _json.dumps(row) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=decisions.jsonl"},
    )


@router.get("/decisions/{decision_id}")
async def get_decision(
    decision_id: int,
    db: Session = Depends(get_db),
):
    """Get a single decision log entry by ID."""
    decision = db.query(DecisionLog).filter(DecisionLog.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    signal_data = None
    if decision.signal_data:
        try:
            signal_data = _json.loads(decision.signal_data)
        except Exception:
            logger.exception(f"Failed to parse signal_data for decision {decision_id}")
            signal_data = decision.signal_data

    return {
        "id": decision.id,
        "strategy": decision.strategy,
        "market_ticker": decision.market_ticker,
        "decision": decision.decision,
        "confidence": decision.confidence,
        "signal_data": signal_data,
        "reason": decision.reason,
        "outcome": decision.outcome,
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
    }


# ============================================================================
# Signal Config Endpoint (public, no secrets)
# ============================================================================


@router.get("/signal-config")
async def get_signal_config():
    """Return current signal approval settings (no auth required, no secrets)."""
    return {
        "approval_mode": settings.SIGNAL_APPROVAL_MODE,
        "min_confidence": settings.AUTO_APPROVE_MIN_CONFIDENCE,
        "notification_duration_ms": settings.SIGNAL_NOTIFICATION_DURATION_MS,
    }


# ============================================================================
# Strategy Management Endpoints
# ============================================================================


@router.get("/strategies")
async def list_strategies(
    db: Session = Depends(get_db),
):
    """List all registered strategies with their DB config."""
    from backend.strategies.registry import STRATEGY_REGISTRY

    db_configs = {c.strategy_name: c for c in db.query(StrategyConfig).all()}

    # Map of strategy -> required credential keys
    STRATEGY_CREDENTIALS = {
        "kalshi_arb": ["KALSHI_API_KEY"],
        "copy_trader": ["POLYMARKET_PRIVATE_KEY"],
        "btc_oracle": [],  # uses public data only
        "btc_momentum": [],  # uses public data only
        "weather_emos": [],  # uses public weather data
        "general_market_scanner": [],
        "realtime_scanner": [],
        "whale_pnl_tracker": [],
        "bond_scanner": [],
        "market_maker": ["POLYMARKET_PRIVATE_KEY"],
    }

    result = []
    for name, cls in STRATEGY_REGISTRY.items():
        cfg = db_configs.get(name)
        required_creds = STRATEGY_CREDENTIALS.get(name, [])
        result.append(
            {
                "name": name,
                "description": getattr(cls, "description", ""),
                "category": getattr(cls, "category", "general"),
                "enabled": cfg.enabled if cfg else False,
                "interval_seconds": cfg.interval_seconds if cfg else 60,
                "params": _json.loads(cfg.params) if cfg and cfg.params else {},
                "default_params": dict(getattr(cls, "default_params", {})),
                "updated_at": _iso(cfg.updated_at) if cfg and cfg.updated_at else None,
                "required_credentials": required_creds,
                "trading_mode": cfg.trading_mode if cfg else None,
            }
        )
    return result


@router.get("/strategies/health")
async def get_strategies_health(db: Session = Depends(get_db)):
    """Return health metrics, heartbeat, last signal, and rejections per strategy."""
    from backend.strategies.registry import STRATEGY_REGISTRY
    from backend.strategies.loader import load_all_strategies
    from backend.models.database import StrategyConfig, BotState, Signal, TradeAttempt
    from backend.config import settings

    if not STRATEGY_REGISTRY:
        load_all_strategies()

    # Fetch all configuration overrides from the database
    db_configs = {c.strategy_name: c for c in db.query(StrategyConfig).all()}

    # Query all BotStates to extract heartbeats and scan stats
    bot_states = {state.mode: state for state in db.query(BotState).all()}

    result = []
    for name, cls in STRATEGY_REGISTRY.items():
        cfg = db_configs.get(name)
        enabled = cfg.enabled if cfg else False
        effective_mode = cfg.trading_mode or settings.TRADING_MODE if cfg else settings.TRADING_MODE

        # Retrieve heartbeat and scan stats from the BotState matching the mode
        bot_state = bot_states.get(effective_mode)
        last_heartbeat = None
        scan_stats = {}
        if bot_state and bot_state.misc_data:
            try:
                misc = (
                    _json.loads(bot_state.misc_data)
                    if isinstance(bot_state.misc_data, str)
                    else bot_state.misc_data
                )
                last_heartbeat = misc.get(f"heartbeat:{name}")
                scan_stats = misc.get(f"scan_stats:{name}", {})
            except Exception:
                logger.warning(f"Failed to parse misc_data for mode {effective_mode}")

        # Retrieve the last generated signal
        last_signal = (
            db.query(Signal)
            .filter(
                Signal.track_name == name,
                Signal.execution_mode == effective_mode,
            )
            .order_by(Signal.timestamp.desc())
            .first()
        )
        last_signal_details = None
        if last_signal:
            last_signal_details = {
                "timestamp": _iso(last_signal.timestamp),
                "market_ticker": last_signal.market_ticker,
                "direction": last_signal.direction,
                "model_probability": last_signal.model_probability,
                "market_price": last_signal.market_price,
                "edge": last_signal.edge,
                "confidence": last_signal.confidence,
                "reasoning": last_signal.reasoning,
            }

        # Retrieve recent rejections / blocks
        recent_rejections = (
            db.query(TradeAttempt)
            .filter(
                TradeAttempt.strategy == name,
                TradeAttempt.mode == effective_mode,
                TradeAttempt.status.in_(("REJECTED", "BLOCKED", "FAILED")),
            )
            .order_by(TradeAttempt.created_at.desc())
            .limit(10)
            .all()
        )
        rejections_details = [
            {
                "timestamp": _iso(rej.created_at),
                "market_ticker": rej.market_ticker,
                "status": rej.status,
                "phase": rej.phase,
                "reason_code": rej.reason_code,
                "reason": rej.reason,
                "requested_size": rej.requested_size,
                "adjusted_size": rej.adjusted_size,
            }
            for rej in recent_rejections
        ]

        result.append(
            {
                "strategy": name,
                "enabled": enabled,
                "trading_mode": effective_mode,
                "last_heartbeat": last_heartbeat,
                "last_scan_time": scan_stats.get("last_scan_time"),
                "markets_scanned": scan_stats.get("markets_scanned", 0),
                "signals_had_edge": scan_stats.get("signals_had_edge", 0),
                "signals_rejected": scan_stats.get("signals_rejected", 0),
                "trades_executed": scan_stats.get("trades_executed", 0),
                "last_signal": last_signal_details,
                "rejections": rejections_details,
            }
        )

    return result


@router.get("/strategies/compare")
async def compare_strategies(db: Session = Depends(get_db)):
    """Compare active strategies side-by-side using PnL and AGI health metrics."""
    from backend.models.database import Trade
    from backend.models.outcome_tables import StrategyHealthRecord
    from sqlalchemy import case

    # Fetch latest AGI health record for each strategy
    all_health = db.query(StrategyHealthRecord).order_by(StrategyHealthRecord.last_updated.desc()).all()
    latest_health = {}
    for h in all_health:
        if h.strategy not in latest_health:
            latest_health[h.strategy] = h

    # Fetch trade statistics grouped by strategy
    trade_stats = (
        db.query(
            Trade.strategy,
            func.count(Trade.id).label("total_trades"),
            func.sum(
                case(
                    (Trade.settled.is_(True), case((Trade.pnl > 0, 1), else_=0)),
                    else_=0,
                )
            ).label("wins"),
            func.sum(
                case(
                    (Trade.settled.is_(True), case((Trade.pnl <= 0, 1), else_=0)),
                    else_=0,
                )
            ).label("losses"),
            func.sum(case((Trade.settled, Trade.pnl), else_=0)).label("total_pnl"),
            func.avg(Trade.edge_at_entry).label("avg_edge"),
            func.avg(Trade.size).label("avg_size"),
        )
        .filter(Trade.strategy.isnot(None), Trade.source == "bot")
        .group_by(Trade.strategy)
        .all()
    )

    comparison = {}
    # Incorporate strategies with trades
    for r in trade_stats:
        strat = r.strategy
        h = latest_health.get(strat)
        total_wr_trades = r.wins + r.losses
        comparison[strat] = {
            "total_trades": r.total_trades,
            "wins": r.wins,
            "losses": r.losses,
            "win_rate": r.wins / total_wr_trades if total_wr_trades > 0 else (h.win_rate if h else 0.0),
            "total_pnl": round(r.total_pnl or 0, 2),
            "avg_edge": round(r.avg_edge or 0, 4),
            "avg_size": round(r.avg_size or 0, 2),
            "sharpe": h.sharpe if h else 0.0,
            "max_drawdown": h.max_drawdown if h else None,
            "brier_score": h.brier_score if h else None,
            "psi_score": h.psi_score if h else None,
            "status": h.status if h else "active",
        }

    # Add any strategies that have an AGI health record but no trades yet
    for strat, h in latest_health.items():
        if strat not in comparison:
            comparison[strat] = {
                "total_trades": h.total_trades,
                "wins": h.wins,
                "losses": h.losses,
                "win_rate": h.win_rate,
                "total_pnl": 0.0,
                "avg_edge": 0.0,
                "avg_size": 0.0,
                "sharpe": h.sharpe,
                "max_drawdown": h.max_drawdown,
                "brier_score": h.brier_score,
                "psi_score": h.psi_score,
                "status": h.status,
            }

    return comparison


class StrategyUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    interval_seconds: Optional[int] = None
    params: Optional[dict] = None
    trading_mode: Optional[str] = None


@router.get("/strategies/{name}")
async def get_strategy(
    name: str,
    db: Session = Depends(get_db),
):
    """Get a single strategy config by name."""
    from backend.strategies.registry import get_strategy_class
    from backend.strategies.loader import load_all_strategies
    from backend.strategies.registry import STRATEGY_REGISTRY

    if not STRATEGY_REGISTRY:
        load_all_strategies()
    if name not in STRATEGY_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")
    cfg = db.query(StrategyConfig).filter(StrategyConfig.strategy_name == name).first()
    try:
        cls = get_strategy_class(name)
        description = getattr(cls, "description", name)
        category = getattr(cls, "category", "general")
        default_params = getattr(cls, "default_params", {})
    except Exception:
        logger.exception(
            f"Failed to get strategy class '{name}', using fallback defaults"
        )
        description, category, default_params = name, "unknown", {}
    return {
        "name": name,
        "description": description,
        "category": category,
        "enabled": cfg.enabled if cfg else True,
        "interval_seconds": cfg.interval_seconds if cfg else 300,
        "params": _json.loads(cfg.params) if cfg and cfg.params else {},
        "default_params": default_params,
        "updated_at": _iso(cfg.updated_at) if cfg and cfg.updated_at else None,
        "trading_mode": cfg.trading_mode if cfg else None,
    }


@router.put("/strategies/{name}")
async def update_strategy(
    name: str,
    body: ValidatedStrategyConfigRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Update a strategy's config (enabled, interval, params)."""
    from backend.strategies.registry import STRATEGY_REGISTRY
    from backend.models.audit_logger import log_audit_event

    if name not in STRATEGY_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")

    cfg = db.query(StrategyConfig).filter(StrategyConfig.strategy_name == name).first()

    old_state = None
    if cfg:
        old_state = {
            "enabled": cfg.enabled,
            "interval_seconds": cfg.interval_seconds,
            "params": _json.loads(cfg.params) if cfg.params else {},
            "trading_mode": cfg.trading_mode,
        }
    else:
        cfg = StrategyConfig(strategy_name=name)
        db.add(cfg)

    if body.enabled is not None:
        cfg.enabled = body.enabled
    if body.interval_seconds is not None:
        cfg.interval_seconds = body.interval_seconds
    if body.params is not None:
        cfg.params = _json.dumps(body.params)
    if body.trading_mode is not None:
        valid_modes = ["paper", "testnet", "live", None]
        if body.trading_mode not in valid_modes:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid trading_mode '{body.trading_mode}'. Must be one of: paper, testnet, live",
            )
        cfg.trading_mode = body.trading_mode

    new_state = {
        "enabled": cfg.enabled,
        "interval_seconds": cfg.interval_seconds,
        "params": _json.loads(cfg.params) if cfg.params else {},
        "trading_mode": cfg.trading_mode,
    }

    log_audit_event(
        db=db,
        event_type="STRATEGY_CONFIG_UPDATED",
        entity_type="STRATEGY_CONFIG",
        entity_id=name,
        old_value=old_state,
        new_value=new_state,
        user_id="admin",
    )

    db.commit()
    db.refresh(cfg)

    if body.interval_seconds is not None or body.enabled is not None:
        from backend.core.scheduler import schedule_strategy, unschedule_strategy

        if cfg.enabled:
            schedule_strategy(name, cfg.interval_seconds or 60)
        else:
            unschedule_strategy(name)

    return {
        "name": name,
        "enabled": cfg.enabled,
        "interval_seconds": cfg.interval_seconds,
        "params": _json.loads(cfg.params) if cfg.params else {},
        "updated_at": _iso(cfg.updated_at),
        "trading_mode": cfg.trading_mode,
    }


@router.post("/strategies/{name}/run-now")
async def run_strategy_now(name: str, _: None = Depends(require_admin)):
    """Trigger an immediate strategy run."""
    from backend.strategies.registry import STRATEGY_REGISTRY, create_strategy

    if name not in STRATEGY_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")

    # Build a proper StrategyContext and run the strategy
    try:
        from backend.strategies.base import StrategyContext
        from backend.models.database import BotState, StrategyConfig

        from backend.db.utils import get_db_session

        with get_db_session() as db:
            # STRAT-13 FIX: Use create_strategy() to check if strategy is enabled
            instance = create_strategy(name, db=db)
            cfg = (
                db.query(StrategyConfig)
                .filter(StrategyConfig.strategy_name == name)
                .first()
            )
            strategy_mode = (
                cfg.trading_mode if cfg and cfg.trading_mode else None
            ) or settings.TRADING_MODE

            state = db.query(BotState).filter_by(mode=strategy_mode).first()
            if not state:
                raise HTTPException(status_code=404, detail="Bot state not initialized")
            from backend.markets.provider_registry import market_registry

            ctx = StrategyContext(
                db=db,
                clob=None,
                settings=settings,
                logger=logger,
                params=dict(getattr(instance.__class__, "default_params", {})),
                mode=strategy_mode,
                market_registry=market_registry,
            )
            result = await instance.run(ctx)

            buy_decisions = [
                d
                for d in getattr(result, "decisions", [])
                if isinstance(d, dict)
                and d.get("decision") == "BUY"
                and d.get("market_ticker")
            ]

        # Execute decisions OUTSIDE the outer session — execute_decision opens
        # its own session per trade to avoid holding the caller session during
        # async I/O (prevents event-loop blocking and stale-session bugs).
        if buy_decisions:
            from backend.core.strategy_executor import execute_decisions

            execution_modes = (
                ["paper", "live"] if strategy_mode == "live" else [strategy_mode]
            )
            for mode in execution_modes:
                decisions_copy = [d.copy() for d in buy_decisions]
                for d in decisions_copy:
                    d["trading_mode"] = mode
                await execute_decisions(decisions_copy, name, mode)

        return {
            "status": "ok",
            "name": name,
            "decisions": result.decisions_recorded,
            "trades_attempted": result.trades_attempted,
            "errors": len(result.errors),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Manual run of strategy '{name}' failed: {e}")
        raise HTTPException(
            status_code=500, detail="Strategy run failed — check server logs"
        )


@router.get("/health/mirofish")
async def get_mirofish_health():
    """Get MiroFish service health status with circuit breaker state."""
    try:
        from backend.services.mirofish_monitor import get_monitor

        monitor = get_monitor()
        metrics = monitor.get_health_metrics()
        state_info = monitor.get_state_info()

        return {
            "status": metrics.status,
            "latency_ms": round(metrics.latency_ms, 2),
            "error_rate": round(metrics.error_rate, 2),
            "circuit_breaker_state": metrics.circuit_breaker_state,
            "total_requests": metrics.total_requests,
            "failed_requests": metrics.failed_requests,
            "consecutive_failures": metrics.consecutive_failures,
            "last_success_time": metrics.last_success_time,
            "last_failure_time": metrics.last_failure_time,
            "state_info": state_info,
        }
    except Exception as e:
        logger.error(f"Failed to get MiroFish health: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "circuit_breaker_state": "UNKNOWN"}


@router.get("/system/db-pool-stats")
async def get_db_pool_stats(_: None = Depends(require_admin)):
    """Get database connection pool statistics."""

    try:
        pool = engine.pool

        return {
            "pool_size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "queue_size": pool.size() - pool.checkedout() - pool.overflow(),
            "total_connections": pool.size() + pool.overflow(),
            "config": {
                "pool_size": 20,
                "max_overflow": 10,
                "pool_timeout": 30,
                "pool_recycle": 3600,
            },
        }
    except Exception as e:
        logger.error(f"Failed to get pool stats: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get pool stats: {str(e)}"
        )


class AuditLogResponse(BaseModel):
    id: int
    timestamp: datetime
    event_type: str
    entity_type: str
    entity_id: str
    old_value: Optional[dict]
    new_value: Optional[dict]
    user_id: str


@router.get("/system/audit-logs", response_model=List[AuditLogResponse])
async def get_audit_logs(
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    entity_id: Optional[str] = Query(None, description="Filter by entity ID"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    since: Optional[str] = Query(
        None, description="Filter logs since timestamp (ISO format)"
    ),
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of logs to return"
    ),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """
    Retrieve audit logs for configuration changes and system events.

    Returns audit trail entries with filtering and pagination support.
    """
    try:
        query = db.query(AuditLog)

        if event_type:
            query = query.filter(AuditLog.event_type == event_type)

        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)

        if entity_id:
            query = query.filter(AuditLog.entity_id == entity_id)

        if user_id:
            query = query.filter(AuditLog.user_id == user_id)

        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                query = query.filter(AuditLog.timestamp >= since_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid timestamp format")

        _total = query.count()

        logs = (
            query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()
        )

        return [
            AuditLogResponse(
                id=log.id,
                timestamp=log.timestamp,
                event_type=log.event_type,
                entity_type=log.entity_type,
                entity_id=log.entity_id,
                old_value=log.old_value,
                new_value=log.new_value,
                user_id=log.user_id,
            )
            for log in logs
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve audit logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve audit logs")


# ============================================================================
# Health Check Endpoints
# ============================================================================


class HealthStatus(BaseModel):
    """Basic health status response."""

    status: str
    agi_events: dict = {}  # "healthy" or "unhealthy"


class ReadinessStatus(BaseModel):
    """Readiness check with dependency status."""

    status: str  # "ready" or "not_ready"
    database: str  # "connected" or "disconnected"
    redis: Optional[str] = (
        None  # "connected", "disconnected", or None if not configured
    )


class DetailedHealthStatus(BaseModel):
    status: str
    timestamp: str
    database: dict
    redis: Optional[dict] = None
    disk_space: dict
    memory: dict
    uptime_seconds: Optional[float] = None
    circuit_breakers: Optional[dict] = None
    avg_signal_time_ms: Optional[float] = None
    signals_24h: Optional[int] = None
    trades_24h: Optional[int] = None


@router.get("/health", response_model=HealthStatus)
async def health_check():
    """
    Basic liveness check. Returns 200 OK if service is running.
    No dependencies checked - purely for load balancer/orchestrator.
    """
    agi_health = {}
    try:
        from backend.core.agi_event_handlers import check_agi_health

        agi_health = check_agi_health()
    except Exception:
        logger.exception("Failed to check AGI health in liveness endpoint")
    return {"status": "healthy", "agi_events": agi_health}


@router.get("/health/live", response_model=HealthStatus, include_in_schema=False)
async def health_live_check():
    """Backward-compatible liveness alias for common /health/live probes."""

    return await health_check()


@router.get("/health/agi")
async def agi_health_check():
    """Return AGI event handler health status."""
    from backend.core.agi_event_handlers import check_agi_health

    return check_agi_health()


@router.get("/health/ready", response_model=ReadinessStatus, status_code=200)
async def readiness_check(db: Session = Depends(get_db)):
    """
    Readiness check with critical dependency verification.
    Returns 200 if ready, 503 if not ready.
    Checks: database connectivity, Redis (if configured).
    """
    database_status = "disconnected"
    redis_status = None

    # Check database connectivity
    try:
        db.execute(text("SELECT 1"))
        database_status = "connected"
    except Exception as e:
        logger.warning(f"Database readiness check failed: {e}")
        return ReadinessStatus(
            status="not_ready", database=database_status, redis=redis_status
        )

    # Check Redis if configured
    if settings.REDIS_URL:
        try:
            import redis

            r = redis.from_url(
                settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2
            )
            r.ping()
            redis_status = "connected"
        except Exception as e:
            logger.warning(f"Redis readiness check failed: {e}")
            redis_status = "disconnected"
            return ReadinessStatus(
                status="not_ready", database=database_status, redis=redis_status
            )

    return ReadinessStatus(status="ready", database=database_status, redis=redis_status)


@router.get("/health/detailed", response_model=DetailedHealthStatus, status_code=200)
async def detailed_health_check(db: Session = Depends(get_db)):
    """
    Comprehensive system health status with full metrics.
    Returns 200 if healthy, 503 if unhealthy.
    Checks: database, Redis, disk space, memory usage, circuit breakers.
    """
    from backend.core.circuit_breaker_pybreaker import get_breaker_status

    timestamp = datetime.now(timezone.utc).isoformat()
    is_healthy = True

    # Database check
    database_info = {"status": "disconnected", "latency_ms": None, "error": None}
    try:
        import time

        start = time.time()
        db.execute(text("SELECT 1"))
        latency_ms = (time.time() - start) * 1000
        database_info["status"] = "connected"
        database_info["latency_ms"] = round(latency_ms, 2)
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        database_info["status"] = "disconnected"
        database_info["error"] = str(e)
        is_healthy = False

    # Redis check (if configured)
    redis_info = None
    if settings.REDIS_URL:
        redis_info = {"status": "disconnected", "latency_ms": None, "error": None}
        try:
            import redis
            import time

            r = redis.from_url(
                settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2
            )
            start = time.time()
            r.ping()
            latency_ms = (time.time() - start) * 1000
            redis_info["status"] = "connected"
            redis_info["latency_ms"] = round(latency_ms, 2)
        except Exception as e:
            logger.warning(f"Redis health check failed: {e}")
            redis_info["status"] = "disconnected"
            redis_info["error"] = str(e)

    # Circuit breaker status
    circuit_breakers = get_breaker_status()

    # Disk space check
    disk_info = {
        "status": "ok",
        "total_gb": 0,
        "used_gb": 0,
        "free_gb": 0,
        "percent_used": 0,
        "warning": None,
    }
    try:
        disk_usage = psutil.disk_usage("/")
        disk_info["total_gb"] = round(disk_usage.total / (1024**3), 2)
        disk_info["used_gb"] = round(disk_usage.used / (1024**3), 2)
        disk_info["free_gb"] = round(disk_usage.free / (1024**3), 2)
        disk_info["percent_used"] = disk_usage.percent

        if disk_usage.percent > 90:
            disk_info["status"] = "critical"
            disk_info["warning"] = "Disk usage above 90%"
            is_healthy = False
        elif disk_usage.percent > 80:
            disk_info["status"] = "warning"
            disk_info["warning"] = "Disk usage above 80%"
    except Exception as e:
        logger.warning(f"Disk space check failed: {e}")
        disk_info["status"] = "unknown"
        disk_info["error"] = str(e)

    # Memory check
    memory_info = {
        "status": "ok",
        "total_gb": 0,
        "used_gb": 0,
        "available_gb": 0,
        "percent_used": 0,
        "warning": None,
    }
    try:
        mem = psutil.virtual_memory()
        memory_info["total_gb"] = round(mem.total / (1024**3), 2)
        memory_info["used_gb"] = round(mem.used / (1024**3), 2)
        memory_info["available_gb"] = round(mem.available / (1024**3), 2)
        memory_info["percent_used"] = mem.percent

        if mem.percent > 90:
            memory_info["status"] = "critical"
            memory_info["warning"] = "Memory usage above 90%"
            is_healthy = False
        elif mem.percent > 80:
            memory_info["status"] = "warning"
            memory_info["warning"] = "Memory usage above 80%"
    except Exception as e:
        logger.warning(f"Memory check failed: {e}")
        memory_info["status"] = "unknown"
        memory_info["error"] = str(e)

    # Uptime (if available from process)
    uptime_seconds = None
    try:
        process = psutil.Process(os.getpid())
        uptime_seconds = time.time() - process.create_time()
    except Exception:
        logger.exception("Failed to read process uptime in health check")

    status = "healthy" if is_healthy else "unhealthy"
    _status_code = 200 if is_healthy else 503

    avg_signal_time_ms = None
    signals_24h = None
    trades_24h = None
    try:
        from backend.monitoring.metrics import get_metrics_snapshot

        metrics = get_metrics_snapshot()
        avg_signal_time_ms = metrics.get("avg_api_latency_ms")
        signals_24h = (
            db.query(Signal)
            .filter(
                Signal.created_at >= datetime.now(timezone.utc) - timedelta(hours=24)
            )
            .count()
            if db
            else 0
        )
        trades_24h = (
            db.query(Trade)
            .filter(
                Trade.created_at >= datetime.now(timezone.utc) - timedelta(hours=24)
            )
            .count()
            if db
            else 0
        )
    except Exception:
        logger.exception("Failed to collect metrics in health check")

    return DetailedHealthStatus(
        status=status,
        timestamp=timestamp,
        database=database_info,
        redis=redis_info,
        disk_space=disk_info,
        memory=memory_info,
        uptime_seconds=uptime_seconds,
        circuit_breakers=circuit_breakers,
        avg_signal_time_ms=avg_signal_time_ms,
        signals_24h=signals_24h,
        trades_24h=trades_24h,
    )


@router.get("/system/connection-limits")
async def get_connection_limits(db: Session = Depends(get_db)):
    """Get current connection limits and usage metrics."""
    from backend.api.connection_limits import connection_limiter

    metrics = await connection_limiter.get_metrics()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "connection_limits": metrics,
    }


@router.post("/redeem")
async def redeem_positions(
    _: None = Depends(require_admin),
    dry_run: bool = Query(
        True, description="If true, only report what would be redeemed"
    ),
):
    from backend.core.auto_redeem import redeem_all_redeemable

    wallet = settings.POLYMARKET_BUILDER_ADDRESS or ""
    private_key = settings.POLYMARKET_PRIVATE_KEY or ""
    if not wallet or not private_key:
        raise HTTPException(
            status_code=500,
            detail="POLYMARKET_BUILDER_ADDRESS or POLYMARKET_PRIVATE_KEY not set",
        )
    result = redeem_all_redeemable(
        wallet=wallet,
        private_key=private_key,
        builder_api_key=settings.POLYMARKET_BUILDER_API_KEY,
        builder_secret=settings.POLYMARKET_BUILDER_SECRET,
        builder_passphrase=settings.POLYMARKET_BUILDER_PASSPHRASE,
        dry_run=dry_run,
    )
    return {
        "status": "dry_run" if dry_run else "executed",
        "attempted": result.total_attempted,
        "redeemed": result.total_redeemed,
        "failed": result.total_failed,
        "usdc_recovered": result.total_usdc_recovered,
        "errors": result.errors,
        "results": [
            {
                "condition_id": r.condition_id,
                "success": r.success,
                "tx_hash": r.tx_hash,
                "error": r.error,
            }
            for r in result.results
        ],
    }


@router.get("/hft/metrics")
async def hft_metrics():
    from backend.monitoring.hft_metrics import get_hft_summary

    summary = get_hft_summary()
    return {
        "signals_per_second": summary.get("signals_per_second", 0.0),
        "avg_signal_latency_ms": summary.get("avg_latency_ms", 0.0),
        "executor_latency_ms": summary.get("executor_latency_ms", 0.0),
        "dispatcher_queue_size": summary.get("queue_size", 0),
        "active_strategies": summary.get("active_strategies", 0),
        "arb_opportunities": summary.get("arb_opportunities", 0),
        "whale_activities": summary.get("whale_activities", 0),
        "orderbook_updates_per_sec": summary.get("orderbook_updates_per_sec", 0.0),
        "ws_connected": True,
    }


@router.get("/hft/strategies")
async def hft_strategies(db: Session = Depends(get_db)):
    from backend.strategies.registry import STRATEGY_REGISTRY
    from backend.models.database import StrategyConfig

    hft_names = {
        "universal_scanner",
        "probability_arb",
        "cross_market_arb",
        "whale_frontrun",
    }
    strategies = []
    for name in STRATEGY_REGISTRY:
        if name in hft_names:
            config = (
                db.query(StrategyConfig)
                .filter(StrategyConfig.strategy_name == name)
                .first()
            )
            strategies.append(
                {
                    "name": name,
                    "enabled": config.enabled if config else True,
                    "signals_generated": 0,
                    "last_signal_at": (
                        _iso(config.updated_at)
                        if config and config.updated_at
                        else None
                    ),
                    "pnl": 0.0,
                    "mode": config.trading_mode or "paper" if config else "paper",
                }
            )
    if not strategies:
        for name in hft_names:
            config = (
                db.query(StrategyConfig)
                .filter(StrategyConfig.strategy_name == name)
                .first()
            )
            strategies.append(
                {
                    "name": name,
                    "enabled": config.enabled if config else True,
                    "signals_generated": 0,
                    "last_signal_at": None,
                    "pnl": 0.0,
                    "mode": "paper",
                }
            )
    return {"strategies": strategies}


@router.post("/hft/strategies/toggle")
async def hft_strategy_toggle(
    req: dict,
    _: None = Depends(require_admin),
):
    global _hft_enabled_cache
    name = req.get("name", "")
    enabled = bool(req.get("enabled", False))
    if enabled:
        _hft_enabled_cache.add(name)
    else:
        _hft_enabled_cache.discard(name)
    return {"name": name, "enabled": enabled, "status": "ok"}
