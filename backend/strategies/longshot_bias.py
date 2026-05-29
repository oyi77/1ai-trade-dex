"""Longshot Bias Strategy — exploit Polymarket longshot pricing inefficiency.

Based on empirical research (Becker data, 72M trades):
- NO bets at <30c: +23% expected value
- YES bets at <30c: -41% expected value (avoid)

This strategy systematically buys NO tokens on low-probability markets
where the crowd overpays for YES tickets.
"""

from __future__ import annotations

import json

import httpx

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    MarketInfo,
    StrategyContext,
    MarketEvent,
)
from backend.config import settings

from loguru import logger

# Polymarket platform fee (per trade, both entry and settlement)
PLATFORM_FEE_PCT = 0.02

GAMMA_API_URL = f"{settings.GAMMA_API_URL}/markets"


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
        params = {**self.default_params, **(ctx.params or {})}

        # Check open positions for auto-sell exits at cycle start
        try:
            from backend.core.auto_sell import check_strategy_positions_for_auto_sell
            await check_strategy_positions_for_auto_sell(
                self.name,
                clob_client=ctx.clob,
                profit_target_pct=float(params["auto_sell_profit_target_pct"]) if params.get("auto_sell_profit_target_pct") is not None else None,
                stop_loss_pct=float(params["auto_sell_stop_loss_pct"]) if params.get("auto_sell_stop_loss_pct") is not None else None,
                max_hold_seconds=int(params["auto_sell_max_hold_seconds"]) if params.get("auto_sell_max_hold_seconds") is not None else None,
            )
        except Exception as e:
            ctx.logger.warning(f"[{self.name}] Auto-sell start check failed: {e}")

        max_price = params.get("max_price")
        min_ev = params.get("min_ev")
        max_position = params.get("max_position_usd")
        kelly_frac = params.get("kelly_fraction")

        decisions_recorded = 0
        trades_attempted = 0
        trades_placed = 0
        errors: list[str] = []

        try:
            # Fetch markets directly from Gamma API (raw dicts with clobTokenIds)
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(
                        GAMMA_API_URL,
                        params={
                            "active": "true",
                            "closed": "false",
                            "limit": 500,
                            "order": "volume",
                            "ascending": "false",
                        },
                    )
                    resp.raise_for_status()
                    raw_markets = resp.json()
            except Exception as e:
                ctx.logger.warning(f"[longshot_bias] Gamma API fetch failed: {e}")
                return CycleResult(0, 0, 0, errors=[str(e)])

            if not isinstance(raw_markets, list):
                ctx.logger.warning("[longshot_bias] Unexpected Gamma API response format")
                return CycleResult(0, 0, 0)

            # Filter to cheap markets (YES price < max_price)
            candidates = []
            for m in raw_markets:
                outcome_prices_raw = m.get("outcomePrices") or []
                if isinstance(outcome_prices_raw, str):
                    try:
                        outcome_prices_raw = json.loads(outcome_prices_raw)
                    except Exception:
                        continue
                if not outcome_prices_raw:
                    continue
                try:
                    yes_price = float(outcome_prices_raw[0])
                except (TypeError, ValueError):
                    continue
                if 0 < yes_price < max_price:
                    candidates.append((m, yes_price))

            # Get dynamic longshot bias from actual settled trades
            from backend.core.longshot_bias import LongshotBiasDetector
            detector = LongshotBiasDetector()
            bias_stats = None
            if ctx.db is not None:
                try:
                    bias_stats = detector.compute_longshot_bias_from_trades(
                        db=ctx.db,
                        price_threshold=max_price,
                        window_days=60,
                        strategy_name=self.name,
                    )
                except Exception as e:
                    ctx.logger.warning("[longshot_bias] Failed to compute dynamic longshot bias: {}", e)

            # Fallback to historical paper average (YES trades win rate is 59% of price)
            bias_ratio = bias_stats["bias"] if bias_stats is not None else 0.59
            ctx.logger.info(
                "[longshot_bias] Found {} markets below {}c (using bias ratio: {:.4f})",
                len(candidates),
                int(max_price * 100),
                bias_ratio,
            )

            for market, yes_price in candidates:
                try:
                    slug = market.get("slug") or market.get("conditionId") or "unknown"
                    no_price = 1.0 - yes_price

                    # EV calculation for NO token based on YES overpricing bias:
                    # gross edge of NO is: yes_price * (1.0 - bias_ratio)
                    ev = max(0.0, yes_price * (1.0 - bias_ratio))
                    # Subtract platform fees (both entry and settlement)
                    ev = max(0.0, ev - 2 * PLATFORM_FEE_PCT * no_price)

                    if ev < min_ev:
                        continue

                    # True win probability of NO is: 1.0 - yes_price * bias_ratio
                    true_win_prob = min(0.95, 1.0 - yes_price * bias_ratio)
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

                    # Extract NO token ID from clobTokenIds (index 1 = NO)
                    clob_token_ids = market.get("clobTokenIds") or []
                    if isinstance(clob_token_ids, str):
                        try:
                            clob_token_ids = json.loads(clob_token_ids)
                        except Exception:
                            clob_token_ids = []
                    no_token_id = clob_token_ids[1] if len(clob_token_ids) > 1 else None
                    if not no_token_id:
                        ctx.logger.warning(
                            "[longshot_bias] Skipping {} — no clobTokenIds[1]",
                            slug,
                        )
                        continue

                    decisions_recorded += 1
                    trades_attempted += 1

                    # Place order via CLOB
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
                        slug,
                        no_price * 100,
                        ev,
                        kelly,
                        position_size,
                    )

                except Exception as exc:
                    errors.append(str(exc))
                    ctx.logger.error(
                        "[longshot_bias] Error on {}: {}", slug, exc
                    )

        except Exception as exc:
            errors.append(str(exc))
            ctx.logger.exception("[longshot_bias] Cycle failed: {}", exc)

        # Check open positions for auto-sell exits at cycle end
        try:
            from backend.core.auto_sell import check_strategy_positions_for_auto_sell
            await check_strategy_positions_for_auto_sell(
                self.name,
                clob_client=ctx.clob,
                profit_target_pct=float(params["auto_sell_profit_target_pct"]) if params.get("auto_sell_profit_target_pct") is not None else None,
                stop_loss_pct=float(params["auto_sell_stop_loss_pct"]) if params.get("auto_sell_stop_loss_pct") is not None else None,
                max_hold_seconds=int(params["auto_sell_max_hold_seconds"]) if params.get("auto_sell_max_hold_seconds") is not None else None,
            )
        except Exception as e:
            ctx.logger.warning(f"[{self.name}] Auto-sell end check failed: {e}")

        return CycleResult(
            decisions_recorded=decisions_recorded,
            trades_attempted=trades_attempted,
            trades_placed=trades_placed,
            errors=errors,
        )
