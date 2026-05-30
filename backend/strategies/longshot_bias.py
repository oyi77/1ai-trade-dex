"""Longshot Bias Strategy — exploit Polymarket longshot pricing inefficiency.

Based on empirical research (Becker data, 72M trades):
- NO bets at <30c: +23% expected value
- YES bets at <30c: -41% expected value (avoid)

This strategy systematically buys NO tokens on low-probability markets
where the crowd overpays for YES tickets.
"""

from __future__ import annotations

from decimal import Decimal

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    MarketInfo,
    StrategyContext,
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
        return [m for m in markets if 0 < m.yes_price < max_price]

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Execute one scan cycle: find longshot markets, evaluate EV, size by Kelly."""
        import json

        params = {**self.default_params, **(ctx.params or {})}

        max_price = float(params.get("max_price", 0.30))
        min_ev = float(params.get("min_ev", 0.05))
        max_position = float(params.get("max_position_usd", 20.0))
        kelly_frac = float(params.get("kelly_fraction", 0.25))

        decisions_recorded = 0
        trades_attempted = 0
        trades_placed = 0
        errors: list[str] = []
        decisions: list[dict] = []

        try:
            # Fetch markets directly from Gamma API
            from backend.data.gamma import fetch_markets
            raw_markets = await fetch_markets(limit=200)

            # Parse outcomePrices to extract yes/no prices
            parsed_markets = []
            for m in raw_markets:
                try:
                    prices = m.get("outcomePrices", "")
                    if isinstance(prices, str):
                        prices = json.loads(prices)
                    outcomes = m.get("outcomes", "")
                    if isinstance(outcomes, str):
                        outcomes = json.loads(outcomes)
                    if len(prices) < 2 or len(outcomes) < 2:
                        continue
                    yes_idx = outcomes.index("Yes") if "Yes" in outcomes else 0
                    yes_price = float(prices[yes_idx])
                    no_price = float(prices[1 - yes_idx])
                    clob_ids = m.get("clobTokenIds", [])
                    if isinstance(clob_ids, str):
                        clob_ids = json.loads(clob_ids)
                    parsed_markets.append({
                        "slug": m.get("slug", ""),
                        "question": m.get("question", ""),
                        "yes_price": yes_price,
                        "no_price": no_price,
                        "clob_ids": clob_ids,
                    })
                except Exception:
                    continue

            candidates = [m for m in parsed_markets if 0 < m["yes_price"] < max_price]

            # Get dynamic longshot bias
            bias_ratio = 0.59  # fallback: YES trades win rate
            try:
                from backend.core.longshot_bias import LongshotBiasDetector
                detector = LongshotBiasDetector()
                if ctx.db is not None:
                    bias_stats = detector.compute_longshot_bias_from_trades(
                        db=ctx.db, price_threshold=max_price, window_days=60,
                        strategy_name=self.name,
                    )
                    if bias_stats is not None:
                        bias_ratio = bias_stats["bias"]
            except Exception as e:
                ctx.logger.warning("[longshot_bias] Bias calc failed: {}", e)

            ctx.logger.info(
                f"[longshot_bias] Found {len(candidates)} markets below {int(max_price*100)}c (bias={bias_ratio:.4f}) parsed={len(parsed_markets)} raw={len(raw_markets)}"
            )

            for market in candidates:
                try:
                    yes_price = market["yes_price"]
                    no_price = market["no_price"]
                    slug = market["slug"]

                    ev = max(0.0, yes_price * (1.0 - bias_ratio))
                    ev = max(0.0, ev - 2 * PLATFORM_FEE_PCT * no_price)
                    if ev < min_ev:
                        if slug == candidates[0]["slug"]:  # debug first market
                            ctx.logger.info(f"[longshot_bias] SKIP ev: {slug} yes={yes_price:.3f} no={no_price:.3f} ev={ev:.4f} < min_ev={min_ev}")
                        continue

                    true_win_prob = min(0.95, 1.0 - yes_price * bias_ratio)
                    odds = (1.0 / no_price) - 1.0
                    if odds <= 0.001 or true_win_prob <= 0 or true_win_prob >= 1.0:
                        continue

                    kelly = (true_win_prob * odds - (1.0 - true_win_prob)) / odds
                    kelly = max(0, kelly * kelly_frac)
                    position_size = min(kelly * ctx.bankroll, max_position)

                    if position_size < 1.01:
                        continue

                    decisions_recorded += 1
                    trades_attempted += 1

                    clob_ids = market["clob_ids"]
                    if len(clob_ids) < 2:
                        ctx.logger.warning("[longshot_bias] Skipping {} — no clobTokenIds", slug)
                        continue
                    no_token_id = clob_ids[1]

                    decision = {
                        "decision": "BUY",
                        "direction": "NO",
                        "market_slug": slug,
                        "token_id": no_token_id,
                        "side": "BUY",
                        "price": round(no_price, 3),
                        "size": round(position_size, 2),
                        "ev": round(ev, 4),
                        "confidence": round(true_win_prob, 4),
                        "edge": round(ev, 4),
                    }
                    decisions.append(decision)

                    if ctx.mode != "paper":
                        provider = ctx.get_market_provider("polymarket")
                        if provider and hasattr(provider, "place_order"):
                            from backend.markets.order_types import NormalizedOrder, OrderSide, OrderType
                            norm_order = NormalizedOrder(
                                market_id=slug,
                                side=OrderSide.BUY,
                                order_type=OrderType.LIMIT,
                                size=Decimal(str(round(position_size, 2))),
                                price=Decimal(str(round(no_price, 3))),
                                metadata={"token_id": no_token_id},
                            )
                            result = await provider.place_order(norm_order)
                            if result:
                                reason = (result.raw or {}).get("error", "")
                                ctx.logger.info(f"[longshot_bias] LIVE order: {result.status} reason={reason}")
                                if result.status.name == "FILLED":
                                    trades_placed += 1
                            else:
                                ctx.logger.warning(f"[longshot_bias] LIVE order None for {slug}")
                    else:
                        trades_placed += 1

                    ctx.logger.info(
                        "[longshot_bias] {} NO @ {:.2f}c | EV: {:.1%} | Kelly: {:.1%} | ${:.2f}",
                        slug, no_price * 100, ev, kelly, position_size,
                    )

                except Exception as exc:
                    errors.append(str(exc))
                    ctx.logger.error("[longshot_bias] Error on {}: {}", market.get("slug", "?"), exc)

        except Exception as exc:
            errors.append(str(exc))
            ctx.logger.exception("[longshot_bias] Cycle failed: {}", exc)

        return CycleResult(
            decisions_recorded=decisions_recorded,
            trades_attempted=trades_attempted,
            trades_placed=trades_placed,
            errors=errors,
            decisions=decisions,
        )
