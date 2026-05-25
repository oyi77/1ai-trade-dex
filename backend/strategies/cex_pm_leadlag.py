"""
CEX → PM Lead-Lag Strategy.

Centralized exchanges (Binance, Coinbase, Kraken) move first on BTC price action.
Polymarket binary markets reprice with measurable lag (seconds to ~1min).

When CEX 1m momentum exceeds `min_momentum`, infer the implied direction for
each active BTC 5-min binary and compare against the current PM mid (via CLOB
midpoint endpoint). If the directional edge exceeds `min_edge`, fire a BUY.

Reuses `compute_btc_microstructure()` (multi-exchange aggregation cached 30s).
Markets discovered via `fetch_active_btc_markets()` which returns structured
`BtcMarket` objects with 5-min UP/DOWN windows and direct CLOB token IDs.
"""

import httpx
import math

from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult
from backend.core.decisions import record_decision_standalone
from backend.core.activity_logger import activity_logger
from backend.data.crypto import compute_btc_microstructure
from backend.data.btc_markets import BtcMarket, fetch_active_btc_markets
from backend.ai.debate_router import run_debate_with_routing
from backend.config import settings

from loguru import logger

PM_MIDPOINT_URL = f"{settings.CLOB_API_URL}/midpoint"


async def _fetch_pm_mid(client: httpx.AsyncClient, token_id: str) -> float | None:
    """Fetch the CLOB midpoint price for a given token ID."""
    try:
        r = await client.get(
            PM_MIDPOINT_URL, params={"token_id": token_id}, timeout=4.0
        )
        if r.status_code != 200:
            return None
        data = r.json()
        mid = data.get("mid") if isinstance(data, dict) else None
        return float(mid) if mid is not None else None
    except Exception as e:
        logger.debug(f"cex_pm_leadlag: midpoint fetch failed for {token_id[:12]}…: {e}")
        return None


