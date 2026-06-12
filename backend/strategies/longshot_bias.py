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
        "max_price": 0.25,
        "min_ev": 0.10,
        "min_edge": 0.15,  # need 15%+ edge (model vs market) to trade
        "min_model_prob": 0.75,  # model must say >75% likely to win
        "max_entry_price": 0.30,  # don't buy NO above 30c (longshots must be cheap)
        "min_volume": 1000,  # only liquid markets (they resolve faster)
        "max_position_usd": 10.0,
        "kelly_fraction": 0.15,
    }

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Filter to markets where the NO token is cheap (below max_price)."""
        max_price = self.default_params.get("max_price", 0.30)
        return [m for m in markets if 0 < m.no_price < max_price]

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Execute one scan cycle: find longshot markets, evaluate EV, size by Kelly."""
        import json

        params = {**self.default_params, **(ctx.params or {})}

        max_price = float(params.get("max_price", 0.30))
        min_ev = float(params.get("min_ev", 0.05))
        min_edge = float(params.get("min_edge", 0.10))
        min_model_prob = float(params.get("min_model_prob", 0.65))
        max_entry_price = float(params.get("max_entry_price", 0.40))
        max_position = float(params.get("max_position_usd", 20.0))
        kelly_frac = float(params.get("kelly_fraction", 0.25))
        min_volume = float(params.get("min_volume", 1000))

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
                    volume = float(m.get("volume", 0) or 0)
                    parsed_markets.append(
                        {
                            "slug": m.get("slug", ""),
                            "question": m.get("question", ""),
                            "yes_price": yes_price,
                            "no_price": no_price,
                            "clob_ids": clob_ids,
                            "volume": volume,
                        }
                    )
                except Exception:
                    continue

            # The strategy buys the NO token, so a "longshot below max_price"
            # market is one where no_price (not yes_price) is cheap.
            candidates = [m for m in parsed_markets if 0 < m["no_price"] < max_price and m["volume"] >= min_volume]

            # Get dynamic longshot bias
            bias_ratio = 0.59  # fallback: YES trades win rate
            try:
                from backend.core.longshot_bias import LongshotBiasDetector

                detector = LongshotBiasDetector()
                if ctx.db is not None:
                    bias_stats = detector.compute_longshot_bias_from_trades(
                        db=ctx.db,
                        price_threshold=max_price,
                        window_days=60,
                        strategy_name=self.name,
                    )
                    if bias_stats is not None:
                        bias_ratio = bias_stats["bias"]
            except Exception as e:
                ctx.logger.warning("[longshot_bias] Bias calc failed: {}", e)

            # Clamp: true_win_prob = 1 - yes_price * bias_ratio must stay
            # positive for yes_price up to 1.0, or every decision below would
            # hit the true_win_prob <= 0 guard and the strategy would go
            # silent again once enough high-win-rate trades push bias_ratio
            # (= win_rate / avg_entry_price) above ~1.
            bias_ratio = max(0.1, min(bias_ratio, 0.95))

            ctx.logger.info(
                f"[longshot_bias] Found {len(candidates)} markets below {int(max_price*100)}c (bias={bias_ratio:.4f}) parsed={len(parsed_markets)} raw={len(raw_markets)}"
            )

            for market in candidates:
                try:
                    yes_price = market["yes_price"]
                    no_price = market["no_price"]
                    slug = market["slug"]

                    # --- HARD GUARD: max entry price (longshots must be cheap) ---
                    if no_price > max_entry_price:
                        ctx.logger.info(
                            f"[longshot_bias] GUARD blocked: {slug} no_price={no_price:.3f} > max={max_entry_price:.3f}"
                        )
                        continue

                    # --- HARD GUARD: minimum model probability ---
                    # Model probability = yes_price (market-implied confidence
                    # the favorite/YES outcome occurs). The NO token we buy is
                    # the corresponding longshot, priced below max_price.
                    model_prob = yes_price
                    if model_prob < min_model_prob:
                        continue

                    # --- HARD GUARD: minimum edge (model vs market) ---
                    # Edge = model_prob (favorite confidence) - no_price (cost
                    # of the longshot NO token) — requires a lopsided market.
                    edge = model_prob - no_price
                    if edge < min_edge:
                        continue

                    ev = max(0.0, yes_price * (1.0 - bias_ratio))
                    ev = max(0.0, ev - 2 * PLATFORM_FEE_PCT * no_price)
                    if ev < min_ev:
                        if slug == candidates[0]["slug"]:  # debug first market
                            ctx.logger.info(
                                f"[longshot_bias] SKIP ev: {slug} yes={yes_price:.3f} no={no_price:.3f} ev={ev:.4f} < min_ev={min_ev}"
                            )
                        continue

                    true_win_prob = min(0.95, 1.0 - yes_price * bias_ratio)
                    odds = (1.0 / no_price) - 1.0
                    if odds <= 0.001 or true_win_prob <= 0 or true_win_prob >= 1.0:
                        continue

                    kelly = (true_win_prob * odds - (1.0 - true_win_prob)) / odds
                    kelly = max(0, kelly * kelly_frac)
                    position_size = min(kelly * ctx.bankroll, max_position)

                    if position_size < 0.50:
                        continue
                    position_size = max(position_size, 1.0)  # CLOB minimum $1.0

                    decisions_recorded += 1
                    trades_attempted += 1

                    clob_ids = market["clob_ids"]
                    if len(clob_ids) < 2:
                        ctx.logger.warning(
                            "[longshot_bias] Skipping {} — no clobTokenIds", slug
                        )
                        continue
                    no_token_id = clob_ids[1]

                    decision = {
                        "decision": "BUY",
                        "direction": "no",
                        "market_ticker": slug,
                        "token_id": no_token_id,
                        "side": "BUY",
                        "entry_price": round(no_price, 3),
                        "size": round(position_size, 2),
                        "ev": round(ev, 4),
                        "confidence": round(true_win_prob, 4),
                        "edge": round(edge, 4),
                    }
                    decisions.append(decision)

                    if ctx.mode != "paper":
                        ctx.logger.info(
                            f"[longshot_bias] LIVE path: ctx.mode={ctx.mode} slug={slug}"
                        )

                        provider = ctx.get_market_provider("polymarket")
                        if provider and hasattr(provider, "place_order"):
                            from backend.markets.order_types import (
                                NormalizedOrder,
                                OrderSide,
                                OrderType,
                            )

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
                                ctx.logger.info(
                                    f"[longshot_bias] LIVE order: {result.status} reason={reason}"
                                )
                                if result.status.name == "FILLED":
                                    trades_placed += 1
                            else:
                                ctx.logger.warning(
                                    f"[longshot_bias] LIVE order None for {slug}"
                                )
                    else:
                        trades_placed += 1

                    ctx.logger.info(
                        "[longshot_bias] {} NO @ {:.2f}c | edge: {:.1%} | EV: {:.1%} | Kelly: {:.1%} | ${:.2f}",
                        slug,
                        no_price * 100,
                        edge,
                        ev,
                        kelly,
                        position_size,
                    )

                except Exception as exc:
                    errors.append(str(exc))
                    ctx.logger.error(
                        "[longshot_bias] Error on {}: {}", market.get("slug", "?"), exc
                    )

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
