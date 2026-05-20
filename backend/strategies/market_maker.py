"""
Market Maker Strategy for PolyEdge.

Two-sided quoting with dynamic spread adjustment based on volatility,
inventory skew, and microstructure analysis.  Active quote management
loop places live orders via the HFT executor path.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

from backend.strategies.base import (
    BaseStrategy,
    StrategyContext,
    CycleResult,
    MarketInfo,
)
from backend.core.decisions import record_decision
from backend.core.market_making_analyzer import (
    MarketMakingAnalyzer,
    LiquidityMetrics,
)
from backend.strategies.types_hft import HFTSignal
from backend.models.database import Trade
from backend.config import settings

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
    description = (
        "Two-sided quoting with dynamic spread, inventory control, and live execution"
    )
    category = "market_making"
    default_params = {
        "base_spread": settings.MARKET_MAKER_BASE_SPREAD,
        "max_inventory": settings.MARKET_MAKER_MAX_INVENTORY,
        "inventory_skew_factor": settings.MARKET_MAKER_INVENTORY_SKEW_FACTOR,
        "min_spread": settings.MARKET_MAKER_MIN_SPREAD,
        "max_spread": settings.MARKET_MAKER_MAX_SPREAD,
        "quote_size": settings.MARKET_MAKER_QUOTE_SIZE,
        "spread_mode": "static",
        "lmsr_liquidity_param": settings.MARKET_MAKER_LMSR_LIQUIDITY_PARAM,
        # Active quoting params
        "risk_aversion": 0.5,
        "kappa": 100.0,
        "quote_max_age_seconds": 30.0,
        "spread_change_threshold": 0.01,
        "inventory_change_threshold": 10.0,
        "max_total_exposure": 3000.0,
        "toxicity_kill_threshold": 0.8,
        "toxicity_widen_threshold": 0.5,
        "quote_refresh_interval": 5.0,
    }

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
            max_toxicity=0.7,
        )

    # ------------------------------------------------------------------
    # LMSR helpers (backward compatible)
    # ------------------------------------------------------------------

    @staticmethod
    def lmsr_spread(
        yes_inventory: float, no_inventory: float, liquidity_param: float = None
    ) -> dict:
        if liquidity_param is None:
            liquidity_param = settings.MARKET_MAKER_LMSR_LIQUIDITY_PARAM
        b = max(liquidity_param, 0.1)
        exp_yes = math.exp(yes_inventory / b)
        exp_no = math.exp(no_inventory / b)
        denom = exp_yes + exp_no
        yes_price = exp_yes / denom
        no_price = exp_no / denom
        return {"yes_price": yes_price, "no_price": no_price}

    @staticmethod
    def optimism_tax_factor(yes_price: float) -> float:
        if yes_price < 0.10:
            return 1.5
        if yes_price < 0.20:
            return 1.3
        if yes_price < 0.30:
            return 1.1
        return 1.0

    # ------------------------------------------------------------------
    # Spread / quote calculation (original + Avellaneda-Stoikov)
    # ------------------------------------------------------------------

    def calculate_spread(
        self, volatility: float, inventory_pct: float, params: dict = None
    ) -> float:
        p = params or self.default_params
        base_spread = p.get("base_spread", self.default_params["base_spread"])
        min_spread = p.get("min_spread", self.default_params["min_spread"])
        max_spread = p.get("max_spread", self.default_params["max_spread"])
        inventory_skew_factor = p.get(
            "inventory_skew_factor", self.default_params["inventory_skew_factor"]
        )

        inventory_pct = max(0.0, min(1.0, inventory_pct))
        volatility = max(0.0, min(2.0, volatility))

        volatility_adjustment = volatility * 0.5
        inventory_skew = abs(inventory_pct) * inventory_skew_factor * base_spread

        spread = base_spread + volatility_adjustment + inventory_skew
        return max(min_spread, min(max_spread, spread))

    def calculate_quotes(
        self, mid_price: float, spread: float, inventory_pct: float, params: dict = None
    ) -> Quote:
        p = params or self.default_params
        inventory_skew_factor = p.get(
            "inventory_skew_factor", self.default_params["inventory_skew_factor"]
        )
        quote_size = p.get("quote_size", self.default_params["quote_size"])
        if quote_size <= 0:
            raise ValueError(f"quote_size must be > 0, got {quote_size}")

        skew = -inventory_pct * inventory_skew_factor * spread * 0.5

        half_spread = spread / 2.0
        bid_price = mid_price - half_spread + skew
        ask_price = mid_price + half_spread + skew

        bid_price = max(0.01, min(0.99, bid_price))
        ask_price = max(0.01, min(0.99, ask_price))

        return Quote(
            bid_price=bid_price,
            ask_price=ask_price,
            bid_size=quote_size,
            ask_size=quote_size,
        )

    def compute_quotes(
        self,
        mid_price: float,
        inventory: float,
        volatility: float,
        time_remaining: float,
        params: dict = None,
    ) -> Quote:
        """Avellaneda-Stoikov optimal quoting model.

        Computes reservation price and optimal spread given current
        inventory, volatility, and time remaining in the trading horizon.

        Args:
            mid_price: Current mid-price of the market.
            inventory: Current signed inventory (positive = long).
            volatility: Estimated volatility.
            time_remaining: Remaining time in trading horizon (seconds).
            params: Optional parameter overrides.

        Returns:
            Quote with optimal bid/ask prices and sizes.
        """
        p = params or self.default_params
        gamma = p.get("risk_aversion", 0.3)
        kappa = p.get("kappa", 1.5)
        quote_size = p.get("quote_size", self.default_params["quote_size"])
        max_inventory = p.get("max_inventory", self.default_params["max_inventory"])
        min_spread = p.get("min_spread", self.default_params["min_spread"])

        # Reservation price: mid adjusted for inventory risk
        # Normalize inventory to [-1, 1] range to prevent unbounded shifts
        vol_sq = max(volatility, 0.001) ** 2
        inv_normalized = inventory / max(max_inventory, 1.0)
        reservation = mid_price - inv_normalized * gamma * vol_sq * time_remaining

        # Optimal spread from AS model
        spread = gamma * vol_sq * time_remaining + (2.0 / gamma) * math.log(
            1.0 + gamma / max(kappa, 0.01)
        )

        # Enforce minimum spread
        spread = max(spread, min_spread)

        bid = max(0.01, reservation - spread / 2.0)
        ask = min(0.99, reservation + spread / 2.0)

        # Inventory-aware sizing: reduce size on side that increases inventory
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

        # Age check
        max_age = params.get("quote_max_age_seconds", 30.0)
        now = time.monotonic()
        oldest = min(q.placed_at for q in active)
        if now - oldest > max_age:
            logger.debug(
                "[market_maker] {} quotes stale (age {:.1f}s > {:.1f}s)",
                market_id,
                now - oldest,
                max_age,
            )
            return True

        # Spread change check
        spread_threshold = params.get("spread_change_threshold", 0.01)
        last_spread = self._last_spread.get(market_id)
        if (
            last_spread is not None
            and abs(current_spread - last_spread) > spread_threshold
        ):
            logger.debug(
                "[market_maker] {} spread changed {:.4f} -> {:.4f}",
                market_id,
                last_spread,
                current_spread,
            )
            return True

        # Inventory change check
        inv_threshold = params.get("inventory_change_threshold", 10.0)
        last_inv = self._last_inventory.get(market_id)
        if last_inv is not None and abs(current_inventory - last_inv) > inv_threshold:
            logger.debug(
                "[market_maker] {} inventory changed {:.1f} -> {:.1f}",
                market_id,
                last_inv,
                current_inventory,
            )
            return True

        return False

    async def _cancel_stale_quotes(
        self,
        market_id: str,
        clob: object,
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
                        logger.info(
                            "[market_maker] Cancelled quote {} on {} ({} {} @ {})",
                            q.quote_id,
                            market_id,
                            q.side,
                            q.size,
                            q.price,
                        )
                    else:
                        logger.warning(
                            "[market_maker] Failed to cancel quote {} on {}",
                            q.quote_id,
                            market_id,
                        )
                except Exception as e:
                    logger.warning(
                        "[market_maker] Cancel error for quote {}: {}", q.quote_id, e
                    )
        self._clear_active_quotes(market_id)
        return cancelled

    async def _place_quote_orders(
        self,
        market_id: str,
        quote: Quote,
        clob: object,
        signal_metadata: dict,
    ) -> tuple[int, int]:
        """Place bid and ask limit orders via HFT executor path.

        Returns (orders_placed, orders_failed).
        """
        placed = 0
        failed = 0

        for side, price, size in [
            ("BUY", quote.bid_price, quote.bid_size),
            ("SELL", quote.ask_price, quote.ask_size),
        ]:
            if size <= 0 or price <= 0:
                continue

            signal = HFTSignal(
                market_id=market_id,
                signal_type="edge",
                edge=price,
                confidence=0.5,
                metadata={**signal_metadata, "side": side, "size": size},
            )

            try:
                result = await clob.place_limit_order(
                    token_id=market_id,
                    side=side,
                    price=price,
                    size=size,
                )

                if result.success:
                    aq = ActiveQuote(
                        quote_id=signal.signal_id,
                        market_id=market_id,
                        side=side,
                        price=price,
                        size=size,
                        placed_at=time.monotonic(),
                        order_id=result.order_id,
                    )
                    self._add_active_quote(aq)
                    placed += 1
                    logger.info(
                        "[market_maker] Placed {} quote: {} {} @ {} on {} (order_id={})",
                        side,
                        side,
                        size,
                        price,
                        market_id,
                        result.order_id,
                    )
                else:
                    failed += 1
                    logger.warning(
                        "[market_maker] Quote order failed: {} {} @ {} on {}: {}",
                        side,
                        size,
                        price,
                        market_id,
                        result.error,
                    )
            except Exception as e:
                failed += 1
                logger.error("[market_maker] Quote placement exception: {}", e)

        return placed, failed

    # ------------------------------------------------------------------
    # Microstructure / toxicity integration
    # ------------------------------------------------------------------

    def _build_orderbook_snapshot(self, meta: dict) -> tuple[list[dict], list[dict]]:
        """Extract bids/asks from market metadata for the analyzer."""
        # Try standard book format first
        bids = meta.get("bids", [])
        asks = meta.get("asks", [])

        if bids and asks:
            return bids, asks

        # Fallback: construct from bestBid/bestAsk
        best_bid = float(meta.get("bestBid", 0))
        best_ask = float(meta.get("bestAsk", 0))
        bid_size = float(meta.get("bestBidSize", 100.0))
        ask_size = float(meta.get("bestAskSize", 100.0))

        bids = [{"price": best_bid, "size": bid_size}] if best_bid > 0 else []
        asks = [{"price": best_ask, "size": ask_size}] if best_ask > 0 else []
        return bids, asks

    def _apply_toxicity_filter(
        self,
        quote: Quote,
        metrics: LiquidityMetrics,
        params: dict,
    ) -> Quote:
        """Widen spreads when toxicity is elevated.

        Kill switch: if toxicity > toxicity_kill_threshold, returns quote
        with zeroed sizes (no orders placed).
        """
        kill_threshold = params.get("toxicity_kill_threshold", 0.8)
        widen_threshold = params.get("toxicity_widen_threshold", 0.5)
        toxicity = metrics.toxicity_score

        if toxicity > kill_threshold:
            logger.warning(
                "[market_maker] KILL SWITCH: toxicity {:.3f} > {:.3f}, cancelling all quotes on {}",
                toxicity,
                kill_threshold,
                metrics.market_id,
            )
            return Quote(
                bid_price=quote.bid_price,
                ask_price=quote.ask_price,
                bid_size=0.0,
                ask_size=0.0,
            )

        if toxicity > widen_threshold:
            # Progressive widening: scale factor from 1.0 at threshold to 2.0 at kill
            scale = 1.0 + (toxicity - widen_threshold) / max(
                kill_threshold - widen_threshold, 0.01
            )
            scale = min(scale, 2.0)
            mid = (quote.bid_price + quote.ask_price) / 2.0
            half_spread = (quote.ask_price - quote.bid_price) / 2.0 * scale
            logger.info(
                "[market_maker] Toxicity {:.3f} > {:.3f}, widening spread by {:.1f}x",
                toxicity,
                widen_threshold,
                scale,
            )
            return Quote(
                bid_price=max(0.01, mid - half_spread),
                ask_price=min(0.99, mid + half_spread),
                bid_size=quote.bid_size,
                ask_size=quote.ask_size,
            )

        return quote

    # ------------------------------------------------------------------
    # Market filter (unchanged)
    # ------------------------------------------------------------------

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """
        Filter markets suitable for market making.

        High-volume markets with tight existing spreads are preferred —
        they have sufficient activity to fill quotes on both sides.
        """
        filtered = []
        for m in markets:
            if m.volume < 10_000.0:
                continue
            if m.liquidity < 1_000.0:
                continue
            meta = m.metadata or {}
            best_bid = float(meta.get("bestBid", 0))
            best_ask = float(meta.get("bestAsk", 0))
            if best_bid > 0 and best_ask > 0:
                spread = best_ask - best_bid
                if spread > 0.10:
                    continue
            filtered.append(m)
        return filtered

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """
        Scan markets, compute quotes via microstructure analysis and
        Avellaneda-Stoikov model, and manage live quote placement.

        Decisions are recorded for backward compatibility.  When a CLOB
        client is available, orders are placed on the order book.
        """
        result = CycleResult(
            decisions_recorded=0,
            trades_attempted=0,
            trades_placed=0,
        )

        params = {**self.default_params, **(ctx.params or {})}
        max_inventory = params["max_inventory"]
        max_total_exposure = params.get("max_total_exposure", 5000.0)

        try:
            # -----------------------------------------------------------------
            # 1. Fetch candidate markets
            # -----------------------------------------------------------------
            markets: list[MarketInfo] = []
            try:
                if ctx.clob is not None:
                    raw_markets = await ctx.clob.get_markets(limit=50)
                    for m in raw_markets:
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
                logger.warning("market_maker: market fetch failed: {}", fetch_err)

            if not markets:
                record_decision(
                    ctx.db,
                    self.name,
                    "all_markets",
                    "SKIP",
                    confidence=0.0,
                    signal_data={
                        "reason": "no_markets_available",
                        "sources": ["market_maker"],
                    },
                    reason="No markets returned from data source",
                )
                result.decisions_recorded = 1
                return result

            # -----------------------------------------------------------------
            # 2. Track total exposure for risk limit
            # -----------------------------------------------------------------
            total_exposure = 0.0
            from sqlalchemy import func as sa_func

            exposure_row = (
                ctx.db.query(
                    sa_func.coalesce(sa_func.sum(Trade.size * Trade.price), 0.0)
                )
                .filter(
                    Trade.settled.is_(False),
                    Trade.trading_mode == ctx.mode,
                    Trade.strategy == self.name,
                )
                .scalar()
            )
            total_exposure = float(exposure_row)

            # -----------------------------------------------------------------
            # 3. Process each market
            # -----------------------------------------------------------------
            for market in markets:
                try:
                    meta = market.metadata
                    best_bid = float(meta.get("bestBid", 0.45))
                    best_ask = float(meta.get("bestAsk", 0.55))
                    mid_price = (best_bid + best_ask) / 2.0

                    # Liquidity-proxied volatility estimate
                    liquidity = max(market.liquidity, 1.0)
                    volatility = max(0.0, 1.0 - min(liquidity / 50_000.0, 1.0)) * 0.10

                    # ---------------------------------------------------------
                    # Inventory tracking from DB
                    # ---------------------------------------------------------
                    inventory_row = (
                        ctx.db.query(sa_func.coalesce(sa_func.sum(Trade.size), 0.0))
                        .filter(
                            Trade.market_ticker == market.ticker,
                            Trade.settled.is_(False),
                            Trade.trading_mode == ctx.mode,
                            Trade.strategy == self.name,
                        )
                        .scalar()
                    )
                    current_inventory = float(inventory_row)
                    inventory_pct = (
                        current_inventory / max_inventory if max_inventory > 0 else 0.0
                    )
                    inventory_pct = max(-1.0, min(1.0, inventory_pct))

                    # ---------------------------------------------------------
                    # Risk gate: max inventory per market
                    # ---------------------------------------------------------
                    if abs(current_inventory) >= max_inventory:
                        logger.info(
                            "[market_maker] {} max inventory reached ({}/{}), skipping",
                            market.ticker,
                            current_inventory,
                            max_inventory,
                        )
                        # Cancel any outstanding quotes
                        await self._cancel_stale_quotes(market.ticker, ctx.clob)
                        continue

                    # Risk gate: max total exposure
                    if total_exposure >= max_total_exposure:
                        logger.info(
                            "[market_maker] Max total exposure reached (${:.0f}/${}), skipping {}",
                            total_exposure,
                            max_total_exposure,
                            market.ticker,
                        )
                        await self._cancel_stale_quotes(market.ticker, ctx.clob)
                        continue

                    # ---------------------------------------------------------
                    # Microstructure analysis
                    # ---------------------------------------------------------
                    bids, asks = self._build_orderbook_snapshot(meta)
                    metrics: Optional[LiquidityMetrics] = None
                    if bids and asks:
                        try:
                            metrics = self._analyzer.analyze(
                                market_id=market.ticker,
                                bids=bids,
                                asks=asks,
                                last_trade_price=mid_price,
                            )
                        except Exception as analysis_err:
                            logger.debug(
                                "[market_maker] Analyzer failed for {}: {}",
                                market.ticker,
                                analysis_err,
                            )

                    # ---------------------------------------------------------
                    # Toxicity kill switch
                    # ---------------------------------------------------------
                    if metrics and metrics.toxicity_score > params.get(
                        "toxicity_kill_threshold", 0.8
                    ):
                        logger.warning(
                            "[market_maker] KILL SWITCH on {}: toxicity={:.3f}",
                            market.ticker,
                            metrics.toxicity_score,
                        )
                        await self._cancel_stale_quotes(market.ticker, ctx.clob)
                        record_decision(
                            ctx.db,
                            self.name,
                            market.ticker,
                            "SKIP",
                            confidence=0.0,
                            signal_data={
                                "reason": "toxicity_kill",
                                "toxicity_score": metrics.toxicity_score,
                                "sources": ["market_maker"],
                            },
                            reason=f"Toxicity kill: {metrics.toxicity_score:.3f}",
                        )
                        result.decisions_recorded += 1
                        continue

                    # ---------------------------------------------------------
                    # Min spread gate
                    # ---------------------------------------------------------
                    current_spread = best_ask - best_bid
                    if current_spread < params.get("min_spread", 0.02):
                        logger.debug(
                            "[market_maker] {} spread {:.4f} < min {:.4f}, skipping",
                            market.ticker,
                            current_spread,
                            params.get("min_spread", 0.02),
                        )
                        continue

                    # ---------------------------------------------------------
                    # Check if quotes need refreshing
                    # ---------------------------------------------------------
                    if not self._should_refresh_quotes(
                        market.ticker,
                        current_spread,
                        current_inventory,
                        params,
                    ):
                        continue

                    # Cancel existing quotes before placing new ones
                    await self._cancel_stale_quotes(market.ticker, ctx.clob)

                    # ---------------------------------------------------------
                    # Compute quotes via Avellaneda-Stoikov
                    # ---------------------------------------------------------
                    spread = self.calculate_spread(volatility, inventory_pct, params)
                    quote = self.compute_quotes(
                        mid_price=mid_price,
                        inventory=current_inventory,
                        volatility=volatility,
                        time_remaining=300.0,  # 5-min horizon
                        params=params,
                    )

                    # ---------------------------------------------------------
                    # Apply toxicity filter
                    # ---------------------------------------------------------
                    if metrics:
                        quote = self._apply_toxicity_filter(quote, metrics, params)

                    # Skip if quotes were zeroed by toxicity kill
                    if quote.bid_size <= 0 or quote.ask_size <= 0:
                        logger.info(
                            "[market_maker] {} quotes suppressed by toxicity filter",
                            market.ticker,
                        )
                        continue

                    # ---------------------------------------------------------
                    # Record decision (backward compatible)
                    # ---------------------------------------------------------
                    signal_data = {
                        "bid_price": quote.bid_price,
                        "ask_price": quote.ask_price,
                        "bid_size": quote.bid_size,
                        "ask_size": quote.ask_size,
                        "spread": spread,
                        "mid_price": mid_price,
                        "volatility": volatility,
                        "inventory_pct": inventory_pct,
                        "sources": ["market_maker"],
                    }
                    if metrics:
                        signal_data["toxicity_score"] = metrics.toxicity_score
                        signal_data["resilience_score"] = metrics.resilience_score
                        signal_data["depth_imbalance"] = metrics.depth.depth_imbalance

                    record_decision(
                        ctx.db,
                        self.name,
                        market.ticker,
                        "QUOTE",
                        confidence=settings.MARKET_MAKER_DEFAULT_CONFIDENCE,
                        signal_data=signal_data,
                        reason=f"market_maker spread={spread:.3f} bid={quote.bid_price:.3f} ask={quote.ask_price:.3f}",
                    )
                    result.decisions_recorded += 1

                    # ---------------------------------------------------------
                    # Place live orders if CLOB available
                    # ---------------------------------------------------------
                    if ctx.clob is not None:
                        placed, failed = await self._place_quote_orders(
                            market_id=market.ticker,
                            quote=quote,
                            clob=ctx.clob,
                            signal_metadata={
                                "strategy": self.name,
                                "mid_price": mid_price,
                                "spread": spread,
                                "volatility": volatility,
                                "inventory_pct": inventory_pct,
                            },
                        )
                        result.trades_attempted += placed + failed
                        result.trades_placed += placed

                    # Update state tracking
                    self._last_spread[market.ticker] = current_spread
                    self._last_inventory[market.ticker] = current_inventory

                except Exception as market_err:
                    logger.warning(
                        "market_maker: error processing {}: {}",
                        market.ticker,
                        market_err,
                    )
                    result.errors.append(str(market_err))

        except Exception as e:
            result.errors.append(str(e))
            logger.error("MarketMakerStrategy cycle error: {}", e)

        return result
