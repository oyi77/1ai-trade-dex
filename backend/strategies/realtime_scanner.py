"""
Real-time Price Velocity Scanner (Track 1 - Parallel Edge Discovery).

Generates signals based on rate of price change (velocity) from Polymarket CLOB WebSocket
integrated into the central WS dispatcher pipeline.
"""

import asyncio
import time
from datetime import datetime, timezone
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Set, Optional, List, Any

from backend.config import settings
from backend.strategies.base import (
    BaseStrategy,
    StrategyContext,
    CycleResult,
    MarketInfo,
)
from backend.core.event_bus import MarketEvent
from backend.core.decisions import record_decision
from loguru import logger


@dataclass
class PriceHistory:
    """Tracks price history for a single token_id."""

    token_id: str
    ticker: str
    prices: deque = field(default_factory=lambda: deque(maxlen=100))
    last_signal_time: float = 0.0
    last_signal_direction: Optional[str] = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def add_price(self, mid_price: float, timestamp: float) -> None:
        async with self._lock:
            self.prices.append((timestamp, mid_price))

    async def get_velocity(self, window_seconds: float) -> Optional[float]:
        async with self._lock:
            if len(self.prices) < 2:
                return None

            now = self.prices[-1][0]
            target_time = now - window_seconds

            oldest_valid = None
            for ts, price in self.prices:
                if ts >= target_time:
                    oldest_valid = (ts, price)
                    break

            if not oldest_valid:
                return None

            current_price = self.prices[-1][1]
            old_price = oldest_valid[1]
            time_delta = now - oldest_valid[0]

            if time_delta <= 0:
                return None

            return (current_price - old_price) / time_delta


