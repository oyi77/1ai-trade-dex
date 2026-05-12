"""
Real-time Price Velocity Scanner (Track 1 - Parallel Edge Discovery).

Generates signals based on rate of price change (velocity) from Polymarket CLOB WebSocket.
High price velocity can indicate momentum shifts before they're reflected in slower indicators.

Strategy:
- Tracks mid-price changes over sliding windows (5s, 15s, 30s)
- Calculates velocity: (current_price - price_n_seconds_ago) / n_seconds
- Generates UP signals when velocity > threshold (rapid price increase)
- Generates DOWN signals when velocity < -threshold (rapid price decrease)
- Records all signals with track_name='realtime' for paper trading validation

Edge Hypothesis:
Rapid price movements often precede volume surges and trend continuations.
By catching velocity early, we can enter before slower momentum indicators trigger.

Track Configuration:
- Default bankroll: $500 (isolated from other tracks)
- Loss limit: $100
- Signal threshold: velocity > 0.15 (15% price change over 30s)
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Optional

from backend.strategies.base import (
    BaseStrategy,
    StrategyContext,
    CycleResult,
    MarketInfo,
)
from backend.core.decisions import record_decision

from loguru import logger
@dataclass
class PriceHistory:
    """Tracks price history for a single token_id."""

    token_id: str
    ticker: str
    prices: deque = field(
        default_factory=lambda: deque(maxlen=100)
    )
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

    def __init__(self):
        super().__init__()
        self._price_history: Dict[str, PriceHistory] = {}
        self._ws_client = None
        self._running = False

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Filter to high-liquidity markets suitable for velocity tracking."""
        min_liquidity = self.default_params["min_liquidity"]
        min_volume = self.default_params["min_volume"]

        return [
            m
            for m in markets
            if m.liquidity >= min_liquidity and m.volume >= min_volume
        ]

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """
        Execute one trading cycle.

        1. Check for price velocity signals from tracked tokens
        2. Record decisions for high-velocity movements
        3. Maintain price history and WebSocket subscriptions
        """
        result = CycleResult(
            decisions_recorded=0,
            trades_attempted=0,
            trades_placed=0,
        )

        try:
            # Get current markets to track
            from backend.data.gamma import fetch_markets

            # Fetch active markets
            markets = await fetch_markets(limit=100)
            await self.market_filter(
                [
                    MarketInfo(
                        ticker=m.get("ticker", m.get("question", "")[:50]),
                        slug=m.get("slug", ""),
                        category=m.get("category", ""),
                        end_date=m.get("end_date"),
                        volume=float(m.get("volume", 0) or 0),
                        liquidity=float(m.get("liquidity", 0) or 0),
                        metadata=m,
                    )
                    for m in markets
                ]
            )

            # Check for velocity signals in tracked tokens
            for token_id, history in list(self._price_history.items()):
                if len(history.prices) < ctx.params.get(
                    "min_history_points", self.default_params["min_history_points"]
                ):
                    continue

                # Calculate velocity across multiple time windows
                velocities = {}
                for window_name in ["fast", "med", "slow"]:
                    window_key = f"velocity_window_{window_name}"
                    window_seconds = ctx.params.get(
                        window_key, self.default_params[window_key]
                    )
                    velocity = await history.get_velocity(window_seconds)
                    if velocity is not None:
                        velocities[window_name] = velocity

                if not velocities:
                    continue

                # Use slow velocity (30s) as primary signal
                slow_velocity = velocities.get("slow", 0)
                threshold_up = ctx.params.get(
                    "velocity_threshold_up",
                    self.default_params["velocity_threshold_up"],
                )
                threshold_down = ctx.params.get(
                    "velocity_threshold_down",
                    self.default_params["velocity_threshold_down"],
                )

                direction = None
                confidence = 0.0

                if slow_velocity > threshold_up:
                    direction = "UP"
                    confidence = min(abs(slow_velocity) / threshold_up, 1.0)
                elif slow_velocity < threshold_down:
                    direction = "DOWN"
                    confidence = min(abs(slow_velocity) / abs(threshold_down), 1.0)

                if direction:
                    # Check minimum signal interval
                    now = time.time()
                    min_interval = ctx.params.get(
                        "min_signal_interval",
                        self.default_params["min_signal_interval"],
                    )

                    if now - history.last_signal_time >= min_interval:
                        # Record decision
                        record_decision(
                            ctx.db,
                            self.name,
                            history.ticker,
                            "BUY",
                            confidence=confidence,
                            signal_data={
                                "direction": direction.lower(),
                                "velocity": slow_velocity,
                                "velocities": velocities,
                                "current_price": history.prices[-1][1],
                                "token_id": token_id,
                                "track_name": ctx.params.get("track_name", "realtime"),
                                "sources": ["realtime_scanner", "polymarket_websocket"],
                            },
                            reason=f"realtime_scanner velocity={slow_velocity:.3f} > {threshold_up if direction == 'UP' else threshold_down:.3f}",
                        )
                        result.decisions_recorded += 1
                        result.trades_attempted += 1

                        current_price = history.prices[-1][1]
                        rt_entry_price = current_price
                        if direction.lower() in ("no", "down"):
                            rt_entry_price = (
                                round(1.0 - current_price, 6)
                                if current_price < 1.0
                                else 0.01
                            )
                        result.decisions.append(
                            {
                                "decision": "BUY",
                                "market_ticker": history.ticker,
                                "direction": direction.lower(),
                                "confidence": confidence,
                                "edge": slow_velocity,
                                "size": ctx.params.get(
                                    "max_position_usd", self.default_params["max_position_usd"]
                                ),
                                "entry_price": rt_entry_price,
                                "suggested_size": ctx.params.get(
                                    "max_position_usd", self.default_params["max_position_usd"]
                                ),
                                "model_probability": confidence,
                                "market_probability": current_price,
                                "platform": "polymarket",
                                "strategy_name": self.name,
                                "token_id": token_id,
                                "reasoning": f"realtime_scanner velocity={slow_velocity:.3f}",
                            }
                        )

                        history.last_signal_time = now
                        history.last_signal_direction = direction

                        logger.info(
                            f"[{self.name}] {direction} signal: {history.ticker} "
                            f"velocity={slow_velocity:.3f} confidence={confidence:.2f}"
                        )

        except Exception as e:
            result.errors.append(str(e))
            logger.error(f"[{self.name}] Error in run_cycle: {e}")

        return result

    async def start_websocket_tracking(self, ctx: StrategyContext) -> None:
        """
        Start WebSocket client for real-time price updates.

        This should be called once when the strategy starts.
        Prices will be tracked in self._price_history and used for velocity calculations.
        """
        if self._running:
            return

        from backend.data.ws_client import CLOBWebSocket, PriceUpdate

        async def on_price(update: PriceUpdate) -> None:
            """Handle price updates from WebSocket."""
            history = self._price_history.get(update.token_id)
            if history:
                await history.add_price(update.mid_price, update.timestamp)

        self._ws_client = CLOBWebSocket(on_price=on_price)
        self._running = True

        from backend.api.main import app
        if hasattr(app.state, 'task_manager'):
            self._ws_task = await app.state.task_manager.create_task(
                self._ws_client.run(), name="realtime_scanner_ws"
            )
        else:
            self._ws_task = asyncio.create_task(self._ws_client.run())

        logger.info(f"[{self.name}] WebSocket tracking started")

    async def stop_websocket_tracking(self) -> None:
        """Stop WebSocket client."""
        if self._ws_client:
            await self._ws_client.stop()
        if getattr(self, "_ws_task", None) and not self._ws_task.done():
            self._ws_task.cancel()
        self._running = False
        logger.info(f"[{self.name}] WebSocket tracking stopped")

    def track_token(self, token_id: str, ticker: str) -> None:
        """
        Add a token to the tracking list.

        Should be called during market_filter or strategy initialization.
        """
        if token_id not in self._price_history:
            self._price_history[token_id] = PriceHistory(
                token_id=token_id, ticker=ticker
            )
            if self._ws_client:
                self._ws_client.subscribe(token_id)
                logger.debug(f"[{self.name}] Now tracking: {ticker} ({token_id})")

    def untrack_token(self, token_id: str) -> None:
        """Remove a token from tracking."""
        self._price_history.pop(token_id, None)
        if self._ws_client:
            self._ws_client.unsubscribe(token_id)
            logger.debug(f"[{self.name}] Stopped tracking: {token_id}")
