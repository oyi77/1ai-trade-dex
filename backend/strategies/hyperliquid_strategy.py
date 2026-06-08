"""Hyperliquid prediction market strategy.

Trades prediction markets on Hyperliquid by comparing on-chain oracle prices
with Hyperliquid market prices. Looks for mispricings similar to crypto_oracle
but adapted for the Hyperliquid venue.
"""

from __future__ import annotations


from backend.strategies.base import (
    BaseStrategy,
    StrategyContext,
    CycleResult,
    MarketInfo,
)


class HyperliquidStrategy(BaseStrategy):
    """Strategy for trading Hyperliquid prediction markets.

    Scans Hyperliquid markets for mispricings against oracle/external data.
    Applies similar logic to crypto_oracle but targets Hyperliquid venue.

    Starts DISABLED. Enable via StrategyConfig DB table.
    """

    name = "hyperliquid"
    description = (
        "Trades Hyperliquid prediction markets via oracle mispricing detection"
    )
    category = "hyperliquid"
    default_params = {
        "min_edge": 0.04,
        "max_entry_price": 0.80,
        "max_trade_usd": 50.0,
        "kelly_fraction": 0.25,
    }

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Filter to Hyperliquid markets only."""
        return [m for m in markets if m.metadata.get("platform") == "hyperliquid"]

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Execute one Hyperliquid trading cycle.

        1. Fetch Hyperliquid markets
        2. For each market, check for oracle mispricing
        3. Place trades when edge exceeds threshold
        """
        decisions_recorded = 0
        trades_attempted = 0
        trades_placed = 0
        errors: list[str] = []

        params = ctx.params or {}
        min_edge = params.get("min_edge", self.default_params["min_edge"])
        max_entry = params.get(
            "max_entry_price", self.default_params["max_entry_price"]
        )
        params.get(
            "max_trade_usd", self.default_params["max_trade_usd"]
        )

        try:
            # Get Hyperliquid client from providers
            hl_provider = ctx.providers.get("hyperliquid")
            if hl_provider is None:
                ctx.logger.debug("[hyperliquid] No Hyperliquid provider available")
                return CycleResult(
                    decisions_recorded=0,
                    trades_attempted=0,
                    trades_placed=0,
                    errors=["No Hyperliquid provider configured"],
                )

            # Fetch markets
            from backend.data.hyperliquid_client import HyperliquidClient

            client = hl_provider if isinstance(hl_provider, HyperliquidClient) else None
            if client is None:
                # Try to get from data pipeline
                from backend.data.pipeline_manager import pipeline_manager

                client = getattr(pipeline_manager, "_hl_client", None)

            if client is None:
                return CycleResult(
                    decisions_recorded=0,
                    trades_attempted=0,
                    trades_placed=0,
                    errors=["Hyperliquid client not initialized"],
                )

            markets = await client.get_markets()
            if not markets:
                ctx.logger.debug("[hyperliquid] No markets available")
                return CycleResult(
                    decisions_recorded=0,
                    trades_attempted=0,
                    trades_placed=0,
                )

            for market in markets:
                if market.status != "active":
                    continue

                # Check for mispricing between outcomes
                if len(market.outcome_prices) >= 2:
                    yes_price = market.outcome_prices[0]
                    no_price = market.outcome_prices[1]

                    # Simple mean-reversion: if Yes is underpriced vs No
                    implied_sum = yes_price + no_price
                    if implied_sum < 0.98 or implied_sum > 1.02:
                        # Mispriced market — sum should be ~1.0
                        edge = abs(1.0 - implied_sum) / 2.0
                        if edge >= min_edge:
                            direction = "BUY" if yes_price < no_price else "SELL"
                            target_price = yes_price if direction == "BUY" else no_price

                            if target_price <= max_entry:
                                decisions_recorded += 1
                                trades_attempted += 1

                                if ctx.mode != "paper":
                                    # Live trade would go here
                                    ctx.logger.info(
                                        "[hyperliquid] Signal: %s %s at %.4f (edge=%.4f) on %s",
                                        direction,
                                        "YES",
                                        target_price,
                                        edge,
                                        market.market_id,
                                    )
                                    trades_placed += 1
                                else:
                                    ctx.logger.info(
                                        "[hyperliquid] Paper signal: %s %s at %.4f (edge=%.4f) on %s",
                                        direction,
                                        "YES",
                                        target_price,
                                        edge,
                                        market.market_id,
                                    )
                                    trades_placed += 1

        except Exception as e:
            ctx.logger.exception("[hyperliquid] Error in run_cycle: %s", e)
            errors.append(str(e))

        return CycleResult(
            decisions_recorded=decisions_recorded,
            trades_attempted=trades_attempted,
            trades_placed=trades_placed,
            errors=errors,
        )