class CexPmLeadLagStrategy(BaseStrategy):
    name = "cex_pm_leadlag"
    description = (
        "CEX→PM lead-lag: trade BTC 5-min UP/DOWN binaries when 1m CEX momentum "
        "disagrees with stale Polymarket mid by > min_edge."
    )
    category = "crypto"
    default_params = {
        "min_momentum": settings.CEX_PM_LEADLAG_MIN_MOMENTUM,
        "min_edge": settings.CEX_PM_LEADLAG_MIN_EDGE,
        "max_minutes_to_resolution": 10,  # tight: 5-min BTC markets, 1m momentum decays fast
        "max_position_usd": settings.CEX_PM_LEADLAG_MAX_POSITION_USD,
        "interval_seconds": settings.CEX_PM_LEADLAG_INTERVAL_SECONDS,
        "fee_rate": settings.PAPER_CLOB_FEE_RATE,  # 2% taker fee (entry + exit)
        "min_volatility": 0.001,   # skip flat markets (no edge)
        "max_volatility": 0.10,   # skip extreme chaos (whipsaws), 10% annualized vol threshold
        "momentum_norm": 0.006,    # 0.6% 1-min move = max sigmoid confidence (~93%)
        "debate_enabled": True,     # validate signals via MiroFish/local Bull/Bear/Judge debate
        "debate_min_confidence": 0.52,  # minimum debate confidence to pass gate
    }

    async def market_filter(self, markets: list[BtcMarket]) -> list[BtcMarket]:
        """Filter to active BTC 5-min markets with valid token IDs."""
        return [
            m
            for m in markets
            if m.is_active and m.up_token_id and m.down_token_id and not m.closed
        ]

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        logger.info("[cex_pm_leadlag] === run_cycle START ===")
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        params = {**self.default_params, **(ctx.params or {})}
        min_momentum = float(params["min_momentum"])
        min_edge = float(params["min_edge"])
        max_minutes = float(params["max_minutes_to_resolution"])
        max_size = float(params["max_position_usd"])
        fee_rate = float(params.get("fee_rate", settings.PAPER_CLOB_FEE_RATE))
        min_volatility = float(params.get("min_volatility", 0.001))
        max_volatility = float(params.get("max_volatility", 0.030))

        try:
            micro = await compute_btc_microstructure()
        except Exception as e:
            result.errors.append(f"microstructure fetch failed: {e}")
            return result

        if micro is None or micro.price <= 0 or micro.momentum_1m is None:
            result.errors.append("microstructure unavailable or missing momentum_1m")
            return result

        momentum_norm = float(params.get("momentum_norm", 0.008))

        if abs(micro.momentum_1m) < min_momentum:
            logger.info(f"[cex_pm_leadlag] momentum {abs(micro.momentum_1m):.4f} < min_momentum {min_momentum}")
            return result

        # Volatility regime filter — skip flat or choppy markets
        if micro.volatility is not None:
            if micro.volatility < min_volatility:
                logger.info(f"[cex_pm_leadlag] volatility {micro.volatility:.4f} < min_volatility {min_volatility}")
                return result
            if micro.volatility > max_volatility:
                logger.info(f"[cex_pm_leadlag] volatility {micro.volatility:.4f} > max_volatility {max_volatility}")
                return result

        momentum_positive = micro.momentum_1m > 0
        direction = "up" if momentum_positive else "down"

        try:
            all_markets = await fetch_active_btc_markets()
        except Exception as e:
            result.errors.append(f"market discovery failed: {e}")
            return result

        candidates = await self.market_filter(all_markets)

        async with httpx.AsyncClient() as http:
            for market in candidates:
                minutes_remaining = market.time_until_end / 60.0
                if minutes_remaining <= 0 or minutes_remaining > max_minutes:
                    continue

                pm_up_mid = await _fetch_pm_mid(http, market.up_token_id)
                if pm_up_mid is None:
                    # Skip — stale fallback creates phantom edges
                    continue

                if direction == "up":
                    target_mid = pm_up_mid
                else:
                    target_mid = 1.0 - pm_up_mid

                # Sigmoid implied probability: smoother than linear, saturates gracefully
                # NOTE: This maps BTC momentum magnitude to probability, but BTC momentum
                # is itself driven by CEX supply/demand — PM crypto markets DO react to BTC
                # momentum because traders buy PM tokens based on BTC direction.
                # The edge is a LEAD signal: BTC goes up → PM_UP gets bought → price rises.
                # Because this relationship is NOISY, cap the max implied probability to avoid
                # phantom edges from tiny momentum readings.
                strength = abs(micro.momentum_1m) / momentum_norm
                sigmoid = 2.0 / (1.0 + math.exp(-3.0 * strength)) - 1.0  # [-1,+1]
                raw_prob = max(0.01, min(0.99, 0.5 + 0.49 * sigmoid))
                # CRITICAL FIX: cap raw probability to prevent 70%+ phantom edges from
                # tiny momentum (0.1% move shouldn't produce >60% confidence)
                implied_prob = max(0.40, min(0.65, raw_prob))
                total_fees = fee_rate * 2
                edge = (implied_prob - target_mid) - min_edge - total_fees

                confidence = (
                    min(1.0, abs(edge + min_edge) / min_edge) if min_edge > 0 else 0.0
                )

                decision = "BUY" if edge > 0 else "SKIP"
                if decision == "BUY" and params.get("debate_enabled", True):
                    try:
                        question = (
                            f"BTC price {micro.price:.0f} with {abs(micro.momentum_1m):.4f} 1-min momentum. "
                            f"Will BTC be {'UP' if direction == 'up' else 'DOWN'} in the next 5-minute window? "
                            f"Polymarket UP mid={pm_up_mid:.3f}, implied edge={edge:.4f}. Trade or skip?"
                        )
                        debate_result = await run_debate_with_routing(
                            db=ctx.db,
                            question=question,
                            market_price=target_mid,
                            context=(
                                f"signal_data={{\"momentum_1m\":{micro.momentum_1m:.4f},"
                                f"\"momentum_5m\":{micro.momentum_5m},"
                                f"\"volatility\":{micro.volatility:.4f},"
                                f"\"btc_price\":{micro.price:.0f}}}"
                            ),
                            max_rounds=2,
                        )
                        if debate_result and debate_result.confidence > 0:
                            debate_min_conf = float(params.get("debate_min_confidence", 0.55))
                            if debate_result.confidence < debate_min_conf:
                                logger.info(
                                    "[cex_pm_leadlag] debate rejected %s for %s (confidence=%.2f < %.2f)",
                                    decision, market.slug, debate_result.confidence, debate_min_conf,
                                )
                                continue
                            confidence = max(confidence, debate_result.confidence)
                    except Exception:
                        logger.debug("[cex_pm_leadlag] debate validation failed, allowing trade")
                projected_price = micro.price * (1.0 + micro.momentum_1m)

                signal_data = {
                    "btc_price": micro.price,
                    "momentum_1m": micro.momentum_1m,
                    "momentum_5m": micro.momentum_5m,
                    "projected_price": projected_price,
                    "pm_up_mid": pm_up_mid,
                    "target_mid": target_mid,
                    "direction": direction,
                    "edge": edge,
                    "minutes_remaining": round(minutes_remaining, 2),
                    "source": micro.source,  # legacy field (exchange list)
                    "sources": ["cex_pm_leadlag"]
                    + (
                        micro.source
                        if isinstance(micro.source, list)
                        else [micro.source]
                    ),  # AGI learning
                    "slug": market.slug,
                    "up_price": market.up_price,
                    "down_price": market.down_price,
                    "spread": market.spread,
                    "window_end": market.window_end.isoformat(),
                }

                record_decision_standalone(
                    self.name,
                    market.slug,
                    decision,
                    confidence=confidence,
                    signal_data=signal_data,
                    reason=(
                        f"leadlag mom1m={micro.momentum_1m:+.4f} "
                        f"dir={direction} pm_mid={target_mid:.3f} "
                        f"edge={edge:+.3f} t={minutes_remaining:.1f}min "
                        f"slug={market.slug}"
                    ),
                )
                result.decisions_recorded += 1

                try:
                    activity_logger.log_entry(
                        strategy_name=self.name,
                        decision_type="entry" if decision == "BUY" else "hold",
                        data=signal_data,
                        confidence=confidence,
                        mode=ctx.mode,
                        db=ctx.db,
                    )
                except Exception:
                    logger.exception("Failed to record CEX-PM lead-lag decision")

                if decision == "BUY":
                    result.trades_attempted += 1
                    chosen_token = (
                        market.up_token_id
                        if direction == "up"
                        else market.down_token_id
                    )
                    entry_price = target_mid
                    # Edge-proportional sizing: scale position by edge strength
                    size_scalar = min(1.0, (edge + min_edge) / (min_edge * 2)) if min_edge > 0 else 0.5
                    suggested_size = round(max_size * max(0.25, size_scalar), 2)
                    result.decisions.append(
                        {
                            "decision": "BUY",
                            "market_ticker": market.slug,
                            "token_id": chosen_token,
                            "direction": direction,
                            "confidence": confidence,
                            "edge": edge,
                            "size": suggested_size,
                            "entry_price": entry_price,
                            "suggested_size": suggested_size,
                            "model_probability": implied_prob,
                            "market_probability": target_mid,
                            "platform": settings.DEFAULT_VENUE,
                            "strategy_name": self.name,
                            "reasoning": (
                                f"CEX 1m momentum {micro.momentum_1m:+.4f} → "
                                f"direction={direction}, PM mid {target_mid:.3f}, "
                                f"edge {edge:+.3f}"
                            ),
                            "slug": market.slug,
                            "market_end_date": market.window_end.isoformat(),
                        }
                    )

        return result
