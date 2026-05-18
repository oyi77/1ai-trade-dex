"""Position monitor — detect stale open positions AND generate sell signals.

Provides two monitoring functions:

1. **Stale position detection** (existing): identifies open positions that have
   not been refreshed within the configured stale window.

2. **Sell signal generation** (new): tracks all open positions, polls current
   market probability, computes unrealised PnL, and emits sell signals when
   profit-taking, stop-loss, or time-decay thresholds are crossed.  Designed
   to close the 948-buy-vs-4-sell gap.

Sell signals are routed through the existing auto_trader / strategy_executor
pipeline and respect ``SHADOW_MODE`` — they are marked as paper/shadow until
validated.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from loguru import logger

from backend.config import settings
from backend.core.alert_manager import AlertManager
from backend.db.utils import get_db_session
from backend.models.database import Trade


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Stale window. 30 minutes per task spec. Override with env STALE_POSITION_MINUTES.
STALE_INTERVAL_MINUTES: int = int(
    getattr(settings, "STALE_POSITION_MINUTES", 30) or 30
)

# Sell-signal thresholds (configurable via settings / env)
PROFIT_TAKE_PROBABILITY: float = float(
    getattr(settings, "SELL_PROFIT_TAKE_PROBABILITY", 0.80)
)
STOP_LOSS_DROP_PP: float = float(
    getattr(settings, "SELL_STOP_LOSS_DROP_PP", 0.15)
)
TIME_DECAY_MINUTES: int = int(
    getattr(settings, "SELL_TIME_DECAY_MINUTES", 60)
)
SELL_SIGNAL_MIN_EDGE: float = float(
    getattr(settings, "SELL_SIGNAL_MIN_EDGE", 0.02)
)

# Sell monitor interval (separate from stale detection)
SELL_MONITOR_INTERVAL_MINUTES: int = int(
    getattr(settings, "SELL_MONITOR_INTERVAL_MINUTES", 5) or 5
)


@dataclass(frozen=True)
class StalePosition:
    """Lightweight snapshot of a stale open trade."""

    trade_id: int
    market_ticker: Optional[str]
    strategy: Optional[str]
    trading_mode: str
    direction: Optional[str]
    size: Optional[float]
    opened_at: Optional[datetime]
    last_sync_at: Optional[datetime]
    age_minutes: float

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "market_ticker": self.market_ticker,
            "strategy": self.strategy,
            "trading_mode": self.trading_mode,
            "direction": self.direction,
            "size": self.size,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "last_sync_at": (
                self.last_sync_at.isoformat() if self.last_sync_at else None
            ),
            "age_minutes": round(self.age_minutes, 2),
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Treat naive timestamps from SQLite as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _latest_touch(trade: Trade) -> Optional[datetime]:
    """Return the most recent monitoring touch for ``trade``.

    Falls back to ``timestamp`` (entry time) if no sync has happened yet — a
    trade that has never been monitored is considered stale by age alone.
    """
    candidates = [
        _as_aware(getattr(trade, "last_sync_at", None)),
        _as_aware(getattr(trade, "timestamp", None)),
    ]
    valid = [c for c in candidates if c is not None]
    return max(valid) if valid else None


def detect_stale_positions(
    db: Session,
    *,
    stale_after_minutes: int = STALE_INTERVAL_MINUTES,
    trading_modes: Optional[Iterable[str]] = None,
    now: Optional[datetime] = None,
) -> List[StalePosition]:
    """Return all open trades whose last monitor touch is older than the window.

    Args:
        db: Active SQLAlchemy session.
        stale_after_minutes: Threshold in minutes. Default 30.
        trading_modes: Optional filter (e.g. ``{"live", "testnet"}``). When
            ``None`` all modes are scanned.
        now: Reference timestamp for tests. Defaults to ``datetime.now(UTC)``.
    """
    reference = now or _now()
    cutoff = reference - timedelta(minutes=stale_after_minutes)

    query = db.query(Trade).filter(Trade.settled.is_(False))
    if trading_modes:
        query = query.filter(Trade.trading_mode.in_(list(trading_modes)))

    # Pull rows where either last_sync_at or fallback timestamp predates cutoff.
    # We compare in Python to keep tz-aware semantics consistent across SQLite/PG.
    query = query.filter(
        or_(
            Trade.last_sync_at.is_(None),
            Trade.last_sync_at <= cutoff,
        )
    )

    stale: List[StalePosition] = []
    for trade in query.all():
        touched = _latest_touch(trade)
        if touched is None:
            age = float("inf")
        else:
            age = (reference - touched).total_seconds() / 60.0

        if age < stale_after_minutes:
            # last_sync_at was old but entry timestamp is fresh — skip.
            continue

        stale.append(
            StalePosition(
                trade_id=trade.id,
                market_ticker=trade.market_ticker,
                strategy=trade.strategy,
                trading_mode=trade.trading_mode or "paper",
                direction=trade.direction,
                size=trade.size,
                opened_at=_as_aware(trade.timestamp),
                last_sync_at=_as_aware(trade.last_sync_at),
                age_minutes=age if age != float("inf") else -1.0,
            )
        )
    return stale


def mark_position_checked(db: Session, trade_id: int) -> None:
    """Stamp ``last_sync_at`` so a trade is not re-flagged immediately."""
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if trade is None:
        return
    trade.last_sync_at = _now()


def _alert_stale(db: Session, stale: List[StalePosition]) -> None:
    if not stale:
        return
    try:
        alerts = AlertManager(db)
    except Exception:  # pragma: no cover - defensive
        logger.exception("AlertManager init failed in position_monitor")
        return

    for entry in stale:
        message = (
            f"Stale open position detected: trade_id={entry.trade_id} "
            f"market={entry.market_ticker} strategy={entry.strategy} "
            f"mode={entry.trading_mode} age_min={entry.age_minutes:.1f}"
        )
        try:
            alerts.create_alert(  # type: ignore[attr-defined]
                kind="stale_position",
                severity="warning",
                message=message,
                meta=entry.to_dict(),
            )
        except Exception:
            # AlertManager API may differ across deployments — fall back to log.
            logger.warning(message)


def run_position_monitor(
    *,
    stale_after_minutes: int = STALE_INTERVAL_MINUTES,
    trading_modes: Optional[Iterable[str]] = None,
    db: Optional[Session] = None,
) -> List[StalePosition]:
    """Top-level entry point — detect, alert, mark, and return stale positions.

    Designed to be invoked by APScheduler on a 30-minute IntervalTrigger:

        scheduler.add_job(
            run_position_monitor,
            IntervalTrigger(minutes=STALE_INTERVAL_MINUTES),
            id="position_monitor",
        )
    """
    if db is not None:
        stale = detect_stale_positions(
            db,
            stale_after_minutes=stale_after_minutes,
            trading_modes=trading_modes,
        )
        _alert_stale(db, stale)
        for entry in stale:
            mark_position_checked(db, entry.trade_id)
        logger.info(
            "Position monitor pass complete",
            stale_count=len(stale),
            threshold_minutes=stale_after_minutes,
        )
        return stale

    with get_db_session() as session:
        stale = detect_stale_positions(
            session,
            stale_after_minutes=stale_after_minutes,
            trading_modes=trading_modes,
        )
        _alert_stale(session, stale)
        for entry in stale:
            mark_position_checked(session, entry.trade_id)
        logger.info(
            "Position monitor pass complete",
            stale_count=len(stale),
            threshold_minutes=stale_after_minutes,
        )
        return stale


async def position_monitor_job() -> None:
    """APScheduler-compatible async wrapper around :func:`run_position_monitor`."""
    import asyncio

    await asyncio.to_thread(run_position_monitor)


# ===================================================================
# Sell signal generation
# ===================================================================


@dataclass
class OpenPositionSnapshot:
    """Snapshot of an open position with current market data for sell evaluation."""

    trade_id: int
    market_ticker: str
    strategy: Optional[str]
    trading_mode: str
    direction: Optional[str]  # "up" / "down"
    entry_price: float
    size: float
    market_price_at_entry: Optional[float]
    market_end_date: Optional[datetime]
    opened_at: Optional[datetime]
    current_price: Optional[float]  # current yes-probability
    unrealized_pnl: float
    unrealized_pnl_pct: float


@dataclass
class SellSignal:
    """A sell signal generated by the position monitor."""

    trade_id: int
    market_ticker: str
    strategy: Optional[str]
    trading_mode: str
    direction: str
    size: float
    trigger: str  # "profit_take", "stop_loss", "time_decay"
    reason: str
    entry_price: float
    current_price: float
    unrealized_pnl: float
    confidence: float


def _fetch_current_price(ticker: str) -> Optional[float]:
    """Fetch current yes-price for a market ticker using Gamma/CLOB API.

    Uses synchronous httpx to stay compatible with the thread-pool execution
    context of position_monitor_job.  Returns ``None`` on failure so callers
    can skip the position rather than crashing.
    """
    import httpx

    if not ticker:
        return None

    try:
        if ticker.isdigit():
            # Token ID — use CLOB midpoint
            r = httpx.get(
                f"{settings.CLOB_API_URL}/midpoint?token_id={ticker}",
                timeout=5.0,
            )
            r.raise_for_status()
            data = r.json()
            return float(data.get("mid", 0.5))
        else:
            # Slug — use Gamma API
            r = httpx.get(
                f"{settings.GAMMA_API_URL}/markets?slug={ticker}",
                timeout=5.0,
            )
            r.raise_for_status()
            data = r.json()
            if data and isinstance(data, list) and len(data) > 0:
                return float(data[0].get("yes_price", 0.5))
    except Exception as exc:
        logger.debug("Failed to fetch price for {}: {}", ticker, exc)
    return None


_price_pool = concurrent.futures.ThreadPoolExecutor(max_workers=10)


def _fetch_prices_bulk(tickers: List[str]) -> Dict[str, float]:
    """Fetch prices for multiple tickers in parallel (sync, thread-safe).

    Returns a dict mapping ticker to current yes-price.  Tickers that fail
    are silently omitted so callers can fall back to entry price.
    """
    results: Dict[str, float] = {}
    futures = {_price_pool.submit(_fetch_current_price, t): t for t in tickers}
    for fut in concurrent.futures.as_completed(futures):
        ticker = futures[fut]
        try:
            price = fut.result()
            if price is not None:
                results[ticker] = price
        except Exception:
            logger.debug("Price fetch failed for %s", ticker, exc_info=True)
    return results


def _get_open_positions(
    db: Session,
    trading_modes: Optional[Iterable[str]] = None,
) -> List[Trade]:
    """Return all unsettled trades, optionally filtered by mode."""
    query = db.query(Trade).filter(Trade.settled.is_(False))
    if trading_modes:
        query = query.filter(Trade.trading_mode.in_(list(trading_modes)))
    return query.all()


def _build_snapshot(
    trade: Trade,
    current_price: Optional[float],
) -> OpenPositionSnapshot:
    """Build a position snapshot combining DB data with live price."""
    entry = float(trade.entry_price or 0.5)
    size = float(trade.size or 0.0)

    # Determine effective current price
    price = current_price
    if price is None:
        price = float(trade.market_price_at_entry or entry)
    price = max(0.01, min(0.99, price))

    # PnL calculation: shares = size / entry, current_value = shares * current_price
    if entry > 0 and entry < 1:
        shares = size / entry
        current_value = shares * price
    else:
        current_value = size

    unrealized_pnl = current_value - size
    unrealized_pnl_pct = (unrealized_pnl / size * 100) if size > 0 else 0.0

    return OpenPositionSnapshot(
        trade_id=trade.id,
        market_ticker=trade.market_ticker or "",
        strategy=trade.strategy,
        trading_mode=trade.trading_mode or "paper",
        direction=trade.direction,
        entry_price=entry,
        size=size,
        market_price_at_entry=trade.market_price_at_entry,
        market_end_date=_as_aware(trade.market_end_date),
        opened_at=_as_aware(trade.timestamp),
        current_price=price,
        unrealized_pnl=round(unrealized_pnl, 4),
        unrealized_pnl_pct=round(unrealized_pnl_pct, 2),
    )


def _evaluate_sell_triggers(
    snapshot: OpenPositionSnapshot,
) -> Optional[SellSignal]:
    """Check whether a position should be sold based on configured thresholds.

    Returns a ``SellSignal`` if any trigger fires, otherwise ``None``.

    Triggers (in priority order):
    1. **Profit-taking**: current probability > 80 % when bought near 50 %.
    2. **Stop-loss**: probability dropped > 15 pp below entry.
    3. **Time decay**: settlement < 1 hour away AND edge is marginal (< 2 pp).
    """
    entry = snapshot.entry_price
    current = snapshot.current_price
    now = _now()

    # --- 1. Profit-taking ---
    # Sell when probability is very high (position is deep in the money).
    if current >= PROFIT_TAKE_PROBABILITY and entry < PROFIT_TAKE_PROBABILITY:
        confidence = min(0.95, 0.7 + (current - PROFIT_TAKE_PROBABILITY) * 2)
        return SellSignal(
            trade_id=snapshot.trade_id,
            market_ticker=snapshot.market_ticker,
            strategy=snapshot.strategy,
            trading_mode=snapshot.trading_mode,
            direction=snapshot.direction or "up",
            size=snapshot.size,
            trigger="profit_take",
            reason=(
                f"Profit-taking: current prob {current:.2%} >= "
                f"{PROFIT_TAKE_PROBABILITY:.0%} threshold (entry {entry:.2%})"
            ),
            entry_price=entry,
            current_price=current,
            unrealized_pnl=snapshot.unrealized_pnl,
            confidence=round(confidence, 3),
        )

    # --- 2. Stop-loss ---
    # Sell when probability has dropped significantly below entry.
    drop = entry - current
    if drop >= STOP_LOSS_DROP_PP:
        confidence = min(0.95, 0.6 + drop * 2)
        return SellSignal(
            trade_id=snapshot.trade_id,
            market_ticker=snapshot.market_ticker,
            strategy=snapshot.strategy,
            trading_mode=snapshot.trading_mode,
            direction=snapshot.direction or "up",
            size=snapshot.size,
            trigger="stop_loss",
            reason=(
                f"Stop-loss: prob dropped {drop:.2%} from entry {entry:.2%} "
                f"to {current:.2%} (threshold {STOP_LOSS_DROP_PP:.0%})"
            ),
            entry_price=entry,
            current_price=current,
            unrealized_pnl=snapshot.unrealized_pnl,
            confidence=round(confidence, 3),
        )

    # --- 3. Time decay ---
    # Sell when settlement is imminent and edge is marginal.
    if snapshot.market_end_date is not None:
        minutes_to_settlement = (
            snapshot.market_end_date - now
        ).total_seconds() / 60.0
        if 0 < minutes_to_settlement <= TIME_DECAY_MINUTES:
            edge = abs(current - entry)
            if edge < SELL_SIGNAL_MIN_EDGE:
                confidence = min(0.85, 0.5 + (TIME_DECAY_MINUTES - minutes_to_settlement) / TIME_DECAY_MINUTES * 0.3)
                return SellSignal(
                    trade_id=snapshot.trade_id,
                    market_ticker=snapshot.market_ticker,
                    strategy=snapshot.strategy,
                    trading_mode=snapshot.trading_mode,
                    direction=snapshot.direction or "up",
                    size=snapshot.size,
                    trigger="time_decay",
                    reason=(
                        f"Time decay: {minutes_to_settlement:.0f}min to settlement, "
                        f"edge only {edge:.2%} < {SELL_SIGNAL_MIN_EDGE:.0%} threshold"
                    ),
                    entry_price=entry,
                    current_price=current,
                    unrealized_pnl=snapshot.unrealized_pnl,
                    confidence=round(confidence, 3),
                )

    return None


def detect_sell_signals(
    db: Session,
    trading_modes: Optional[Iterable[str]] = None,
) -> List[SellSignal]:
    """Scan all open positions and return sell signals for those that cross thresholds.

    This is the main entry point for sell-signal generation.  It:
    1. Fetches all unsettled trades from DB.
    2. Bulk-fetches current market prices.
    3. Evaluates profit-take / stop-loss / time-decay triggers.
    4. Returns the list of generated ``SellSignal`` objects.
    """
    trades = _get_open_positions(db, trading_modes)
    if not trades:
        return []

    # Collect unique tickers for bulk price fetch
    tickers = list({t.market_ticker for t in trades if t.market_ticker})
    prices = _fetch_prices_bulk(tickers) if tickers else {}

    signals: List[SellSignal] = []
    for trade in trades:
        ticker = trade.market_ticker or ""
        current_price = prices.get(ticker)
        snapshot = _build_snapshot(trade, current_price)
        signal = _evaluate_sell_triggers(snapshot)
        if signal is not None:
            signals.append(signal)

    if signals:
        logger.info(
            "Sell signal scan complete: {} signals from {} open positions",
            len(signals),
            len(trades),
        )

    return signals


async def execute_sell_signals(
    signals: List[SellSignal],
    *,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Execute sell signals through the auto_trader / strategy_executor pipeline.

    Each sell signal is routed as a SELL-side decision.  In ``SHADOW_MODE``
    (default) signals are logged but not sent to the CLOB.  When ``dry_run``
    is True, signals are evaluated but not executed at all (useful for testing).

    Returns a list of result dicts for each signal.
    """
    from backend.core.strategy_executor import execute_decision

    results: List[Dict[str, Any]] = []
    shadow = getattr(settings, "SHADOW_MODE", True)

    for sig in signals:
        if dry_run:
            results.append({
                "trade_id": sig.trade_id,
                "trigger": sig.trigger,
                "action": "dry_run",
                "reason": sig.reason,
            })
            continue

        # Build a decision dict compatible with strategy_executor.execute_decision
        decision = {
            "market_ticker": sig.market_ticker,
            "direction": "down" if sig.direction == "up" else "up",
            "side": "SELL",
            "size": sig.size,
            "entry_price": sig.current_price,
            "edge": abs(sig.current_price - sig.entry_price),
            "confidence": sig.confidence,
            "model_probability": sig.current_price,
            "platform": "polymarket",
            "market_type": "btc",
            "reasoning": f"[sell_monitor] {sig.trigger}: {sig.reason}",
        }

        strategy_name = sig.strategy or "sell_monitor"
        mode = sig.trading_mode

        try:
            result = await execute_decision(decision, strategy_name, mode=mode)
            if result:
                results.append({
                    "trade_id": sig.trade_id,
                    "trigger": sig.trigger,
                    "action": "executed",
                    "result": result,
                    "shadow_mode": shadow,
                })
                logger.info(
                    "Sell signal executed: trade_id={} trigger={} mode={} shadow={}",
                    sig.trade_id, sig.trigger, mode, shadow,
                )
            else:
                results.append({
                    "trade_id": sig.trade_id,
                    "trigger": sig.trigger,
                    "action": "blocked",
                    "reason": "execute_decision returned None (duplicate/risk rejection)",
                })
        except Exception as exc:
            logger.exception(
                "Sell signal execution failed: trade_id={} trigger={}",
                sig.trade_id, sig.trigger,
            )
            results.append({
                "trade_id": sig.trade_id,
                "trigger": sig.trigger,
                "action": "error",
                "error": str(exc),
            })

    return results


