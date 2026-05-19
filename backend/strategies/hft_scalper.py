"""HFT Momentum Scalper Strategy — ride short-term price moves, exit fast.

High-frequency scalping: detect directional price momentum over a rolling
lookback window, enter when move exceeds threshold, exit on profit target,
stop loss, or max hold time. Kelly criterion sizing based on rolling win rate.

Paper mode only. Uses HFT executor path.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    MarketInfo,
    StrategyContext,
)
from backend.strategies.types_hft import HFTSignal
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
    direction: str          # "BUY_YES" or "BUY_NO"
    entry_price: float
    size_usd: float
    opened_at: float        # time.monotonic()
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
        "target, stop, or time limit. Kelly sizing. Paper mode only. "
        "0W/0L ROI: 0%"
    )
    category = "hft"

    default_params: dict = {
        "entry_threshold": 0.01,       # 1% price move to trigger entry
        "profit_target": 0.008,        # 0.8% profit target
        "stop_loss": 0.008,            # 0.8% stop loss
        "max_hold_seconds": 15,        # max hold time
        "lookback_window": 30,         # seconds of price history to analyze
        "min_volume": 500,             # minimum market volume
        "max_spread": 0.05,            # don't trade if spread > 5%
        "kelly_fraction": 0.20,        # 20% of Kelly
        "max_position_usd": 50,        # max per trade
        "cooldown_seconds": 5,         # min time between trades same market
        "momentum_confirmation": 2,    # need N consecutive same-direction ticks
        "max_concurrent_positions": 5,
        "max_daily_loss_pct": 0.03,    # 3% bankroll max daily loss
    }

    def __init__(self) -> None:
        super().__init__()
        # Rolling price history: market_id -> deque[(timestamp, price)]
        self._price_history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=500)
        )
        # Open positions
        self._open_positions: dict[str, ScalpPosition] = {}
        # Closed positions (last 200 for win rate calc)
        self._closed_positions: deque[ScalpPosition] = deque(maxlen=200)
        # Cooldown tracker: market_id -> last exit timestamp
        self._cooldowns: dict[str, float] = {}
        # Daily PnL tracking (reset each calendar day)
        self._daily_pnl: float = 0.0
        self._daily_pnl_day: str = ""

    # ------------------------------------------------------------------
    # Momentum detection
    # ------------------------------------------------------------------

    def detect_momentum(
        self, price_history: deque, params: dict
    ) -> tuple[Optional[str], float]:
        """Detect directional momentum from recent price ticks.

        Returns (signal_direction, total_move) or (None, 0).
        """
        confirmation = params.get("momentum_confirmation", 2)
        lookback = params.get("lookback_window", 30)
        threshold = params.get("entry_threshold", 0.01)

        if len(price_history) < confirmation + 1:
            return None, 0.0

        # Filter to lookback window
        now = time.time()
        windowed = [
            (ts, p) for ts, p in price_history
            if (now - ts) <= lookback
        ]

        if len(windowed) < confirmation + 1:
            return None, 0.0

        # Extract recent prices for confirmation check
        recent_prices = [p for _, p in windowed[-(confirmation + 1):]]
        deltas = [
            recent_prices[i] - recent_prices[i - 1]
            for i in range(1, len(recent_prices))
        ]

        # All ticks same direction + total move exceeds threshold
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
        """Check whether to exit an open position.

        Returns (exit_reason, pnl_pct) or (None, pnl_pct).
        """
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
            # Insufficient data: use conservative fixed size
            return min(max_position, bankroll * 0.01)

        win_rate = wins / total
        avg_win = (
            sum(p.pnl_pct for p in self._closed_positions if p.pnl_pct > 0) / max(wins, 1)
        )
        avg_loss = (
            sum(abs(p.pnl_pct) for p in self._closed_positions if p.pnl_pct <= 0)
            / max(total - wins, 1)
        )

        # Kelly: f* = (p * b - q) / b where b = avg_win/avg_loss
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
        market: MarketInfo,
        current_price: float,
        bankroll: float,
        params: dict,
        now: float,
    ) -> Optional[str]:
        """Return rejection reason or None if risk gates pass."""
        # Max concurrent positions
        max_concurrent = params.get("max_concurrent_positions", 5)
        if len(self._open_positions) >= max_concurrent:
            return "max_concurrent_positions"

        # Daily loss limit
        self._maybe_reset_daily_pnl(now)
        max_daily_loss = params.get("max_daily_loss_pct", 0.03)
        if self._daily_pnl < 0 and abs(self._daily_pnl) >= bankroll * max_daily_loss:
            return "daily_loss_limit"

        # Min volume
        min_volume = params.get("min_volume", 500)
        if market.volume < min_volume:
            return "low_volume"

        # Max spread
        max_spread = params.get("max_spread", 0.05)
        meta = market.metadata or {}
        best_bid = float(meta.get("bestBid", 0))
        best_ask = float(meta.get("bestAsk", 0))
        if best_bid > 0 and best_ask > 0:
            spread = best_ask - best_bid
            if spread > max_spread:
                return "wide_spread"

        # Cooldown
        cooldown = params.get("cooldown_seconds", 5)
        last_exit = self._cooldowns.get(market.ticker, 0)
        if (now - last_exit) < cooldown:
            return "cooldown"

        # Already in position on this market
        if market.ticker in self._open_positions:
            return "already_in_position"

        return None

    def _maybe_reset_daily_pnl(self, now: float) -> None:
        """Reset daily PnL counter at midnight UTC."""
        from datetime import datetime, timezone
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
                if position.entry_price > 0 else 0.0
            )
        else:
            position.pnl_pct = (
                (position.entry_price - exit_price) / position.entry_price
                if position.entry_price > 0 else 0.0
            )

        position.pnl_usd = position.pnl_pct * position.size_usd
        self._daily_pnl += position.pnl_usd

        # Remove from open, add to closed
        self._open_positions.pop(position.ticker, None)
        self._closed_positions.append(position)
        self._cooldowns[position.ticker] = time.time()

        logger.info(
            "[hft_scalper] CLOSED {} {} @ {} | entry={} reason={} pnl={:.4f}% ${:.4f}",
            position.direction, position.ticker, exit_price,
            position.entry_price, reason, position.pnl_pct * 100, position.pnl_usd,
        )
        return position

    # ------------------------------------------------------------------
    # Market filter
    # ------------------------------------------------------------------

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Filter markets suitable for scalping: sufficient volume and liquidity."""
        return [
            m for m in markets
            if m.volume >= self.default_params["min_volume"]
            and m.liquidity >= 100
        ]

    # ------------------------------------------------------------------
    # Event-driven: update price history from WS events
    # ------------------------------------------------------------------

    async def on_market_event(self, event) -> Optional[dict]:
        """Ingest price events into rolling history for momentum detection."""
        if event.event_type == "last_trade_price":
            price = float(event.data.get("price", 0))
            if 0 < price < 1:
                self._price_history[event.token_id].append(
                    (event.timestamp, price)
                )
        return None

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Execute one scalping cycle: check exits, scan for entries."""
        result = CycleResult(
            decisions_recorded=0,
            trades_attempted=0,
            trades_placed=0,
        )

        params = {**self.default_params, **(ctx.params or {})}
        now = time.monotonic()
        now_wall = time.time()

        try:
            # ---------------------------------------------------------------
            # 1. Check exits on all open positions
            # ---------------------------------------------------------------
            tickers_to_close: dict[str, tuple[ScalpPosition, str]] = {}
            for ticker, position in list(self._open_positions.items()):
                history = self._price_history.get(ticker)
                if not history:
                    continue
                current_price = history[-1][1]
                exit_reason, pnl_pct = self.check_exit(
                    position, current_price, params
                )
                if exit_reason:
                    tickers_to_close[ticker] = (position, current_price)
                # Also check stale positions by wall clock
                elif (now - position.opened_at) > params.get("max_hold_seconds", 15) * 3:
                    tickers_to_close[ticker] = (position, current_price)

            for ticker, (position, exit_price) in tickers_to_close.items():
                reason, pnl_pct = self.check_exit(position, exit_price, params)
                reason = reason or "TIME_EXIT"
                closed = self._close_position(position, exit_price, reason)

                record_decision(
                    ctx.db,
                    self.name,
                    position.ticker,
                    "SELL",
                    confidence=0.5,
                    signal_data={
                        "exit_reason": reason,
                        "pnl_pct": closed.pnl_pct,
                        "pnl_usd": closed.pnl_usd,
                        "hold_time_s": closed.closed_at - closed.opened_at,
                        "direction": closed.direction,
                        "sources": ["hft_scalper"],
                    },
                    reason=f"Exit {reason}: pnl={closed.pnl_pct:.4f}%",
                )
                result.decisions_recorded += 1

            # ---------------------------------------------------------------
            # 2. Scan markets for entry signals
            # ---------------------------------------------------------------
            markets: list[MarketInfo] = []
            try:
                if ctx.clob is not None:
                    raw = await ctx.clob.get_markets(limit=100)
                    for m in raw:
                        markets.append(
                            MarketInfo(
                                ticker=m.get("conditionId", ""),
                                slug=m.get("slug", ""),
                                category=m.get("category", ""),
                                end_date=m.get("endDate"),
                                volume=float(m.get("volume24hr", 0)),
                                liquidity=float(m.get("liquidity", 0)),
                                metadata=m,
                            )
                        )
            except Exception as fetch_err:
                logger.warning("[hft_scalper] Market fetch failed: {}", fetch_err)

            if not markets:
                return result

            # Get bankroll for sizing
            bankroll = 100.0
            try:
                if ctx.clob is not None:
                    balance = await ctx.clob.get_usdc_balance()
                    bankroll = float(balance) if balance else 100.0
            except Exception:
                pass

            for market in markets:
                try:
                    # Update price history from market metadata if no WS data
                    meta = market.metadata or {}
                    mid = float(meta.get("midpoint", 0))
                    if mid <= 0:
                        best_bid = float(meta.get("bestBid", 0))
                        best_ask = float(meta.get("bestAsk", 0))
                        if best_bid > 0 and best_ask > 0:
                            mid = (best_bid + best_ask) / 2.0
                    if 0 < mid < 1:
                        self._price_history[market.ticker].append(
                            (now_wall, mid)
                        )

                    # Risk gates
                    rejection = self._passes_risk_gates(
                        market, mid, bankroll, params, now_wall
                    )
                    if rejection:
                        continue

                    # Momentum detection
                    direction, move_size = self.detect_momentum(
                        self._price_history[market.ticker], params
                    )
                    if direction is None:
                        continue

                    # Size the position
                    size_usd = self._kelly_size(bankroll, params)
                    if size_usd < 1.0:
                        continue

                    # Record decision
                    record_decision(
                        ctx.db,
                        self.name,
                        market.ticker,
                        "BUY",
                        confidence=min(move_size / params["entry_threshold"], 1.0),
                        signal_data={
                            "direction": direction,
                            "move_size": move_size,
                            "entry_price": mid,
                            "size_usd": size_usd,
                            "kelly_win_rate": self._win_rate(),
                            "sources": ["hft_scalper"],
                        },
                        reason=f"Momentum {direction}: move={move_size:.4f} "
                               f"threshold={params['entry_threshold']:.4f}",
                    )
                    result.decisions_recorded += 1

                    # Open position
                    import uuid
                    position = ScalpPosition(
                        position_id=str(uuid.uuid4()),
                        market_id=market.ticker,
                        ticker=market.ticker,
                        direction=direction,
                        entry_price=mid,
                        size_usd=size_usd,
                        opened_at=now,
                    )
                    self._open_positions[market.ticker] = position

                    logger.info(
                        "[hft_scalper] OPENED {} {} @ {} size=${:.2f} move={:.4f}",
                        direction, market.ticker, mid, size_usd, move_size,
                    )

                    # Execute via HFT path if CLOB available
                    if ctx.clob is not None:
                        try:
                            signal = HFTSignal(
                                market_id=market.ticker,
                                ticker=market.ticker,
                                signal_type="edge",
                                edge=mid,
                                confidence=min(move_size / params["entry_threshold"], 1.0),
                                metadata={
                                    "strategy": self.name,
                                    "direction": direction,
                                    "size_usd": size_usd,
                                    "move_size": move_size,
                                },
                            )
                            side = "BUY"
                            await ctx.clob.place_limit_order(
                                token_id=market.ticker,
                                side=side,
                                price=mid,
                                size=size_usd / mid if mid > 0 else size_usd,
                            )
                            result.trades_placed += 1
                        except Exception as exec_err:
                            logger.warning(
                                "[hft_scalper] Execution failed for {}: {}",
                                market.ticker, exec_err,
                            )
                            # Remove position on execution failure
                            self._open_positions.pop(market.ticker, None)

                    result.trades_attempted += 1

                except Exception as market_err:
                    logger.warning(
                        "[hft_scalper] Error processing {}: {}",
                        market.ticker, market_err,
                    )
                    result.errors.append(str(market_err))

        except Exception as e:
            result.errors.append(str(e))
            logger.error("[hft_scalper] Cycle error: {}", e)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _win_rate(self) -> float:
        """Rolling win rate from closed positions."""
        if not self._closed_positions:
            return 0.5
        wins = sum(1 for p in self._closed_positions if p.pnl_usd > 0)
        return wins / len(self._closed_positions)

    def get_open_positions(self) -> dict[str, ScalpPosition]:
        """Return current open positions (for monitoring)."""
        return dict(self._open_positions)

    def get_stats(self) -> dict:
        """Return strategy statistics."""
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
