# hft_trigger.py — extracted from scheduler.py
"""Scheduler sub-module: hft_trigger."""

from backend.config import settings
from loguru import logger
import time

async def _subscribe_hft_trigger(orderbook_router) -> None:
    """Subscribe OrderbookRouter updates to trigger HFT strategy re-evaluation.

    When an orderbook update arrives, this handler checks if any strategy
    is actively monitoring this market and triggers execute_decision()
    with the HFT flag set, bypassing the 60s poll cycle.
    """
    _HFT_MARKETS_BEING_SCANNED: set[str] = set()
    _SCAN_DEBOUNCE_SEC = 1.0  # don't re-trigger same market more than once per second
    _last_trigger: dict[str, float] = {}

    async def _hft_orderbook_handler(update) -> None:
        """Receive orderbook update and trigger HFT execution if eligible."""
        if not getattr(settings, "HFT_ENABLED", True):
            return

        market_id = getattr(update, "market_id", None) or (
            update.market_id if hasattr(update, "market_id") else None
        )
        if not market_id:
            return

        # Debounce: skip if we just triggered for this market
        now = time.monotonic()
        last = _last_trigger.get(market_id, 0.0)
        if now - last < _SCAN_DEBOUNCE_SEC:
            return
        _last_trigger[market_id] = now

        # Build a decision dict from the orderbook update and route through HFT path
        snapshot = orderbook_router.get_snapshot(market_id)
        if snapshot is None:
            return

        # Detect significant price movement — threshold from config
        spread = abs(
            (snapshot.best_ask_yes - snapshot.best_bid_yes)
            / max(snapshot.best_bid_yes, 0.001)
        )
        min_edge = float(getattr(settings, "HFT_SCANNER_MIN_EDGE", 0.05))
        if spread < min_edge:
            return  # not a significant enough move to trigger

        decision = {
            "condition_id": market_id,
            "market_ticker": market_id,
            "token_id": market_id,
            "entry_price": (snapshot.best_bid_yes + snapshot.best_ask_yes) / 2.0,
            "direction": "BUY" if snapshot.best_ask_yes < snapshot.best_bid_yes else "SELL",
            "confidence": 0.5,
            "hft": True,
            "orderbook": snapshot,
            "platform": "polymarket",
        }

        try:
            from backend.core.strategy_executor import execute_decision
            await execute_decision(
                decision,
                strategy_name="hft_trigger",
                mode=getattr(settings, "TRADING_MODE", "paper"),
            )
        except Exception:
            logger.opt(exception=True).warning(
                "[hft_trigger] Orderbook-triggered execution failed for market {}", market_id
            )

    # Subscribe to all markets via a wildcard handler
    # The OrderbookRouter dispatches to ALL registered handlers for each market
    from backend.infrastructure.market_stream.orderbook_router import OrderbookUpdate

    # Use event_bus to bridge orderbook updates to strategy execution
    from backend.core.event_bus import subscribe_handler

    # Subscribe to generic orderbook update events
    subscribe_handler("orderbook_update", _hft_orderbook_handler)