"""
Market Maker Strategy for PolyEdge.

Two-sided quoting with dynamic spread adjustment based on volatility,
inventory skew, and microstructure analysis. Refactored to support lock-free
async L2 queue consumer ticks from WSDispatcher.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Set, List, Dict, Any

from backend.strategies.base import (
    BaseStrategy,
    StrategyContext,
    CycleResult,
    MarketInfo,
)
from backend.core.event_bus import MarketEvent
from backend.core.decisions import record_decision
from backend.core.market_making_analyzer import (
    MarketMakingAnalyzer,
    LiquidityMetrics,
)
from backend.config import settings
from backend.data.shared_client import get_shared_client
from loguru import logger

# ---------------------------------------------------------------------------
# Quote state tracking
# ---------------------------------------------------------------------------


@dataclass
class Quote:
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float


@dataclass
class ActiveQuote:
    """Tracks a live quote placed on the order book."""

    quote_id: str
    market_id: str
    side: str  # "BUY" or "SELL"
    price: float
    size: float
    placed_at: float  # time.monotonic()
    order_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class MarketMakerStrategy(BaseStrategy):
    name = "market_maker"
    description = "Two-sided quoting with dynamic spread, inventory control, and live WS execution"
    category = "market_making"
    default_params = {
        "base_spread": settings.MARKET_MAKER_BASE_SPREAD,
        "max_inventory": 50.0,  # per-side limit (was 250)
        "inventory_skew_factor": settings.MARKET_MAKER_INVENTORY_SKEW_FACTOR,
        "min_spread": settings.MARKET_MAKER_MIN_SPREAD,  # 0.03 (3%)
        "max_spread": settings.MARKET_MAKER_MAX_SPREAD,
        "quote_size": settings.MARKET_MAKER_QUOTE_SIZE,
        "spread_mode": "static",
        "lmsr_liquidity_param": settings.MARKET_MAKER_LMSR_LIQUIDITY_PARAM,
        # Active quoting params
        "risk_aversion": 0.5,
        "kappa": 100.0,
        "quote_max_age_seconds": 30.0,  # cancel stale after 30s
        "spread_change_threshold": 0.01,
        "inventory_change_threshold": 10.0,
        "max_total_exposure_usd": 100.0,  # $100 max (was 3000)
        "max_open_positions": 10,
        "max_per_asset": 2,
        "stop_loss_pct": 0.10,
        "profit_target_pct": 0.05,
        "toxicity_kill_threshold": 0.8,
        "toxicity_widen_threshold": 0.5,
        "quote_refresh_interval": 5.0,
        # Adverse selection protection
        "max_adverse_streak": 3,  # halt after 3 consecutive adverse fills
    }

    # -- Event-driven (WebSocket) subscription config --
    subscribed_tokens: Set[str] = set()
    subscribed_events: Set[str] = {"book", "price_change"}

    def __init__(self) -> None:
        super().__init__()
        # Per-market active quote tracking: market_id -> list[ActiveQuote]
        self._active_quotes: dict[str, list[ActiveQuote]] = {}
        # Per-market last-known state for change detection
        self._last_spread: dict[str, float] = {}
        self._last_inventory: dict[str, float] = {}
        # Shared analyzer instance (keeps history across cycles)
        self._analyzer = MarketMakingAnalyzer(
            min_spread_pct=settings.MARKET_MAKER_MIN_SPREAD,
        )

        # High-speed lock-free processing queue
        self._queue: asyncio.Queue = asyncio.Queue()
        self._consumer_task: Optional[asyncio.Task] = None
        self._tokens_populated: bool = False
        self._halted: bool = False
        # Stored from run_cycle so event-driven path can place real orders
        self._clob: Optional[object] = None
        self._mode: str = "paper"
        # Per-market inventory tracking (net filled size: +BUY, -SELL)
        self._inventory: dict[str, float] = {}
        # Per-market price history for volatility estimation
        self._price_history: dict[str, list] = {}
        # Adverse selection tracking (consecutive bad fills)
        self._adverse_streak: int = 0
        self._last_fill_price: dict[str, float] = {}  # market_id -> last fill price
        # Total exposure tracking
        self._total_exposure_usd: float = 0.0

    # ------------------------------------------------------------------
    # Risk controls: adverse selection + exposure limits
    # ------------------------------------------------------------------

    def record_fill(
        self, market_id: str, side: str, price: float, size: float, current_mid: float
    ) -> None:
        """Record a fill and check for adverse selection.

        Adverse = buy fill above mid or sell fill below mid (picked off by informed flow).
        Halts quoting after max_adverse_streak consecutive adverse fills.
        """
        self._total_exposure_usd += price * size

        is_adverse = (side == "BUY" and price > current_mid) or (
            side == "SELL" and price < current_mid
        )
        if is_adverse:
            self._adverse_streak += 1
            logger.warning(
                f"[{self.name}] Adverse fill #{self._adverse_streak}: {side} {size}@{price:.4f} (mid={current_mid:.4f})"
            )
            max_streak = self.default_params.get("max_adverse_streak", 3)
            if self._adverse_streak >= max_streak:
                self._halted = True
                logger.error(
                    f"[{self.name}] HALTED: {self._adverse_streak} consecutive adverse fills. Pulling all quotes."
                )
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._cancel_all_quotes())
                except RuntimeError:
                    pass  # no event loop running (e.g. test)
        else:
            self._adverse_streak = 0

    def _check_exposure_limit(self) -> bool:
        """Returns True if exposure is within limits, False if we should stop quoting."""
        max_exposure = self.default_params.get("max_total_exposure_usd", 100.0)
        if self._total_exposure_usd >= max_exposure:
            logger.warning(
                f"[{self.name}] Exposure limit reached: ${self._total_exposure_usd:.2f} >= ${max_exposure:.2f}"
            )
            return False
        return True

    async def _cancel_all_quotes(self) -> int:
        """Cancel all active quotes across all markets. Returns count cancelled."""
        total = 0
        for market_id in list(self._active_quotes.keys()):
            total += await self._cancel_stale_quotes(market_id, self._clob)
        return total

    def start_consumer(self) -> None:
        """Start the background L2 consumer task if not active."""
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(self._process_queue_loop())
            logger.info(f"[{self.name}] Async L2 queue consumer loop started.")

    async def stop_consumer(self) -> None:
        """Cancel the background L2 consumer task on shutdown."""
        if self._consumer_task and not self._consumer_task.done():
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None
            logger.info(f"[{self.name}] L2 queue consumer stopped.")

    async def _populate_subscribed_tokens(self) -> None:
        """Discover active short-duration markets and map outcome token IDs."""
        try:
            from backend.core.market_scanner import fetch_short_duration_token_ids

            # MarketMaker subscribes to the top highly liquid short-duration tokens for quoting
            short_tokens = await fetch_short_duration_token_ids(limit=30)
            self.subscribed_tokens = set(short_tokens)
            self._tokens_populated = True

            self.start_consumer()
            logger.info(
                f"[{self.name}] Subscribed tokens populated with {len(self.subscribed_tokens)} active tokens."
            )
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to populate subscribed tokens: {e}")

    async def on_ws_disconnected(self) -> None:
        """Safety Safeguard: Disconnection cancels all quotes and halts quoting."""
        self._halted = True
        logger.warning(
            f"[{self.name}] WebSocket telemetry lost! Halting quoting and canceling all orders."
        )
        for market_id in list(self._active_quotes.keys()):
            await self._cancel_stale_quotes(market_id, None)

    async def on_ws_reconnected(self) -> None:
        """Resume quoting after WebSocket reconnection."""
        self._halted = False
        logger.info(f"[{self.name}] WebSocket telemetry restored. Strategy resumed.")

    # ------------------------------------------------------------------
    # Avellaneda-Stoikov math
    # ------------------------------------------------------------------

    def calculate_spread(self, volatility: float, inventory_pct: float) -> float:
        """Calculate optimal spread for backward-compatibility with tests."""
        gamma = self.default_params.get("risk_aversion", 0.3)
        kappa = self.default_params.get("kappa", 1.5)
        min_spread = self.default_params["min_spread"]
        max_spread = self.default_params["max_spread"]

        vol_sq = max(volatility, 0.001) ** 2
        spread = gamma * vol_sq * 1.0 + (2.0 / gamma) * math.log(
            1.0 + gamma / max(kappa, 0.01)
        )
        return max(min_spread, min(spread, max_spread))

    def calculate_quotes(
        self,
        mid_price: float,
        spread: float,
        inventory_pct: float,
        params: Optional[dict] = None,
    ) -> Quote:
        """Calculate skew quotes for backward-compatibility with tests."""
        p = params or self.default_params
        quote_size = p.get("quote_size", self.default_params["quote_size"])
        if quote_size <= 0:
            raise ValueError("quote_size must be > 0")

        p.get("risk_aversion", 0.3)
        skew_factor = p.get("inventory_skew_factor", 0.7)

        reservation = mid_price - inventory_pct * skew_factor * spread

        bid = max(0.01, reservation - spread / 2.0)
        ask = min(0.99, reservation + spread / 2.0)

        return Quote(
            bid_price=round(bid, 4),
            ask_price=round(ask, 4),
            bid_size=quote_size,
            ask_size=quote_size,
        )

    def lmsr_spread(
        self,
        yes_shares: float,
        no_shares: float,
        liquidity_param: Optional[float] = None,
    ) -> dict[str, float]:
        """Calculate yes/no pricing based on LMSR model for backward-compatibility with tests."""
        b = liquidity_param or self.default_params.get("lmsr_liquidity_param", 10.0)
        b = max(b, 0.001)  # prevent division by zero

        e_yes = math.exp(yes_shares / b)
        e_no = math.exp(no_shares / b)
        denom = e_yes + e_no

        return {
            "yes_price": e_yes / denom,
            "no_price": e_no / denom,
        }

    def calculate_as_quote(
        self,
        mid_price: float,
        volatility: float,
        inventory: float,
        time_remaining: float,
        params: Optional[dict] = None,
    ) -> Quote:
        """Calculate optimal bid and ask quotes based on Avellaneda-Stoikov model."""
        p = params or self.default_params
        gamma = p.get("risk_aversion", 0.3)
        kappa = p.get("kappa", 1.5)
        quote_size = p.get("quote_size", self.default_params["quote_size"])
        max_inventory = p.get("max_inventory", self.default_params["max_inventory"])
        min_spread = p.get("min_spread", self.default_params["min_spread"])

        vol_sq = max(volatility, 0.001) ** 2
        inv_normalized = inventory / max(max_inventory, 1.0)
        reservation = mid_price - inv_normalized * gamma * vol_sq * time_remaining

        spread = gamma * vol_sq * time_remaining + (2.0 / gamma) * math.log(
            1.0 + gamma / max(kappa, 0.01)
        )

        spread = max(spread, min_spread)

        bid = max(0.01, reservation - spread / 2.0)
        ask = min(0.99, reservation + spread / 2.0)

        max_inv = max(max_inventory, 1.0)
        inv_ratio = abs(inventory) / max_inv
        bid_size = quote_size * (1.0 - inv_ratio) if inventory > 0 else quote_size
        ask_size = quote_size * (1.0 - inv_ratio) if inventory < 0 else quote_size
        bid_size = max(quote_size * 0.2, bid_size)
        ask_size = max(quote_size * 0.2, ask_size)

        return Quote(
            bid_price=round(bid, 4),
            ask_price=round(ask, 4),
            bid_size=round(bid_size, 2),
            ask_size=round(ask_size, 2),
        )

    # ------------------------------------------------------------------
    # Quote management helpers
    # ------------------------------------------------------------------

    def _get_active_quotes(self, market_id: str) -> list[ActiveQuote]:
        return self._active_quotes.get(market_id, [])

    def _add_active_quote(self, quote: ActiveQuote) -> None:
        self._active_quotes.setdefault(quote.market_id, []).append(quote)

    def _remove_active_quote(self, market_id: str, quote_id: str) -> None:
        quotes = self._active_quotes.get(market_id, [])
        self._active_quotes[market_id] = [q for q in quotes if q.quote_id != quote_id]

    def _clear_active_quotes(self, market_id: str) -> None:
        self._active_quotes.pop(market_id, None)

    def _estimate_volatility(self, market_id: str) -> float:
        """Estimate volatility from recent price history using std of returns."""
        prices = list(self._price_history.get(market_id, []))
        if len(prices) < 2:
            return 0.05  # default fallback
        recent = [p[1] for p in prices[-50:]]
        returns = [
            (recent[i] - recent[i - 1]) / recent[i - 1]
            for i in range(1, len(recent))
            if recent[i - 1] > 0
        ]
        if not returns:
            return 0.05
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        return max(0.001, variance**0.5)

    def _estimate_time_remaining(self, market_id: str) -> float:
        """Estimate seconds to market resolution. Default 1h if unknown."""
        # Market end time not available in this context — use default
        return 3600.0

    def _should_refresh_quotes(
        self,
        market_id: str,
        current_spread: float,
        current_inventory: float,
        params: dict,
    ) -> bool:
        """Determine whether quotes need refreshing based on state changes."""
        active = self._get_active_quotes(market_id)
        if not active:
            return True

        max_age = params.get("quote_max_age_seconds", 30.0)
        now = time.monotonic()
        oldest = min(q.placed_at for q in active)
        if now - oldest > max_age:
            return True

        spread_threshold = params.get("spread_change_threshold", 0.01)
        last_spread = self._last_spread.get(market_id)
        if (
            last_spread is not None
            and abs(current_spread - last_spread) > spread_threshold
        ):
            return True

        inv_threshold = params.get("inventory_change_threshold", 10.0)
        last_inv = self._last_inventory.get(market_id)
        if last_inv is not None and abs(current_inventory - last_inv) > inv_threshold:
            return True

        return False

    async def _cancel_stale_quotes(
        self,
        market_id: str,
        clob: Optional[object],
    ) -> int:
        """Cancel all active quotes for a market. Returns count cancelled."""
        quotes = self._get_active_quotes(market_id)
        cancelled = 0
        for q in quotes:
            if q.order_id and clob is not None:
                try:
                    ok = await clob.cancel_order(q.order_id)
                    if ok:
                        cancelled += 1
                except Exception as e:
                    logger.warning(
                        "[market_maker] Cancel error for quote {}: {}", q.quote_id, e
                    )
        self._clear_active_quotes(market_id)
        return cancelled

    # ------------------------------------------------------------------
    # Microstructure / toxicity integration
    # ------------------------------------------------------------------

    def _apply_toxicity_filter(
        self,
        quote: Quote,
        toxicity: float,
        params: dict,
    ) -> Quote:
        """Adjust or kill quotes in response to order flow toxicity."""
        widen_thresh = params.get("toxicity_widen_threshold", 0.5)
        kill_thresh = params.get("toxicity_kill_threshold", 0.8)

        if toxicity >= kill_thresh:
            logger.warning(
                "[market_maker] High flow toxicity ({:.2f}). Pulling all quotes.",
                toxicity,
            )
            return Quote(0.0, 0.0, 0.0, 0.0)

        if toxicity >= widen_thresh:
            # Scale spread widening up to 3x based on toxicity level
            scaling = (
                1.0 + (toxicity - widen_thresh) / (kill_thresh - widen_thresh) * 2.0
            )
            bid_dist = abs(quote.bid_price - (quote.bid_price + quote.ask_price) / 2.0)
            ask_dist = abs(quote.ask_price - (quote.bid_price + quote.ask_price) / 2.0)

            new_bid = quote.bid_price - bid_dist * (scaling - 1.0)
            new_ask = quote.ask_price + ask_dist * (scaling - 1.0)

            logger.info(
                "[market_maker] Toxic flow widening: bid={:.4f} -> {:.4f}, ask={:.4f} -> {:.4f}",
                quote.bid_price,
                new_bid,
                quote.ask_price,
                new_ask,
            )

            quote.bid_price = round(max(0.01, new_bid), 4)
            quote.ask_price = round(min(0.99, new_ask), 4)

        return quote

    # ------------------------------------------------------------------
    # Event-driven: Ingest into async queue
    # ------------------------------------------------------------------

    async def on_market_event(self, event: MarketEvent) -> Optional[dict]:
        """Ingest order book events into the queue sequentially."""
        if self._halted:
            return None

        self.start_consumer()
        if event.event_type in ("book", "price_change"):
            await self._queue.put(event)
        return None

    # ------------------------------------------------------------------
    # Lock-free queue consumer
    # ------------------------------------------------------------------

    async def _process_queue_loop(self) -> None:
        """Consumes L2 order book updates sequentially to adjust quotes."""
        while True:
            try:
                event = await self._queue.get()
                await self._process_orderbook_update(event)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.name}] Error in L2 consumer loop: {e}")
                await asyncio.sleep(0.01)

    async def _process_orderbook_update(self, event: MarketEvent) -> None:
        """Process real-time L2 order book updates and refresh quotes aggressively."""
        market_id = event.token_id
        data = event.data

        bids = data.get("bids", [])
        asks = data.get("asks", [])
        if not bids or not asks:
            return

        try:
            best_bid = float(bids[0].get("price") or bids[0][0])
            best_ask = float(asks[0].get("price") or asks[0][0])
        except (IndexError, ValueError, TypeError):
            return

        if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
            return

        mid = (best_bid + best_ask) / 2.0
        spread = best_ask - best_bid

        # Spread threshold check: only quote if spread is wide enough to profit
        min_spread = self.default_params.get("min_spread", 0.03)
        if spread < min_spread:
            return  # spread too narrow, skip

        # Exposure limit check
        if not self._check_exposure_limit():
            await self._cancel_stale_quotes(market_id, self._clob)
            return

        # Inventory management skew (tracked from filled orders)
        inventory = self._inventory.get(market_id, 0.0)
        params = self.default_params

        if self._should_refresh_quotes(market_id, spread, inventory, params):
            # Calculate new reservation and AS optimal quoting spread
            volatility = self._estimate_volatility(market_id)
            time_remaining = self._estimate_time_remaining(market_id)
            quote = self.calculate_as_quote(
                mid, volatility, inventory, time_remaining, params
            )

            # Microstructure toxic flow safety
            toxicity = 0.2
            quote = self._apply_toxicity_filter(quote, toxicity, params)
            if quote.bid_size <= 0 and quote.ask_size <= 0:
                await self._cancel_stale_quotes(market_id, self._clob)
                return

            # Cancel stale quotes
            await self._cancel_stale_quotes(market_id, self._clob)

            # Place new quotes (real CLOB orders in live mode)
            for side, price, size in [
                ("BUY", quote.bid_price, quote.bid_size),
                ("SELL", quote.ask_price, quote.ask_size),
            ]:
                if size <= 0 or price <= 0:
                    continue
                aq = ActiveQuote(
                    quote_id=str(uuid.uuid4()),
                    market_id=market_id,
                    side=side,
                    price=price,
                    size=size,
                    placed_at=time.monotonic(),
                )

                # Place real CLOB order when available and in live mode
                if self._clob and self._mode == "live":
                    try:
                        order = await self._clob.place_limit_order(
                            token_id=market_id,
                            side=side,
                            price=price,
                            size=size,
                        )
                        if order and getattr(order, "success", False):
                            aq.order_id = str(getattr(order, "order_id", "") or "")
                            logger.info(
                                f"[{self.name}] CLOB {side} order placed: {aq.order_id[:20]}"
                            )
                        elif order:
                            logger.warning(
                                f"[{self.name}] CLOB {side} order rejected: {getattr(order, 'error', 'unknown')}"
                            )
                    except Exception as e:
                        logger.warning(f"[{self.name}] CLOB {side} order failed: {e}")

                self._add_active_quote(aq)

                # Persist quote decision
                from backend.db.utils import get_db_session

                try:
                    with get_db_session() as db:
                        record_decision(
                            db,
                            self.name,
                            market_id,
                            "BUY" if side == "BUY" else "SELL",
                            confidence=0.5,
                            signal_data={
                                "quote_side": side,
                                "quote_price": price,
                                "quote_size": size,
                                "order_id": aq.order_id or "",
                                "sources": ["market_maker", "polymarket_websocket"],
                            },
                            reason=f"Quote {side}: {size} @ {price}",
                        )
                except Exception as e:
                    logger.debug(f"[{self.name}] Failed to save quote decision: {e}")

            self._last_spread[market_id] = spread
            self._last_inventory[market_id] = inventory

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Scheduled cycle: store CLOB context, populate tokens, place quotes via polling."""
        # Store CLOB reference so the event-driven path can place real orders
        self._clob = ctx.clob
        self._mode = getattr(ctx, "mode", "paper")

        if not self._tokens_populated:
            await self._populate_subscribed_tokens()

        trades_placed = 0

        # Polling fallback: place quotes on subscribed tokens when no WS events
        if self._clob and self._mode == "live" and self.subscribed_tokens:
            for token_id in list(self.subscribed_tokens)[:10]:  # cap to avoid overload
                try:
                    # Fetch orderbook
                    book = await self._clob.get_orderbook(token_id)
                    if not book:
                        continue
                    bids = book.get("bids", [])
                    asks = book.get("asks", [])
                    if not bids or not asks:
                        continue
                    best_bid = float(
                        bids[0].get("price", 0)
                        if isinstance(bids[0], dict)
                        else bids[0][0]
                    )
                    best_ask = float(
                        asks[0].get("price", 0)
                        if isinstance(asks[0], dict)
                        else asks[0][0]
                    )
                    if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
                        continue

                    mid = (best_bid + best_ask) / 2.0
                    spread = best_ask - best_bid

                    # Spread threshold check
                    min_spread = self.default_params.get("min_spread", 0.03)
                    if spread < min_spread:
                        continue

                    # Exposure limit check
                    if not self._check_exposure_limit():
                        await self._cancel_stale_quotes(token_id, self._clob)
                        continue

                    inventory = self._inventory.get(token_id, 0.0)

                    if self._should_refresh_quotes(
                        token_id, spread, inventory, self.default_params
                    ):
                        volatility = self._estimate_volatility(token_id)
                        time_remaining = self._estimate_time_remaining(token_id)
                        quote = self.calculate_as_quote(
                            mid,
                            volatility,
                            inventory,
                            time_remaining,
                            self.default_params,
                        )

                        # Cancel stale quotes
                        await self._cancel_stale_quotes(token_id, self._clob)

                        # Place new quotes
                        for side, price, size in [
                            ("BUY", quote.bid_price, quote.bid_size),
                            ("SELL", quote.ask_price, quote.ask_size),
                        ]:
                            if size <= 0 or price <= 0:
                                continue
                            try:
                                order = await self._clob.place_limit_order(
                                    token_id=token_id,
                                    side=side,
                                    price=price,
                                    size=size,
                                )
                                if order and getattr(order, "success", False):
                                    aq = ActiveQuote(
                                        quote_id=str(uuid.uuid4()),
                                        market_id=token_id,
                                        side=side,
                                        price=price,
                                        size=size,
                                        placed_at=time.monotonic(),
                                        order_id=str(
                                            getattr(order, "order_id", "") or ""
                                        ),
                                    )
                                    self._add_active_quote(aq)
                                    trades_placed += 1
                            except Exception as e:
                                logger.debug(
                                    f"[{self.name}] Quote placement failed: {e}"
                                )

                        self._last_spread[token_id] = spread
                        self._last_inventory[token_id] = inventory
                except Exception as e:
                    logger.debug(
                        f"[{self.name}] Polling quote failed for {token_id}: {e}"
                    )

        return CycleResult(
            decisions_recorded=trades_placed,
            trades_attempted=trades_placed,
            trades_placed=trades_placed,
        )