def run_sell_signal_detect(
    *,
    trading_modes: Optional[Iterable[str]] = None,
    db: Optional[Session] = None,
) -> List[SellSignal]:
    """Synchronous entry point: detect sell signals only (no execution).

    Returns the list of signals for the caller to execute asynchronously.
    """
    if db is not None:
        return detect_sell_signals(db, trading_modes=trading_modes)

    with get_db_session() as session:
        return detect_sell_signals(session, trading_modes=trading_modes)


def _log_sell_decisions(
    db: Session,
    signals: List[SellSignal],
    results: List[Dict[str, Any]],
) -> None:
    """Log sell decisions to DecisionLog for audit trail."""
    from backend.core.decisions import record_decision

    result_by_trade = {r["trade_id"]: r for r in results}
    for sig in signals:
        res = result_by_trade.get(sig.trade_id, {})
        action = res.get("action", "unknown")
        decision_str = "SELL" if action == "executed" else "SKIP"
        record_decision(
            db=db,
            strategy=sig.strategy or "sell_monitor",
            market_ticker=sig.market_ticker,
            decision=decision_str,
            confidence=sig.confidence,
            signal_data={
                "trigger": sig.trigger,
                "entry_price": sig.entry_price,
                "current_price": sig.current_price,
                "unrealized_pnl": sig.unrealized_pnl,
                "reason": sig.reason,
                "execution_action": action,
            },
            reason=f"[sell_monitor] {sig.trigger}: {sig.reason}",
        )


