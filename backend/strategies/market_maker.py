"""
Market Maker Strategy for PolyEdge.

Two-sided quoting with dynamic spread adjustment based on volatility
and inventory skew to manage position risk.
"""

import logging
from dataclasses import dataclass

from backend.strategies.base import (
    BaseStrategy,
    StrategyContext,
    CycleResult,
    MarketInfo,
)
from backend.core.decisions import record_decision
from backend.models.database import Trade

logger = logging.getLogger("trading_bot.market_maker")


@dataclass
class Quote:
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float


class MarketMakerStrategy(BaseStrategy):
    name = "market_maker"
    description = "Two-sided quoting with dynamic spread and inventory control"
    category = "market_making"
    default_params = {
        "base_spread": 0.04,  # 4% base spread
        "max_inventory": 500.0,  # max USD per market
        "inventory_skew_factor": 0.5,
        "min_spread": 0.02,
        "max_spread": 0.15,
        "quote_size": 25.0,  # USD per side
        "spread_mode": "static",
        "lmsr_liquidity_param": 10.0,
    }

    @staticmethod
    def lmsr_spread(yes_inventory: float, no_inventory: float, liquidity_param: float = 10.0) -> dict:
        import math
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
        quote_size = p.get("quote_size", self.default_params["quote_size"])

        if quote_size <= 0:
            logger.warning("market_maker: quote_size=%.2f invalid, using default", quote_size)
            quote_size = self.default_params["quote_size"]

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

        # Clamp prices to valid probability range [0.01, 0.99]
        bid_price = max(0.01, min(0.99, bid_price))
        ask_price = max(0.01, min(0.99, ask_price))

        return Quote(
            bid_price=bid_price,
            ask_price=ask_price,
            bid_size=quote_size,
            ask_size=quote_size,
        )

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

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """
        Scan markets and calculate two-sided quotes for each.

        Decisions are recorded but no orders are placed — that is the
        executor's responsibility.
        """
        result = CycleResult(
            decisions_recorded=0,
            trades_attempted=0,
            trades_placed=0,
        )

        params = {**self.default_params, **ctx.params}
        max_inventory = params["max_inventory"]

        try:
            # Fetch candidate markets via Gamma API (best-effort)
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
                logger.warning(f"market_maker: market fetch failed: {fetch_err}")

            if not markets:
                # No live data — record a skip and exit gracefully
                record_decision(
                    ctx.db,
                    self.name,
                    "all_markets",
                    "SKIP",
                    confidence=0.0,
                    signal_data={"reason": "no_markets_available", "sources": ["market_maker"]},
                    reason="No markets returned from data source",
                )
                result.decisions_recorded = 1
                return result

            for market in markets:
                try:
                    # Estimate mid-price from market metadata if available
                    meta = market.metadata
                    best_bid = float(meta.get("bestBid", 0.45))
                    best_ask = float(meta.get("bestAsk", 0.55))
                    mid_price = (best_bid + best_ask) / 2.0

                    # Estimate volatility from liquidity proxy (thin book = higher vol)
                    liquidity = max(market.liquidity, 1.0)
                    volatility = max(0.0, 1.0 - min(liquidity / 50_000.0, 1.0)) * 0.10

                    # Inventory tracking — query open positions from database
                    from sqlalchemy import func

                    inventory_row = (
                        ctx.db.query(func.coalesce(func.sum(Trade.size), 0.0))
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

                    spread = self.calculate_spread(volatility, inventory_pct, params)
                    quote = self.calculate_quotes(
                        mid_price, spread, inventory_pct, params
                    )

                    decision = "QUOTE"
                    record_decision(
                        ctx.db,
                        self.name,
                        market.ticker,
                        decision,
                        confidence=0.5,
                        signal_data={
                            "bid_price": quote.bid_price,
                            "ask_price": quote.ask_price,
                            "bid_size": quote.bid_size,
                            "ask_size": quote.ask_size,
                            "spread": spread,
                            "mid_price": mid_price,
                            "volatility": volatility,
                            "inventory_pct": inventory_pct,
                            "sources": ["market_maker"],
                        },
                        reason=f"market_maker spread={spread:.3f} bid={quote.bid_price:.3f} ask={quote.ask_price:.3f}",
                    )
                    result.decisions_recorded += 1

                except Exception as market_err:
                    logger.warning(
                        f"market_maker: error processing {market.ticker}: {market_err}"
                    )
                    result.errors.append(str(market_err))

        except Exception as e:
            result.errors.append(str(e))
            logger.error(f"MarketMakerStrategy cycle error: {e}")

        return result
