"""Longshot Bias Strategy — exploit Polymarket longshot pricing inefficiency.

Based on empirical research (Becker data, 72M trades):
- NO bets at <30c: +23% expected value
- YES bets at <30c: -41% expected value (avoid)

This strategy systematically buys NO tokens on low-probability markets
where the crowd overpays for YES tickets.
"""

from __future__ import annotations

import json as _json

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    MarketInfo,
    StrategyContext,
    MarketEvent,
)

# Polymarket platform fee (per trade, both entry and settlement)
PLATFORM_FEE_PCT = 0.02


def _resolve_yes_no_prices(market_dict: dict) -> tuple[float, float]:
    """Extract YES and NO prices from a Gamma API market dict.

    The ``outcomes`` array defines the ordering of ``outcomePrices``.
    For binary Yes/No markets the Gamma API *usually* returns
    ``["Yes", "No"]`` so that ``outcomePrices[0]`` is the YES price,
    but some markets (or legacy data) use ``["No", "Yes"]`` which
    would invert the mapping.  This helper resolves both cases by
    checking the ``outcomes`` labels when available, falling back to
    index 0 = YES when the array is missing or unrecognisable.
    """
    outcome_prices_raw = market_dict.get("outcomePrices") or []
    if isinstance(outcome_prices_raw, str):
        try:
            outcome_prices_raw = _json.loads(outcome_prices_raw)
        except Exception:
            outcome_prices_raw = []

    if not outcome_prices_raw or len(outcome_prices_raw) < 2:
        return 0.5, 0.5

    # Try to resolve ordering from the outcomes array
    outcomes_raw = market_dict.get("outcomes") or []
    if isinstance(outcomes_raw, str):
        try:
            outcomes_raw = _json.loads(outcomes_raw)
        except Exception:
            outcomes_raw = []

    yes_idx, no_idx = 0, 1  # default assumption: index 0 = YES
    if len(outcomes_raw) >= 2:
        first = str(outcomes_raw[0]).strip().lower()
        second = str(outcomes_raw[1]).strip().lower()
        # If first outcome is "no" (or "down"), swap
        if first in ("no", "down") and second in ("yes", "up"):
            yes_idx, no_idx = 1, 0

    try:
        yes_price = float(outcome_prices_raw[yes_idx])
        no_price = float(outcome_prices_raw[no_idx])
    except (TypeError, ValueError, IndexError):
        yes_price = float(outcome_prices_raw[0])
        no_price = float(outcome_prices_raw[1]) if len(outcome_prices_raw) > 1 else 1.0 - yes_price

    return yes_price, no_price


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
        result_decisions: list[dict] = []

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

            # Scan for cheap markets — resolve YES/NO prices using outcomes array
            raw_markets = await provider.get_markets(limit=200)
            candidates: list[tuple[object, float, float]] = []  # (market, yes_price, no_price)
            for m in raw_markets:
                # Resolve prices from raw market dict if available
                raw_dict = getattr(m, "metadata", None) or (m if isinstance(m, dict) else None)
                if raw_dict and isinstance(raw_dict, dict) and "outcomePrices" in raw_dict:
                    yes_p, no_p = _resolve_yes_no_prices(raw_dict)
                elif hasattr(m, "yes_price"):
                    yes_p = float(m.yes_price)
                    no_p = float(getattr(m, "no_price", 1.0 - yes_p))
                else:
                    continue

                # Debug: log raw outcomePrices for first few markets
                if len(candidates) < 5:
                    ctx.logger.debug(
                        "[longshot_bias] {} yes={:.4f} no={:.4f} raw_outcomePrices={}",
                        getattr(m, "slug", getattr(m, "ticker", "?")),
                        yes_p, no_p,
                        (raw_dict or {}).get("outcomePrices", "N/A"),
                    )

                if 0 < yes_p < max_price:
                    candidates.append((m, yes_p, no_p))

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

            for market, yes_price, no_price in candidates:
                try:
                    market_slug = getattr(market, "slug", "") or ""

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

                    if position_size < 1.0:  # min $1 order (was $5, too high for $1.89 balance)
                        continue

                    decisions_recorded += 1
                    trades_attempted += 1

                    # Place order via CLOB
                    metadata = getattr(market, "metadata", None) or (market if isinstance(market, dict) else {})
                    if not isinstance(metadata, dict):
                        metadata = {}
                    no_token_id = metadata.get("no_token_id")
                    if not no_token_id:
                        ctx.logger.warning(
                            "[longshot_bias] Skipping {} — no no_token_id in metadata",
                            market_slug,
                        )
                        continue

                    # Build decision dict (for shadow trade tracking + trade log)
                    decision = {
                        "market_ticker": market_slug,
                        "market_slug": market_slug,
                        "token_id": no_token_id,
                        "market_question": getattr(market, "question", "") or market_slug,
                        "direction": "down",
                        "decision": "BUY",
                        "entry_price": round(no_price, 4),
                        "size": round(position_size, 2),
                        "suggested_size": round(position_size, 2),
                        "edge": round(ev, 4),
                        "confidence": round(kelly, 4),
                        "model_probability": round(true_win_prob, 4),
                        "market_probability": round(yes_price, 4),
                        "platform": "polymarket",
                        "strategy_name": self.name,
                        "trading_mode": ctx.mode,
                    }

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

                    result_decisions.append(decision)

                    ctx.logger.info(
                        "[longshot_bias] {} NO @ {:.2f}c | EV: {:.1%} | Kelly: {:.1%} | ${:.2f}",
                        market_slug,
                        no_price * 100,
                        ev,
                        kelly,
                        position_size,
                    )

                except Exception as exc:
                    errors.append(str(exc))
                    ctx.logger.error(
                        "[longshot_bias] Error on {}: {}",
                        getattr(market, "slug", "?"),
                        exc,
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
            decisions=result_decisions,
        )
