"""Longshot Bias Strategy — exploit Polymarket longshot pricing inefficiency.

Based on empirical research (Becker data, 72M trades):
- NO bets at <30c: +23% expected value
- YES bets at <30c: -41% expected value (avoid)

This strategy systematically buys NO tokens on low-probability markets
where the crowd overpays for YES tickets.
"""

from __future__ import annotations

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    MarketInfo,
    StrategyContext,
    MarketEvent,
)

# Polymarket platform fee (per trade, both entry and settlement)
PLATFORM_FEE_PCT = 0.02


class LongshotBiasStrategy(BaseStrategy):
    """Exploit longshot bias by buying NO on cheap markets."""

    name = "longshot_bias"
    description = (
        "Exploit Polymarket longshot bias: buy NO tokens on markets priced below "
        "30c where empirical EV is +23%. Avoid YES on same markets (-41% EV)."
    )
    category = "edge_discovery"

    default_params: dict = {
        "max_price": 0.30,
        "min_ev": 0.05,
        "max_position_usd": 20.0,
        "kelly_fraction": 0.25,
    }

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Filter to only low-price markets (below max_price threshold)."""
        max_price = self.default_params.get("max_price", 0.30)
        filtered = [m for m in markets if 0 < m.yes_price < max_price]
        return filtered

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Execute one scan cycle: find longshot markets, evaluate EV, size by Kelly."""
        max_price = ctx.params.get("max_price", self.default_params["max_price"])
        min_ev = ctx.params.get("min_ev", self.default_params["min_ev"])
        max_position = ctx.params.get(
            "max_position_usd", self.default_params["max_position_usd"]
        )
        kelly_frac = ctx.params.get(
            "kelly_fraction", self.default_params["kelly_fraction"]
        )

        decisions_recorded = 0
        trades_attempted = 0
        trades_placed = 0
        errors: list[str] = []

        try:
            # Get markets from primary provider
            provider = ctx.primary_provider
            if provider is None:
                ctx.logger.warning("[longshot_bias] No market provider available")
                return CycleResult(
                    decisions_recorded=0,
                    trades_attempted=0,
                    trades_placed=0,
                    errors=["No market provider available"],
                )

            # Scan for cheap markets
            raw_markets = await provider.get_markets(limit=200)
            candidates = [
                m
                for m in raw_markets
                if hasattr(m, "yes_price") and 0 < m.yes_price < max_price
            ]

            ctx.logger.info(
                "[longshot_bias] Found {} markets below {}c",
                len(candidates),
                int(max_price * 100),
            )

            for market in candidates:
                try:
                    yes_price = market.yes_price
                    # Use actual NO price from market/orderbook, not 1-complement.
                    # The 1-complement assumes perfectly efficient binary pricing,
                    # which fails during CLOB dislocations or illiquidity.
                    no_price = getattr(market, "no_price", None)
                    if no_price is None:
                        no_price = 1.0 - yes_price

                    # EV calculation for NO token:
                    # Per Becker data: NO at <30c has +23% expected value.
                    # Use hardcoded empirical EV (bias_factor = 0.23).
                    # At lower prices the empirical advantage is stronger,
                    # but the 0.23 figure is the conservative anchor.
                    # Net after Polymarket platform fees (entry + settlement):
                    #   gross_payout = 1.0
                    #   fee_per_dollar = 2 * PLATFORM_FEE_PCT = 0.04
                    #   net_payout = 0.96
                    #   EV = 0.23 * no_price * net_payout - (1 - 0.23) * no_price  [if fully efficient]
                    # Simplified: use empirical EV directly, scale by no_price.
                    # Empirical EV already factors in the crowd overpricing of YES.
                    ev = max(0.0, 0.23 * no_price)
                    # Subtract platform fees (both entry and settlement)
                    ev = max(0.0, ev - 2 * PLATFORM_FEE_PCT * no_price)

                    if ev < min_ev:
                        continue

                    # E-107: Kelly sizing — use market price directly as win prob.
                    # EV was already computed above and accounted for separately.
                    # Do NOT add EV to probability — that double-counts the edge.
                    true_win_prob = min(0.95, 1.0 - yes_price)
                    odds = (1.0 / no_price) - 1.0  # net odds
                    if odds <= 0.001:  # guard: no_price >= 0.999 → effectively zero odds
                        continue
                    if true_win_prob <= 0 or true_win_prob >= 1.0:
                        continue
                    kelly = (true_win_prob * odds - (1.0 - true_win_prob)) / odds
                    kelly = max(0, kelly * kelly_frac)  # fractional Kelly
                    position_size = min(kelly * 100.0, max_position)  # cap at max

                    if position_size < 5.0:  # below min order
                        continue

                    decisions_recorded += 1
                    trades_attempted += 1

                    # Place order via CLOB
                    no_token_id = market.metadata.get("no_token_id")
                    if not no_token_id:
                        ctx.logger.warning(
                            "[longshot_bias] Skipping {} — no no_token_id in metadata",
                            market.slug,
                        )
                        continue

                    if ctx.mode != "paper":
                        order = await ctx.clob.place_order(
                            token_id=no_token_id,
                            side="BUY",
                            price=no_price,
                            size=position_size,
                        )
                        if order:
                            trades_placed += 1
                    else:
                        trades_placed += 1  # paper mode auto-fills

                    ctx.logger.info(
                        "[longshot_bias] {} NO @ {:.2f}c | EV: {:.1%} | Kelly: {:.1%} | ${:.2f}",
                        market.slug,
                        no_price * 100,
                        ev,
                        kelly,
                        position_size,
                    )

                except Exception as exc:
                    errors.append(str(exc))
                    ctx.logger.error(
                        "[longshot_bias] Error on {}: {}", market.slug, exc
                    )

        except Exception as exc:
            errors.append(str(exc))
            ctx.logger.exception("[longshot_bias] Cycle failed: {}", exc)

        return CycleResult(
            decisions_recorded=decisions_recorded,
            trades_attempted=trades_attempted,
            trades_placed=trades_placed,
            errors=errors,
        )
