"""CEX → PM Lead-Lag Strategy.

Centralized exchanges (Binance, Coinbase, Kraken) move first on BTC/ETH/SOL price action.
Polymarket binary markets reprice with measurable lag (seconds to ~1min).

When CEX 1m momentum exceeds `min_momentum`, infer the implied direction for
each active 5-min binary and compare against the current PM mid (via CLOB
midpoint endpoint). If the directional edge exceeds `min_edge`, fire a BUY.
"""

from __future__ import annotations

import httpx
import math
from typing import Optional, List, Any

from loguru import logger

from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult
from backend.core.decisions import record_decision_standalone
from backend.core.activity_logger import activity_logger
from backend.data.crypto import compute_crypto_microstructure
from backend.data.btc_markets import CryptoMarket, fetch_active_crypto_markets
from backend.ai.debate_router import run_debate_with_routing
from backend.config import settings

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
        "CEX→PM lead-lag: trade BTC, ETH, and SOL 5-min UP/DOWN binaries when CEX 1m momentum "
        "disagrees with Polymarket mid by > min_edge."
    )
    category = "crypto"
    default_params = {
        "min_momentum": settings.CEX_PM_LEADLAG_MIN_MOMENTUM,
        "min_edge": settings.CEX_PM_LEADLAG_MIN_EDGE,
        "max_minutes_to_resolution": 10,
        "max_position_usd": settings.CEX_PM_LEADLAG_MAX_POSITION_USD,
        "interval_seconds": 5,  # HFT optimized interval
        "fee_rate": settings.PAPER_CLOB_FEE_RATE,
        "min_volatility": 0.001,
        "max_volatility": 0.10,
        "momentum_norm": 0.006,
        "debate_enabled": True,
        "debate_min_confidence": 0.52,
        "max_open_positions": 3,
        "max_per_asset": 1,
        "stop_loss_pct": 0.20,
        "max_hold_seconds": 240,
        "profit_target_pct": 0.08,
    }

    async def market_filter(self, markets: list[CryptoMarket]) -> list[CryptoMarket]:
        """Filter to active 5-min markets with valid token IDs."""
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
        max_position_frac = getattr(settings, "MAX_POSITION_FRACTION", 0.10)
        hard_cap = float(params.get("max_position_usd", 5.0))
        dynamic_cap = ctx.bankroll * max_position_frac
        max_size = max(hard_cap, dynamic_cap)
        max_size = min(max_size, ctx.bankroll * 0.15)  # never more than 15% of bankroll per trade
        max_size = max(max_size, float(getattr(settings, "MIN_ORDER_USDC", 1.0)))
        fee_rate = float(params.get("fee_rate", settings.PAPER_CLOB_FEE_RATE))
        min_volatility = float(params.get("min_volatility", 0.001))
        max_volatility = float(params.get("max_volatility", 0.10))

        # Check open positions for auto-sell exits (profit-taking before settlement)
        try:
            from backend.core.auto_sell import check_strategy_positions_for_auto_sell
            await check_strategy_positions_for_auto_sell(
                self.name,
                clob_client=ctx.clob,
                profit_target_pct=float(params.get("profit_target_pct", 0.08)),
                stop_loss_pct=float(params.get("stop_loss_pct", 0.20)),
                max_hold_seconds=int(params.get("max_hold_seconds", 240)),
            )
        except Exception as e:
            logger.warning(f"[cex_pm_leadlag] Auto-sell exit check failed: {e}")

        # Max open positions gate
        db = ctx.db
        from backend.models.database import Trade
        open_count = db.query(Trade).filter(
            Trade.strategy == self.name,
            Trade.settled.is_(False),
            Trade.trading_mode == ctx.mode,
        ).count()
        max_open = int(params.get("max_open_positions", 3))
        if open_count >= max_open:
            logger.info(f"[cex_pm_leadlag] {open_count} open positions >= max {max_open}, skipping")
            return result

        # Supported assets mapping to CoinGecko IDs
        asset_map = {
            "btc": "bitcoin",
            "eth": "ethereum",
            "sol": "solana",
        }

        async with httpx.AsyncClient() as http:
            for asset_key, asset_cg_id in asset_map.items():
                try:
                    micro = await compute_crypto_microstructure(asset_cg_id)
                except Exception as e:
                    result.errors.append(f"{asset_key} microstructure fetch failed: {e}")
                    continue

                if micro is None or micro.price <= 0 or micro.momentum_1m is None:
                    continue

                momentum_norm = float(params.get("momentum_norm", 0.006))

                if abs(micro.momentum_1m) < min_momentum:
                    logger.debug(
                        f"[cex_pm_leadlag] {asset_key} momentum {abs(micro.momentum_1m):.4f} "
                        f"< min_momentum {min_momentum}"
                    )
                    continue

                # Volatility regime filter
                if micro.volatility is not None:
                    if micro.volatility < min_volatility or micro.volatility > max_volatility:
                        logger.debug(
                            f"[cex_pm_leadlag] {asset_key} volatility {micro.volatility:.4f} "
                            f"out of bounds [{min_volatility}, {max_volatility}]"
                        )
                        continue

                momentum_positive = micro.momentum_1m > 0
                direction = "up" if momentum_positive else "down"

                try:
                    all_markets = await fetch_active_crypto_markets(asset=asset_key)
                except Exception as e:
                    result.errors.append(f"{asset_key} market discovery failed: {e}")
                    continue

                candidates = await self.market_filter(all_markets)
                if not candidates:
                    logger.debug(f"[cex_pm_leadlag] {asset_key}: 0 qualifying markets from {len(all_markets)} fetched")
                    continue

                # Per-asset open positions cap
                asset_open = db.query(Trade).filter(
                    Trade.strategy == self.name,
                    Trade.settled.is_(False),
                    Trade.trading_mode == ctx.mode,
                    Trade.market_ticker.like(f"{asset_key}%"),
                ).count()
                max_per_asset = int(params.get("max_per_asset", 1))
                if asset_open >= max_per_asset:
                    logger.debug(f"[cex_pm_leadlag] {asset_key} has {asset_open} open >= max {max_per_asset}")
                    continue

                for market in candidates:
                    minutes_remaining = market.time_until_end / 60.0
                    if minutes_remaining <= 0 or minutes_remaining > max_minutes:
                        continue

                    pm_up_mid = await _fetch_pm_mid(http, market.up_token_id)
                    if pm_up_mid is None:
                        continue

                    if direction == "up":
                        target_mid = pm_up_mid
                    else:
                        target_mid = 1.0 - pm_up_mid

                    # Convert micro.momentum_1m (percentage, e.g. 0.2 for 0.2%) to decimal to align with momentum_norm (decimal, e.g. 0.006)
                    momentum_decimal = abs(micro.momentum_1m) / 100.0
                    strength = momentum_decimal / momentum_norm
                    sigmoid = 2.0 / (1.0 + math.exp(-3.0 * strength)) - 1.0
                    raw_prob = max(0.01, min(0.99, 0.5 + 0.49 * sigmoid))
                    # Cap probability at 0.75 (75%) instead of 0.65 to allow high-conviction trades to scale
                    implied_prob = max(0.40, min(0.75, raw_prob))
                    total_fees = fee_rate * 2
                    edge = (implied_prob - target_mid) - min_edge - total_fees

                    confidence = (
                        min(1.0, abs(edge + min_edge) / min_edge) if min_edge > 0 else 0.0
                    )

                    decision = "BUY" if edge > 0 else "SKIP"
                    if decision == "BUY" and params.get("debate_enabled", True):
                        try:
                            question = (
                                f"{asset_key.upper()} price {micro.price:.0f} with {abs(micro.momentum_1m):.4f} 1-min momentum. "
                                f"Will {asset_key.upper()} be {'UP' if direction == 'up' else 'DOWN'} in the next 5-minute window? "
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
                                    f"\"{asset_key}_price\":{micro.price:.0f}}}"
                                ),
                                max_rounds=2,
                            )
                            if debate_result and debate_result.confidence > 0:
                                debate_min_conf = float(
                                    params.get("debate_min_confidence", 0.55)
                                )
                                if debate_result.confidence < debate_min_conf:
                                    logger.info(
                                        "[cex_pm_leadlag] debate rejected %s for %s (confidence=%.2f < %.2f)",
                                        decision,
                                        market.slug,
                                        debate_result.confidence,
                                        debate_min_conf,
                                    )
                                    continue
                                confidence = max(confidence, debate_result.confidence)
                        except Exception:
                            logger.debug("[cex_pm_leadlag] debate validation failed, allowing trade")

                    projected_price = micro.price * (1.0 + micro.momentum_1m)

                    signal_data = {
                        "asset": asset_key,
                        "price": micro.price,
                        "momentum_1m": micro.momentum_1m,
                        "momentum_5m": micro.momentum_5m,
                        "projected_price": projected_price,
                        "pm_up_mid": pm_up_mid,
                        "target_mid": target_mid,
                        "direction": direction,
                        "edge": edge,
                        "minutes_remaining": round(minutes_remaining, 2),
                        "source": micro.source,
                        "sources": ["cex_pm_leadlag"]
                        + (
                            micro.source
                            if isinstance(micro.source, list)
                            else [micro.source]
                        ),
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
                            f"leadlag {asset_key} mom1m={micro.momentum_1m:+.4f} "
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
                        logger.exception(
                            f"Failed to record CEX-PM lead-lag decision for {asset_key}"
                        )

                    if decision == "BUY":
                        result.trades_attempted += 1
                        chosen_token = (
                            market.up_token_id
                            if direction == "up"
                            else market.down_token_id
                        )
                        entry_price = target_mid
                        size_scalar = (
                            min(1.0, (edge + min_edge) / (min_edge * 2))
                            if min_edge > 0
                            else 0.5
                        )
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
                                    f"CEX {asset_key} 1m momentum {micro.momentum_1m:+.4f} → "
                                    f"direction={direction}, PM mid {target_mid:.3f}, "
                                    f"edge {edge:+.3f}"
                                ),
                                "slug": market.slug,
                                "market_end_date": market.window_end.isoformat(),
                            }
                        )

        return result
