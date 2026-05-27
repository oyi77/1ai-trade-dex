"""Pre-settlement auto-sell (profit-taking) for open positions.

Monitors open positions and sells on the secondary market when profit target,
stop-loss, or max-hold-time thresholds are hit.  More capital-efficient than
waiting for market resolution.

Paper-mode only.  Uses existing CLOB client for sell orders.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from backend.config import settings

# ---------------------------------------------------------------------------
# Defaults (overridable via settings / env)
# ---------------------------------------------------------------------------

_DEFAULT_PROFIT_TARGET_PCT: float = 0.03  # 3 % (must cover ~1% PM fee + 0.5% slippage)
_DEFAULT_STOP_LOSS_PCT: float = 0.03  # 3 %
_DEFAULT_MAX_HOLD_SECONDS: int = 300  # 5 min


def _get_auto_sell_config() -> Dict[str, float]:
    """Read auto-sell settings from config, falling back to defaults."""
    return {
        "profit_target_pct": float(
            getattr(settings, "AUTO_SELL_PROFIT_TARGET_PCT", _DEFAULT_PROFIT_TARGET_PCT)
        ),
        "stop_loss_pct": float(
            getattr(settings, "AUTO_SELL_STOP_LOSS_PCT", _DEFAULT_STOP_LOSS_PCT)
        ),
        "max_hold_seconds": int(
            getattr(settings, "AUTO_SELL_MAX_HOLD_SECONDS", _DEFAULT_MAX_HOLD_SECONDS)
        ),
    }


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class AutoSellResult:
    """Outcome of an auto-sell check."""

    trade_id: int
    market_ticker: str
    triggered: bool
    trigger_reason: Optional[str] = None  # "TAKE_PROFIT" | "STOP_LOSS" | "TIME_EXIT"
    entry_price: float = 0.0
    current_price: float = 0.0
    pnl_pct: float = 0.0
    order_id: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "market_ticker": self.market_ticker,
            "triggered": self.triggered,
            "trigger_reason": self.trigger_reason,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "pnl_pct": round(self.pnl_pct, 6),
            "order_id": self.order_id,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure a timestamp is timezone-aware (treat naive as UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class AutoSellManager:
    """Monitor open positions and auto-sell when profit/loss targets hit.

    Parameters are read from settings (``AUTO_SELL_*``) with sensible defaults.
    Each call to :meth:`check_and_sell` evaluates a single trade and returns
    a sell order result or ``None`` if thresholds are not crossed.
    """

    def __init__(
        self,
        *,
        profit_target_pct: Optional[float] = None,
        stop_loss_pct: Optional[float] = None,
        max_hold_seconds: Optional[int] = None,
    ) -> None:
        cfg = _get_auto_sell_config()
        self.profit_target = (
            profit_target_pct
            if profit_target_pct is not None
            else cfg["profit_target_pct"]
        )
        self.stop_loss = (
            stop_loss_pct if stop_loss_pct is not None else cfg["stop_loss_pct"]
        )
        self.max_hold = (
            max_hold_seconds
            if max_hold_seconds is not None
            else cfg["max_hold_seconds"]
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check_and_sell(
        self,
        trade: Any,
        current_price: float,
        clob_client: Optional[Any] = None,
    ) -> Optional[AutoSellResult]:
        """Check if *trade* should be sold.  Returns :class:`AutoSellResult`
        if a sell was triggered (and optionally executed), otherwise ``None``.

        Args:
            trade: ORM ``Trade`` object (must have ``entry_price``, ``direction``,
                ``timestamp``, ``id``, ``market_ticker``, ``token_id``).
            current_price: Latest yes-price for the market.
            clob_client: CLOB client with ``place_limit_order``.  Pass ``None``
                to get signal-only mode (no order placement).
        """
        entry = float(getattr(trade, "entry_price", 0) or 0)
        if entry <= 0 or entry >= 1:
            logger.debug("[auto_sell] Invalid entry_price={}", entry)
            return None

        direction = (getattr(trade, "direction", "yes") or "yes").lower()
        trade_id = getattr(trade, "id", 0)
        ticker = getattr(trade, "market_ticker", "") or ""
        token_id = getattr(trade, "token_id", None)

        # PnL calculation depends on direction
        if direction == "yes":
            pnl_pct = (current_price - entry) / entry
        else:  # "no"
            pnl_pct = (entry - current_price) / entry

        # Time elapsed since entry
        ts = _as_aware(getattr(trade, "timestamp", None))
        elapsed = (_now_utc() - ts).total_seconds() if ts else float("inf")

        trigger: Optional[str] = None

        if pnl_pct >= self.profit_target:
            trigger = "TAKE_PROFIT"
        elif pnl_pct <= -self.stop_loss:
            trigger = "STOP_LOSS"
        elif elapsed >= self.max_hold:
            trigger = "TIME_EXIT"

        if trigger is None:
            return None

        logger.info(
            "[auto_sell] {} triggered for trade_id={} ticker={} entry={:.4f} "
            "current={:.4f} pnl={:.4f}% elapsed={:.0f}s",
            trigger,
            trade_id,
            ticker,
            entry,
            current_price,
            pnl_pct * 100,
            elapsed,
        )

        result = AutoSellResult(
            trade_id=trade_id,
            market_ticker=ticker,
            triggered=True,
            trigger_reason=trigger,
            entry_price=entry,
            current_price=current_price,
            pnl_pct=pnl_pct,
        )

        # Place sell order if CLOB client provided
        if clob_client is not None and token_id:
            try:
                order_id = await self._place_sell(
                    clob_client=clob_client,
                    token_id=str(token_id),
                    size=float(getattr(trade, "size", 0) or 0),
                    price=current_price,
                )
                result.order_id = order_id
                logger.info(
                    "[auto_sell] Sell order placed: trade_id={} order_id={}",
                    trade_id,
                    order_id,
                )
            except Exception as exc:
                result.error = str(exc)
                logger.exception(
                    "[auto_sell] Sell order failed: trade_id={} error={}",
                    trade_id,
                    exc,
                )

        return result

    async def scan_and_sell_all(
        self,
        trades: List[Any],
        prices: Dict[str, float],
        clob_client: Optional[Any] = None,
    ) -> List[AutoSellResult]:
        """Scan a list of open trades and auto-sell those that trigger.

        Args:
            trades: List of ORM ``Trade`` objects (open/unsettled).
            prices: Dict mapping ``market_ticker`` to current yes-price.
            clob_client: Optional CLOB client for order placement.

        Returns:
            List of :class:`AutoSellResult` for trades that triggered.
        """
        results: List[AutoSellResult] = []
        for trade in trades:
            ticker = getattr(trade, "market_ticker", "") or ""
            price = prices.get(ticker)
            if price is None:
                continue

            result = await self.check_and_sell(trade, price, clob_client)
            if result is not None and result.triggered:
                results.append(result)

        if results:
            logger.info(
                "[auto_sell] Scan complete: {} sells triggered from {} open positions",
                len(results),
                len(trades),
            )

        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    async def _place_sell(
        clob_client: Any,
        token_id: str,
        size: float,
        price: float,
    ) -> str:
        """Place a SELL limit order via the CLOB client.

        Returns the order ID string.
        """
        # Use opposite side: we own YES shares, so we SELL YES (side=SELL).
        result = await clob_client.place_limit_order(
            token_id=token_id,
            side="SELL",
            price=price,
            size=size,
        )
        return getattr(result, "order_id", str(result))


# ---------------------------------------------------------------------------
# Scheduler-compatible async job
# ---------------------------------------------------------------------------


async def auto_sell_monitor_job() -> None:
    """APScheduler-compatible async job that checks ALL open positions for
    auto-sell every 30 seconds.

    Designed to be wired into the scheduler alongside the existing
    ``sell_signal_monitor_job`` (which runs every 5 minutes with
    probability-based thresholds).  This job uses tighter PnL-percentage
    thresholds for faster profit-taking.
    """
    from backend.db.utils import get_db_session
    from backend.models.database import Trade
    from backend.core.position_monitor import _fetch_prices_bulk

    modes = [settings.TRADING_MODE]
    if settings.TRADING_MODE != "paper":
        modes.append("paper")

    def _load_open_trades() -> list:
        with get_db_session() as db:
            return (
                db.query(Trade)
                .filter(Trade.settled.is_(False))
                .filter(Trade.trading_mode.in_(modes))
                .all()
            )

    try:
        trades = await asyncio.to_thread(_load_open_trades)
        if not trades:
            return

        # Bulk fetch prices using existing position_monitor helper
        tickers = list({t.market_ticker for t in trades if t.market_ticker})
        if not tickers:
            return

        prices = await asyncio.to_thread(_fetch_prices_bulk, tickers)
        if not prices:
            return
            
        from backend.markets.provider_registry import market_registry

        # Group trades by platform to fetch the right client
        from collections import defaultdict
        trades_by_platform = defaultdict(list)
        for t in trades:
            plat = getattr(t, "platform", "polymarket") or "polymarket"
            trades_by_platform[plat].append(t)

        manager = AutoSellManager()
        total_results = []
        
        for platform, plat_trades in trades_by_platform.items():
            provider = market_registry.get_provider(platform)
            # If provider is found, it will be used as clob_client to execute live orders
            results = await manager.scan_and_sell_all(plat_trades, prices, clob_client=provider)
            total_results.extend(results)

        if total_results:
            logger.info(
                "[auto_sell_job] Completed: {} sells from {} positions across platforms",
                len(total_results),
                len(trades),
            )

    except Exception:
        logger.exception("[auto_sell_job] Failed")


# ---------------------------------------------------------------------------
# Strategy integration helper
# ---------------------------------------------------------------------------


async def check_strategy_positions_for_auto_sell(
    strategy_name: str,
    clob_client: Optional[Any] = None,
    *,
    profit_target_pct: Optional[float] = None,
    stop_loss_pct: Optional[float] = None,
    max_hold_seconds: Optional[int] = None,
) -> List[AutoSellResult]:
    """Check all open positions belonging to *strategy_name* for auto-sell.

    Convenience function for strategies (e.g. line_movement_detector) that
    want to integrate auto-sell into their own run_cycle.
    """
    from backend.db.utils import get_db_session
    from backend.models.database import Trade
    from backend.core.position_monitor import _fetch_prices_bulk

    def _load() -> list:
        with get_db_session() as db:
            return (
                db.query(Trade)
                .filter(Trade.settled.is_(False))
                .filter(Trade.strategy == strategy_name)
                .all()
            )

    trades = await asyncio.to_thread(_load)
    if not trades:
        return []

    tickers = list({t.market_ticker for t in trades if t.market_ticker})
    prices = await asyncio.to_thread(_fetch_prices_bulk, tickers)

    manager = AutoSellManager(
        profit_target_pct=profit_target_pct,
        stop_loss_pct=stop_loss_pct,
        max_hold_seconds=max_hold_seconds,
    )
    return await manager.scan_and_sell_all(trades, prices, clob_client)


__all__ = [
    "AutoSellManager",
    "AutoSellResult",
    "auto_sell_monitor_job",
    "check_strategy_positions_for_auto_sell",
]
