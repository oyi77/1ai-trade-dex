"""HFT Momentum Scalper Strategy — ride short-term price moves, exit fast.

High-frequency scalping: detect directional price momentum over a rolling
lookback window, enter when move exceeds threshold, exit on profit target,
stop loss, or max hold time. Kelly criterion sizing based on rolling win rate.
Refactored to support lock-free async queue consumer ticks from WSDispatcher.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Set, List, Dict, Any

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    MarketInfo,
    StrategyContext,
)
from backend.core.event_bus import MarketEvent
from backend.core.decisions import record_decision
from loguru import logger


# ---------------------------------------------------------------------------
# Position tracking
# ---------------------------------------------------------------------------


@dataclass
class ScalpPosition:
    """Tracks an open scalping position."""

    position_id: str
    market_id: str
    ticker: str
    direction: str  # "BUY_YES" or "BUY_NO"
    entry_price: float
    size_usd: float
    opened_at: float  # time.monotonic()
    exit_price: Optional[float] = None
    closed_at: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl_pct: float = 0.0
    pnl_usd: float = 0.0


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class HFTScalperStrategy(BaseStrategy):
    """Momentum scalping — ride short-term price moves, exit fast."""

    name = "hft_scalper"
    description = (
        "HFT momentum scalper: detects directional price moves within a "
        "rolling lookback window and enters for quick profit. Exits on "
        "target, stop, or time limit. Kelly sizing. Safe halting."
    )
    category = "hft"

    default_params: dict = {
        "entry_threshold": 0.01,  # 1% price move to trigger entry
        "profit_target": 0.008,  # 0.8% profit target
        "stop_loss": 0.008,  # 0.8% stop loss
        "max_hold_seconds": 15,  # max hold time
        "lookback_window": 30,  # seconds of price history to analyze
        "min_volume": 500,  # minimum market volume
        "max_spread": 0.05,  # don't trade if spread > 5%
        "kelly_fraction": 0.20,  # 20% of Kelly
        "max_position_usd": 50,  # max per trade
        "cooldown_seconds": 5,  # min time between trades same market
        "momentum_confirmation": 2,  # need N consecutive same-direction ticks
        "max_concurrent_positions": 5,
        "max_daily_loss_pct": 0.03,  # 3% bankroll max daily loss
    }

    # -- Event-driven (WebSocket) subscription config --
    subscribed_tokens: Set[str] = set()
    subscribed_events: Set[str] = {"last_trade_price"}

    def __init__(self) -> None:
        super().__init__()
        # Rolling price history: market_id -> deque[(timestamp, price)]
        self._price_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
        # Open positions
        self._open_positions: dict[str, ScalpPosition] = {}
        # Closed positions (last 200 for win rate calc)
        self._closed_positions: deque[ScalpPosition] = deque(maxlen=200)
        # Cooldown tracker: market_id -> last exit timestamp
        self._cooldowns: dict[str, float] = {}
        # Daily PnL tracking (reset each calendar day)
        self._daily_pnl: float = 0.0
        self._daily_pnl_day: str = ""

        # High-speed lock-free processing queue
        self._queue: asyncio.Queue = asyncio.Queue()
        self._consumer_task: Optional[asyncio.Task] = None
        self._tokens_populated: bool = False
        self._halted: bool = False

    def start_consumer(self) -> None:
        """Start the background consumer task if not active."""
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(self._process_queue_loop())
            logger.info(f"[{self.name}] Async queue consumer loop started.")

    async def _populate_subscribed_tokens(self) -> None:
        """Discover active short-duration markets and map outcome token IDs."""
        try:
            from backend.core.market_scanner import fetch_short_duration_token_ids
            
            # Subscribe to the top highly liquid short-duration tokens
            short_tokens = await fetch_short_duration_token_ids(limit=50)
            self.subscribed_tokens = set(short_tokens)
            self._tokens_populated = True
            
            self.start_consumer()
            logger.info(
                f"[{self.name}] Subscribed tokens populated with {len(self.subscribed_tokens)} active tokens."
            )
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to populate subscribed tokens: {e}")

    async def on_ws_disconnected(self) -> None:
        """Safety Safeguard: Disconnection halts execution and flushes exposure."""
        self._halted = True
        logger.warning(f"[{self.name}] WebSocket telemetry lost! Activating safety halt.")
        
        # Safe positions cancel
        to_exit = list(self._open_positions.values())
        for pos in to_exit:
            logger.warning(f"[{self.name}] Telemetry lost: Emergency closing position on {pos.ticker}")
            # Close position locally at entry price to neutralize exposure in simulation
            self._close_position(pos, pos.entry_price, "EMERGENCY_HALT")

    async def on_ws_reconnected(self) -> None:
        """Resume trading after WebSocket reconnection."""
        self._halted = False
        logger.info(f"[{self.name}] WebSocket telemetry restored. Strategy resumed.")

    # ------------------------------------------------------------------
    # Momentum detection
    # ------------------------------------------------------------------

    def detect_momentum(
        self, price_history: deque, params: dict
    ) -> tuple[Optional[str], float]:
        """Detect directional momentum from recent price ticks."""
        confirmation = params.get("momentum_confirmation", 2)
        lookback = params.get("lookback_window", 30)
        threshold = params.get("entry_threshold", 0.01)

        if len(price_history) < confirmation + 1:
            return None, 0.0

        # Filter to lookback window
        now = time.time()
        windowed = [(ts, p) for ts, p in price_history if (now - ts) <= lookback]

        if len(windowed) < confirmation + 1:
            return None, 0.0

        # Extract recent prices for confirmation check
        recent_prices = [p for _, p in windowed[-(confirmation + 1) :]]
        deltas = [
            recent_prices[i] - recent_prices[i - 1]
            for i in range(1, len(recent_prices))
        ]

        if all(d > 0 for d in deltas):
            total_move = recent_prices[-1] - recent_prices[0]
            if total_move >= threshold:
                return "BUY_YES", total_move
        elif all(d < 0 for d in deltas):
            total_move = recent_prices[0] - recent_prices[-1]
            if total_move >= threshold:
                return "BUY_NO", total_move

        return None, 0.0

    # ------------------------------------------------------------------
    # Exit logic
    # ------------------------------------------------------------------

    def check_exit(
        self, position: ScalpPosition, current_price: float, params: dict
    ) -> tuple[Optional[str], float]:
        """Check whether to exit an open position."""
        entry = position.entry_price
        elapsed = time.monotonic() - position.opened_at

        if position.direction == "BUY_YES":
            pnl_pct = (current_price - entry) / entry if entry > 0 else 0.0
        else:
            pnl_pct = (entry - current_price) / entry if entry > 0 else 0.0

        profit_target = params.get("profit_target", 0.008)
        stop_loss = params.get("stop_loss", 0.008)
        max_hold = params.get("max_hold_seconds", 15)

        if pnl_pct >= profit_target:
            return "TAKE_PROFIT", pnl_pct
        elif pnl_pct <= -stop_loss:
            return "STOP_LOSS", pnl_pct
        elif elapsed >= max_hold:
            return "TIME_EXIT", pnl_pct

        return None, pnl_pct

    # ------------------------------------------------------------------
    # Kelly criterion sizing
    # ------------------------------------------------------------------

    def _kelly_size(self, bankroll: float, params: dict) -> float:
        """Compute fractional Kelly position size from rolling win rate."""
        kelly_fraction = params.get("kelly_fraction", 0.20)
        max_position = params.get("max_position_usd", 50.0)

        wins = sum(1 for p in self._closed_positions if p.pnl_usd > 0)
        total = len(self._closed_positions)

        if total < 5:
            return min(max_position, bankroll * 0.01)

        win_rate = wins / total
        avg_win = sum(p.pnl_pct for p in self._closed_positions if p.pnl_pct > 0) / max(
            wins, 1
        )
        avg_loss = sum(
            abs(p.pnl_pct) for p in self._closed_positions if p.pnl_pct <= 0
        ) / max(total - wins, 1)

        b = avg_win / max(avg_loss, 0.001)
        q = 1.0 - win_rate
        kelly_f = (win_rate * b - q) / max(b, 0.01)
        kelly_f = max(0.0, min(kelly_f, 0.5))

        size = bankroll * kelly_f * kelly_fraction
        return min(size, max_position, bankroll * 0.05)

    # ------------------------------------------------------------------
    # Risk gates
    # ------------------------------------------------------------------

    def _passes_risk_gates(
        self,
        ticker: str,
        current_price: float,
        bankroll: float,
        params: dict,
        now: float,
    ) -> Optional[str]:
        """Return rejection reason or None if risk gates pass."""
        if self._halted:
            return "safety_halted"

        max_concurrent = params.get("max_concurrent_positions", 5)
        if len(self._open_positions) >= max_concurrent:
            return "max_concurrent_positions"

        self._maybe_reset_daily_pnl(now)
        max_daily_loss = params.get("max_daily_loss_pct", 0.03)
        if self._daily_pnl < 0 and abs(self._daily_pnl) >= bankroll * max_daily_loss:
            return "daily_loss_limit"

        cooldown = params.get("cooldown_seconds", 5)
        last_exit = self._cooldowns.get(ticker, 0)
        if (now - last_exit) < cooldown:
            return "cooldown"

        if ticker in self._open_positions:
            return "already_in_position"

        return None

    def _maybe_reset_daily_pnl(self, now: float) -> None:
        """Reset daily PnL counter at midnight UTC."""
        today = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")
        if today != self._daily_pnl_day:
            self._daily_pnl = 0.0
            self._daily_pnl_day = today

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def _close_position(
        self, position: ScalpPosition, exit_price: float, reason: str
    ) -> ScalpPosition:
        """Close a position and record outcome."""
        position.exit_price = exit_price
        position.closed_at = time.monotonic()
        position.exit_reason = reason

        if position.direction == "BUY_YES":
            position.pnl_pct = (
                (exit_price - position.entry_price) / position.entry_price
                if position.entry_price > 0
                else 0.0
            )
        else:
            position.pnl_pct = (
                (position.entry_price - exit_price) / position.entry_price
                if position.entry_price > 0
                else 0.0
            )

        position.pnl_usd = position.pnl_pct * position.size_usd
        self._daily_pnl += position.pnl_usd

        self._open_positions.pop(position.ticker, None)
        self._closed_positions.append(position)
        self._cooldowns[position.ticker] = time.time()

        logger.info(
            "[hft_scalper] CLOSED {} {} @ {} | entry={} reason={} pnl={:.4f}% ${:.4f}",
            position.direction,
            position.ticker,
            exit_price,
            position.entry_price,
            reason,
            position.pnl_pct * 100,
            position.pnl_usd,
        )
        return position

    # ------------------------------------------------------------------
    # Market filter
    # ------------------------------------------------------------------

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Filter markets suitable for scalping: sufficient volume."""
        return [
            m
            for m in markets
            if m.volume >= self.default_params["min_volume"]
        ]

    # ------------------------------------------------------------------
    # Event-driven: Ingest into async queue
    # ------------------------------------------------------------------

    async def on_market_event(self, event: MarketEvent) -> Optional[dict]:
        """Ingest price events into rolling history sequentially."""
        if self._halted:
            return None

        self.start_consumer()
        if event.event_type in ("last_trade_price", "price_change"):
            await self._queue.put(event)
        return None

    # ------------------------------------------------------------------
    # Lock-free queue consumer
    # ------------------------------------------------------------------

    async def _process_queue_loop(self) -> None:
        """Consumes WebSocket ticks sequentially to avoid race conditions."""
        while True:
            try:
                event = await self._queue.get()
                await self._process_tick(event)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.name}] Error in queue consumer loop: {e}")
                await asyncio.sleep(0.01)

    async def _process_tick(self, event: MarketEvent) -> None:
        """Process a single real-time WS price or trade tick."""
        token_id = event.token_id
        price_str = event.data.get("price") or event.data.get("last_trade_price")
        if not price_str:
            return
        try:
            price = float(price_str)
        except (ValueError, TypeError):
            return

        if not (0 < price < 1):
            return

        # Handle timestamp parsing
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

        # 1. Record price
        self._price_history[token_id].append((event_ts, price))

        # 2. Check exits for existing position on this market
        position = self._open_positions.get(token_id)
        if position:
            params = self.default_params
            exit_reason, pnl_pct = self.check_exit(position, price, params)
            
            # Check maximum hold safeguard
            now = time.monotonic()
            if not exit_reason and (now - position.opened_at) > params.get("max_hold_seconds", 15):
                exit_reason = "TIME_EXIT"

            if exit_reason:
                closed = self._close_position(position, price, exit_reason)
                
                # Persist exit decision immediately
                from backend.db.utils import get_db_session
                try:
                    with get_db_session() as db:
                        record_decision(
                            db,
                            self.name,
                            position.ticker,
                            "SELL",
                            confidence=0.5,
                            signal_data={
                                "exit_reason": exit_reason,
                                "pnl_pct": closed.pnl_pct,
                                "pnl_usd": closed.pnl_usd,
                                "sources": ["hft_scalper", "polymarket_websocket"],
                            },
                            reason=f"Exit {exit_reason}: pnl={closed.pnl_pct:.4f}%",
                        )
                except Exception as e:
                    logger.debug(f"[{self.name}] Failed to save exit decision: {e}")
                return

        # 3. Check entry momentum for new position
        else:
            params = self.default_params
            direction, move_size = self.detect_momentum(self._price_history[token_id], params)
            if not direction:
                return

            bankroll = 100.0
            rejection = self._passes_risk_gates(token_id, price, bankroll, params, time.time())
            if rejection:
                return

            size_usd = self._kelly_size(bankroll, params)
            if size_usd < 1.0:
                return

            # Record entry decision
            from backend.db.utils import get_db_session
            try:
                with get_db_session() as db:
                    record_decision(
                        db,
                        self.name,
                        token_id,
                        "BUY",
                        confidence=min(move_size / params["entry_threshold"], 1.0),
                        signal_data={
                            "direction": direction,
                            "move_size": move_size,
                            "entry_price": price,
                            "size_usd": size_usd,
                            "sources": ["hft_scalper", "polymarket_websocket"],
                        },
                        reason=f"Momentum {direction}: move={move_size:.4f}",
                    )
            except Exception as e:
                logger.debug(f"[{self.name}] Failed to save entry decision: {e}")

            # Open position locally (Simulation fills instantly on tick)
            import uuid
            position = ScalpPosition(
                position_id=str(uuid.uuid4()),
                market_id=token_id,
                ticker=token_id,
                direction=direction,
                entry_price=price,
                size_usd=size_usd,
                opened_at=time.monotonic(),
            )
            self._open_positions[token_id] = position
            logger.info(
                f"[hft_scalper] OPENED {direction} {token_id} @ {price} size=${size_usd:.2f}"
            )

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Scheduled fallback: events process sequentially, cycles only log metrics."""
        if not self._tokens_populated:
            await self._populate_subscribed_tokens()

        result = CycleResult(
            decisions_recorded=0,
            trades_attempted=0,
            trades_placed=0,
        )
        return result

    def _win_rate(self) -> float:
        """Rolling win rate from closed positions."""
        if not self._closed_positions:
            return 0.5
        wins = sum(1 for p in self._closed_positions if p.pnl_usd > 0)
        return wins / len(self._closed_positions)

    def get_open_positions(self) -> dict[str, ScalpPosition]:
        return dict(self._open_positions)

    def get_stats(self) -> dict:
        closed = list(self._closed_positions)
        wins = [p for p in closed if p.pnl_usd > 0]
        losses = [p for p in closed if p.pnl_usd <= 0]
        return {
            "total_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": self._win_rate(),
            "total_pnl_usd": sum(p.pnl_usd for p in closed),
            "avg_pnl_pct": (
                sum(p.pnl_pct for p in closed) / len(closed) if closed else 0
            ),
            "open_positions": len(self._open_positions),
            "daily_pnl_usd": self._daily_pnl,
        }