async def sell_signal_monitor_job() -> None:
    """APScheduler-compatible async wrapper for sell-signal monitoring.

    Runs every 5 minutes (configurable via SELL_MONITOR_INTERVAL_MINUTES).
    Scans open positions and generates/executes sell signals.
    """
    import asyncio

    modes = [settings.TRADING_MODE]
    if settings.TRADING_MODE != "paper":
        modes.append("paper")

    try:
        # Detect signals synchronously in a thread (DB + HTTP price fetches)
        signals = await asyncio.to_thread(
            run_sell_signal_detect,
            trading_modes=modes,
        )
        if not signals:
            return

        # Execute sell signals asynchronously (on the event loop)
        results = await execute_sell_signals(signals)

        # Log decisions for audit trail (in thread to avoid blocking loop)
        await asyncio.to_thread(_log_sell_decisions_sync, signals, results)

        logger.info(
            "Sell signal monitor pass complete: {} signals, {} results",
            len(signals),
            len(results),
        )
    except Exception:
        logger.exception("sell_signal_monitor_job failed")


def _log_sell_decisions_sync(
    signals: List[SellSignal],
    results: List[Dict[str, Any]],
) -> None:
    """Synchronous wrapper for logging sell decisions to DB."""
    with get_db_session() as db:
        _log_sell_decisions(db, signals, results)


__all__ = [
    "STALE_INTERVAL_MINUTES",
    "StalePosition",
    "detect_stale_positions",
    "mark_position_checked",
    "run_position_monitor",
    "position_monitor_job",
    # Sell signal additions
    "SELL_MONITOR_INTERVAL_MINUTES",
    "OpenPositionSnapshot",
    "SellSignal",
    "detect_sell_signals",
    "execute_sell_signals",
    "run_sell_signal_detect",
    "sell_signal_monitor_job",
]
