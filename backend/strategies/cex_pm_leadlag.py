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

from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult
from backend.core.decisions import record_decision_standalone
from backend.core.activity_logger import activity_logger
from backend.data.crypto import compute_btc_microstructure
from backend.data.btc_markets import BtcMarket, fetch_active_btc_markets
from backend.config import settings

from loguru import logger
PM_MIDPOINT_URL = f"{settings.CLOB_API_URL}/midpoint"


async def _fetch_pm_mid(client: httpx.AsyncClient, token_id: str) -> float | None:
    """Fetch the CLOB midpoint price for a given token ID."""
    try:
        r = await client.get(PM_MIDPOINT_URL, params={"token_id": token_id}, timeout=4.0)
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
        "max_minutes_to_resolution": settings.CEX_PM_LEADLAG_MAX_MINUTES_TO_RESOLUTION,
        "max_position_usd": settings.CEX_PM_LEADLAG_MAX_POSITION_USD,
        "interval_seconds": settings.CEX_PM_LEADLAG_INTERVAL_SECONDS,
    }

    async def market_filter(self, markets: list[BtcMarket]) -> list[BtcMarket]:
        """Filter to active BTC 5-min markets with valid token IDs."""
        return [
            m for m in markets
            if m.is_active and m.up_token_id and m.down_token_id and not m.closed
        ]

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        params = {**self.default_params, **(ctx.params or {})}
        min_momentum = float(params["min_momentum"])
        min_edge = float(params["min_edge"])
        max_minutes = float(params["max_minutes_to_resolution"])
        max_size = float(params["max_position_usd"])

        try:
            micro = await compute_btc_microstructure()
        except Exception as e:
            result.errors.append(f"microstructure fetch failed: {e}")
            return result

        if micro is None or micro.price <= 0 or micro.momentum_1m is None:
            result.errors.append("microstructure unavailable or missing momentum_1m")
            return result

        if abs(micro.momentum_1m) < min_momentum:
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
                    pm_up_mid = market.up_price or 0.5

                if direction == "up":
                    target_mid = pm_up_mid
                else:
                    target_mid = 1.0 - pm_up_mid

                # E-297: Derive implied probability from momentum strength.
                # Stronger momentum -> higher confidence in direction.
                # Normalize by 0.01 (1% BTC move/min is very strong).
                # Clamp to [0.01, 0.99] to avoid degenerate probabilities.
                momentum_norm = 0.01  # 1% BTC move = max confidence
                momentum_strength = min(1.0, abs(micro.momentum_1m) / momentum_norm)
                implied_prob = max(0.01, min(0.99, 0.5 + 0.49 * momentum_strength))
                edge = (implied_prob - target_mid) - min_edge

                decision = "BUY" if edge > 0 else "SKIP"
                confidence = min(1.0, abs(edge + min_edge) / min_edge) if min_edge > 0 else 0.0
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
                    "sources": ["cex_pm_leadlag"] + (micro.source if isinstance(micro.source, list) else [micro.source]),  # AGI learning
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
                    pass

                if decision == "BUY":
                    result.trades_attempted += 1
                    chosen_token = market.up_token_id if direction == "up" else market.down_token_id
                    entry_price = target_mid
                    result.decisions.append(
                        {
                            "decision": "BUY",
                            "market_ticker": market.slug,
                            "token_id": chosen_token,
                            "direction": direction,
                            "confidence": confidence,
                            "edge": edge,
                            "size": max_size,
                            "entry_price": entry_price,
                            "suggested_size": max_size,
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