class RealtimeScannerStrategy(BaseStrategy):
    """
    Real-time price velocity scanner for parallel edge discovery.

    Monitors Polymarket CLOB WebSocket for rapid price movements and generates
    signals when velocity exceeds configured thresholds.
    """

    name = "realtime_scanner"
    description = "Real-time price velocity scanner (Track 1 - Parallel Edge Discovery)"
    category = "edge_discovery"
    default_params = {
        "_force_disabled": False,  # Enabled by default when active in DB
        # Velocity thresholds (0.15 = 15% price change over 30s)
        "velocity_threshold_up": 0.15,  # Generate UP signal when velocity > 0.15
        "velocity_threshold_down": -0.15,  # Generate DOWN signal when velocity < -0.15
        # Time windows for velocity calculation (seconds)
        "velocity_window_fast": 5,  # Fast velocity (5s)
        "velocity_window_med": 15,  # Medium velocity (15s)
        "velocity_window_slow": 30,  # Slow velocity (30s)
        # Signal constraints
        "min_signal_interval": 60,  # Minimum seconds between signals for same token
        "min_history_points": 10,  # Minimum price points before calculating velocity
        # Market filter
        "min_liquidity": 1000,  # Minimum liquidity in USDC
        "min_volume": 5000,  # Minimum volume in USDC
        # Track configuration
        "track_name": "realtime",
        "execution_mode": "live",
        "max_position_usd": 50.0,  # Max trade size for this strategy (USD)
    }

    # -- Event-driven (WebSocket) subscription config --
    subscribed_tokens: Set[str] = set()
    subscribed_events: Set[str] = {"last_trade_price", "price_change"}

    def __init__(self):
        super().__init__()
        self._price_history: Dict[str, PriceHistory] = {}
        self._token_to_ticker: Dict[str, str] = {}
        self._tokens_populated: bool = False

    async def _populate_subscribed_tokens(self) -> None:
        """Discover active short-duration markets and map token_id -> ticker/slug."""
        try:
            from backend.core.market_scanner import fetch_all_active_markets, fetch_short_duration_token_ids
            import json
            
            markets = await fetch_all_active_markets(limit=1000)
            
            for m in markets:
                raw_token_ids = m.metadata.get("clobTokenIds") or []
                if isinstance(raw_token_ids, str):
                    try:
                        raw_token_ids = json.loads(raw_token_ids)
                    except Exception:
                        raw_token_ids = []
                token_ids = [str(token_id) for token_id in raw_token_ids if token_id]
                
                if len(token_ids) >= 1:
                    self._token_to_ticker[token_ids[0]] = f"{m.slug}_YES"
                if len(token_ids) >= 2:
                    self._token_to_ticker[token_ids[1]] = f"{m.slug}_NO"
                    
            # Subset/limit our subscribed tokens to short duration or liquid ones
            short_tokens = await fetch_short_duration_token_ids(limit=50)
            
            self.subscribed_tokens = set(short_tokens)
            self._tokens_populated = True
            logger.info(
                f"[{self.name}] Subscribed tokens populated with {len(self.subscribed_tokens)} active tokens."
            )
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to populate subscribed tokens: {e}")

    async def market_filter(self, markets: List[MarketInfo]) -> List[MarketInfo]:
        """Filter to high-liquidity markets suitable for velocity tracking."""
        min_liquidity = self.default_params["min_liquidity"]
        min_volume = self.default_params["min_volume"]

        return [
            m
            for m in markets
            if m.liquidity >= min_liquidity and m.volume >= min_volume
        ]

    async def on_market_event(self, event: MarketEvent) -> Optional[dict]:
        """Handle real-time WebSocket market events (trades or price updates)."""
        if not self._tokens_populated:
            await self._populate_subscribed_tokens()

        token_id = event.token_id
        if token_id not in self.subscribed_tokens:
            return None

        price_str = event.data.get("price") or event.data.get("last_trade_price")
        if not price_str:
            return None

        try:
            current_price = float(price_str)
        except (ValueError, TypeError):
            return None

        # Resolve or track token history
        if token_id not in self._price_history:
            ticker = self._token_to_ticker.get(token_id, token_id)
            self._price_history[token_id] = PriceHistory(token_id=token_id, ticker=ticker)

        history = self._price_history[token_id]

        # Extract timestamp
        event_ts = event.data.get("timestamp") or event.timestamp
        if isinstance(event_ts, str):
            try:
                event_ts = datetime.fromisoformat(event_ts.replace("Z", "+00:00")).timestamp()
            except Exception:
                event_ts = time.time()
        elif not isinstance(event_ts, (int, float)):
            event_ts = time.time()
        else:
            if event_ts > 10_000_000_000:
                event_ts = event_ts / 1000.0

        await history.add_price(current_price, event_ts)

        min_points = self.default_params["min_history_points"]
        if len(history.prices) < min_points:
            return None

        # Calculate price velocity across windows
        velocities = {}
        for window_name in ["fast", "med", "slow"]:
            window_key = f"velocity_window_{window_name}"
            window_seconds = self.default_params[window_key]
            velocity = await history.get_velocity(window_seconds)
            if velocity is not None:
                velocities[window_name] = velocity

        if not velocities:
            return None

        slow_velocity = velocities.get("slow", 0.0)
        threshold_up = self.default_params["velocity_threshold_up"]
        threshold_down = self.default_params["velocity_threshold_down"]

        direction = None
        confidence = 0.0

        if slow_velocity > threshold_up:
            direction = "UP"
            confidence = min(abs(slow_velocity) / threshold_up, 1.0)
        elif slow_velocity < threshold_down:
            direction = "DOWN"
            confidence = min(abs(slow_velocity) / abs(threshold_down), 1.0)

        if direction:
            now = time.monotonic()
            min_interval = self.default_params["min_signal_interval"]

            if now - history.last_signal_time >= min_interval:
                history.last_signal_time = now
                history.last_signal_direction = direction

                rt_entry_price = current_price
                if direction.lower() in ("no", "down"):
                    rt_entry_price = (
                        round(1.0 - current_price, 6)
                        if current_price < 1.0
                        else 0.01
                    )

                logger.info(
                    f"[{self.name}] Real-time velocity breach: {history.ticker} "
                    f"velocity={slow_velocity:.3f} confidence={confidence:.2f}"
                )

                # Fetch dynamic db context safely if needed or record decision directly
                from backend.db.utils import get_db_session
                try:
                    with get_db_session() as db:
                        record_decision(
                            db,
                            self.name,
                            history.ticker,
                            "BUY",
                            confidence=confidence,
                            signal_data={
                                "direction": direction.lower(),
                                "velocity": slow_velocity,
                                "velocities": velocities,
                                "current_price": current_price,
                                "token_id": token_id,
                                "track_name": self.default_params["track_name"],
                                "sources": ["realtime_scanner", "polymarket_websocket"],
                            },
                            reason=f"realtime_scanner velocity={slow_velocity:.3f} > {threshold_up if direction == 'UP' else threshold_down:.3f}",
                        )
                except Exception as e:
                    logger.debug(f"[{self.name}] Failed to save real-time decision to DB: {e}")

                return {
                    "decision": "BUY",
                    "market_ticker": history.ticker,
                    "direction": direction.lower(),
                    "confidence": confidence,
                    "edge": slow_velocity,
                    "size": self.default_params["max_position_usd"],
                    "entry_price": rt_entry_price,
                    "suggested_size": self.default_params["max_position_usd"],
                    "model_probability": confidence,
                    "market_probability": current_price,
                    "platform": settings.DEFAULT_VENUE,
                    "strategy_name": self.name,
                    "token_id": token_id,
                    "reasoning": f"realtime_scanner velocity={slow_velocity:.3f}",
                }

        return None

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """
        Execute one periodic/scheduled cycle.
        
        RealtimeScannerStrategy is fully event-driven, but we preserve
        run_cycle to act as fallback and populate tokens periodically.
        """
        if not self._tokens_populated:
            await self._populate_subscribed_tokens()

        result = CycleResult(
            decisions_recorded=0,
            trades_attempted=0,
            trades_placed=0,
        )
        return result
