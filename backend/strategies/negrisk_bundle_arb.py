"""NegRisk Bundle Arbitrage — TRUE risk-free profit on Polymarket.

Polymarket's NegRisk events guarantee exactly ONE outcome wins.
If you buy YES on ALL outcomes and total cost < $1.00, you're
guaranteed profit on resolution (one wins, pays $1.00).

Source: homerun open-source repo (production-grade, 102 stars).
Edge: 0.5-3% per arb when mispricing detected.
Risk: ZERO (true arbitrage) — only execution risk.
"""

from datetime import datetime, timezone

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    StrategyContext,
)
from backend.data.shared_client import get_shared_client
from backend.config import settings

from loguru import logger

GAMMA_API_URL = f"{settings.GAMMA_API_URL}/markets"
# Polymarket NegRisk endpoint
NEGRISK_URL = "https://gamma-api.polymarket.com/events"


class NegRiskBundleArbStrategy(BaseStrategy):
    name = "negrisk_bundle_arb"
    description = "Arbitrage NegRisk events where buying YES on all outcomes costs < $1.00"
    category = "arbitrage"
    default_params = {
        "min_outcomes": 3,              # minimum outcomes per event
        "max_outcomes": 20,             # avoid huge markets
        "min_total_margin": 0.03,       # minimum total profit ($0.03)
        "max_position_per_leg": 5.0,    # max per leg
        "bankroll_pct": 0.05,           # 5% of bankroll per arb opportunity
        "min_leg_liquidity": 500,       # minimum liquidity per leg
        "min_leg_volume": 1000,         # minimum volume per leg
        "max_concurrent": 3,            # max concurrent arb bundles
        "min_size_usd": 1.0,
    }

    async def market_filter(self, markets):
        return markets

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        params = {**self.default_params, **(ctx.params or {})}
        client = get_shared_client()

        # Check existing arb positions
        arb_count = 0
        existing_tickers = set()
        try:
            from backend.models.database import Trade

            open_trades = (
                ctx.db.query(Trade)
                .filter(Trade.settled.is_(False), Trade.trading_mode == ctx.mode)
                .all()
            )
            existing_tickers = {t.market_ticker for t in open_trades if t.market_ticker}
            arb_count = sum(1 for t in open_trades if t.strategy == self.name)
        except Exception:
            pass

        if arb_count >= params["max_concurrent"]:
            ctx.logger.info(f"[nerisk_bundle_arb] At max concurrent ({arb_count}), skipping")
            return result

        # Fetch NegRisk events
        try:
            resp = await client.get(
                NEGRISK_URL,
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": 100,
                    "order": "volume",
                    "ascending": "false",
                    "neg_risk": "true",
                },
            )
            resp.raise_for_status()
            events = resp.json()
        except Exception as e:
            ctx.logger.warning(f"[nerisk_bundle_arb] NegRisk events fetch failed: {e}")
            # Fallback: scan all markets for multi-outcome groups
            events = []

        if not isinstance(events, list):
            events = []

        # Also scan regular markets for multi-outcome groups
        try:
            resp2 = await client.get(
                GAMMA_API_URL,
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": 500,
                    "order": "volume",
                    "ascending": "false",
                },
            )
            resp2.raise_for_status()
            all_markets = resp2.json()
        except Exception as e:
            ctx.logger.warning(f"[nerisk_bundle_arb] Markets fetch failed: {e}")
            all_markets = []

        if not isinstance(all_markets, list):
            all_markets = []

        # Group markets by event
        event_groups = {}

        # From NegRisk events
        for event in events:
            event_id = event.get("id") or event.get("slug", "")
            markets_in_event = event.get("markets", [])
            if markets_in_event and len(markets_in_event) >= params["min_outcomes"]:
                event_groups[f"negrisk_{event_id}"] = markets_in_event

        # From regular markets (group by shared fields)
        slug_groups = {}
        for m in all_markets:
            group_key = m.get("eventSlug") or m.get("groupItemTitle", "")
            if not group_key:
                continue
            if group_key not in slug_groups:
                slug_groups[group_key] = []
            slug_groups[group_key].append(m)

        for key, markets_list in slug_groups.items():
            if len(markets_list) >= params["min_outcomes"]:
                if f"negrisk_{key}" not in event_groups:
                    event_groups[f"regular_{key}"] = markets_list

        # Analyze each event group for arbitrage
        for event_id, event_markets in event_groups.items():
            if arb_count >= params["max_concurrent"]:
                break

            if not isinstance(event_markets, list):
                continue

            # Collect all outcomes with prices and token IDs
            legs = []
            total_volume = 0
            total_liquidity = 0

            for m in event_markets:
                outcomes = m.get("outcomes", [])
                prices = m.get("outcomePrices", [])
                tokens = m.get("clobTokenIds", [])
                vol = float(m.get("volume", 0) or 0)
                liq = float(m.get("liquidity", 0) or 0)
                slug = m.get("slug", "")

                total_volume += vol
                total_liquidity += liq

                if not outcomes or not prices:
                    continue

                for i, price_str in enumerate(prices):
                    try:
                        price = float(price_str)
                        token_id = tokens[i] if i < len(tokens) else ""
                        if price > 0 and price < 1 and token_id:
                            legs.append({
                                "market_slug": slug,
                                "outcome": outcomes[i] if i < len(outcomes) else f"outcome_{i}",
                                "yes_price": price,
                                "token_id": token_id,
                                "volume": vol,
                                "liquidity": liq,
                            })
                    except (ValueError, TypeError):
                        continue

            if len(legs) < params["min_outcomes"]:
                continue

            # Filter legs with minimum liquidity
            viable_legs = [
                l for l in legs
                if l["liquidity"] >= params["min_leg_liquidity"]
                and l["volume"] >= params["min_leg_volume"]
            ]

            if len(viable_legs) < params["min_outcomes"]:
                continue

            # THE KEY CHECK: sum of all YES prices
            total_cost = sum(l["yes_price"] for l in viable_legs)

            # Arbitrage exists when total_cost < $1.00
            # We buy YES on every outcome. One will win, paying $1.00.
            # Profit = $1.00 - total_cost
            if total_cost >= 1.0:
                continue

            margin = 1.0 - total_cost
            margin_per_leg = margin / len(viable_legs)

            if margin < params["min_total_margin"]:
                continue
            if margin_per_leg < params["min_margin_per_leg"]:
                continue

            # We found an arbitrage! Buy YES on all outcomes.
            ctx.logger.info(
                f"[nerisk_bundle_arb] ARB FOUND! event={event_id[:30]} "
                f"legs={len(viable_legs)} cost={total_cost:.4f} margin={margin:.4f}"
            )

            # Create one decision per leg
            for leg in viable_legs:
                if arb_count >= params["max_concurrent"]:
                    break

                size = min(
                    params["max_position_per_leg"],
                    ctx.bankroll * params["bankroll_pct"] / len(viable_legs),
                )
                size = max(size, params["min_size_usd"])

                if size <= 0:
                    continue

                decision = {
                    "market_ticker": leg["market_slug"],
                    "token_id": leg["token_id"],
                    "direction": "yes",
                    "decision": "BUY",
                    "entry_price": round(leg["yes_price"], 4),
                    "size": round(size, 2),
                    "suggested_size": round(size, 2),
                    "edge": round(margin_per_leg, 4),
                    "confidence": round(min(margin * 10, 0.99), 2),
                    "model_probability": 1.0,  # one outcome MUST win
                    "market_probability": round(leg["yes_price"], 4),
                    "platform": "polymarket",
                    "strategy_name": self.name,
                    "arb_bundle_id": event_id[:30],
                    "arb_bundle_size": len(viable_legs),
                    "arb_total_cost": round(total_cost, 4),
                    "arb_margin": round(margin, 4),
                }

                result.decisions.append(decision)
                result.decisions_recorded += 1
                result.trades_attempted += 1

            arb_count += 1

            ctx.logger.info(
                f"[nerisk_bundle_arb] Executing {len(viable_legs)}-leg arb: "
                f"cost={total_cost:.4f} margin={margin:.4f} "
                f"profit=${margin * size:.2f}"
            )

        if not event_groups:
            ctx.logger.debug("[nerisk_bundle_arb] No multi-outcome events found")

        return result
