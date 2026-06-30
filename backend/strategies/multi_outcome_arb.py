"""Multi-Outcome Arbitrage Strategy.

Academic basis: Hanson (2003) "Combinatorial Information Market Design".
In multi-outcome markets (elections, tournaments), all YES prices must sum to 1.0.
When sum > 1.02 or < 0.98, there's a risk-free arbitrage opportunity.

Edge: 0.5-3% per arb, more common in less liquid multi-outcome markets.
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


class MultiOutcomeArbStrategy(BaseStrategy):
    name = "multi_outcome_arb"
    description = "Arbitrage mispriced multi-outcome markets where prices don't sum to 1.0"
    category = "arbitrage"
    default_params = {
        "min_outcomes": 3,            # only multi-outcome markets
        "max_outcomes": 20,           # avoid huge markets with thin liquidity
        "min_volume": 5000,           # minimum total volume
        "min_liquidity": 2000,        # minimum liquidity
        "overpriced_threshold": 1.02, # sum > this = sell overpriced
        "underpriced_threshold": 0.98,# sum < this = buy underpriced
        "max_position_size": 5.0,
        "max_concurrent": 5,
        "bankroll_pct": 0.03,         # 3% per leg
        "min_size_usd": 1.0,
        "min_edge": 0.005,            # minimum 0.5% edge
    }

    async def market_filter(self, markets):
        return markets

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        params = {**self.default_params, **(ctx.params or {})}
        client = get_shared_client()

        # Check existing positions
        existing_tickers = set()
        arb_count = 0
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
            ctx.logger.info(f"[multi_outcome_arb] At max concurrent ({arb_count}), skipping")
            return result

        # Fetch active markets
        try:
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
            markets = resp.json()
        except Exception as e:
            ctx.logger.warning(f"[multi_outcome_arb] Gamma API fetch failed: {e}")
            result.errors.append(str(e))
            return result

        if not isinstance(markets, list):
            return result

        # Group markets by event (multi-outcome markets share an event)
        # Polymarket structures multi-outcome markets as separate markets per outcome
        # We need to find groups of markets that represent the same event
        event_groups = {}
        for market in markets:
            # Multi-outcome markets have a groupItemTitle or are linked by event
            group_id = market.get("groupItemTitle") or market.get("eventSlug", "")
            if not group_id:
                # Try to detect multi-outcome by question pattern
                question = market.get("question", "")
                # Skip binary markets
                outcomes = market.get("outcomes", [])
                if len(outcomes) <= 2:
                    continue
                group_id = market.get("slug", "")

            if group_id not in event_groups:
                event_groups[group_id] = []
            event_groups[group_id].append(market)

        # Analyze each event group
        for event_id, event_markets in event_groups.items():
            if arb_count >= params["max_concurrent"]:
                break

            # Only process groups with multiple outcomes
            if len(event_markets) < params["min_outcomes"]:
                continue
            if len(event_markets) > params["max_outcomes"]:
                continue

            # Calculate sum of YES prices across all outcomes
            total_volume = 0
            total_liquidity = 0
            outcome_data = []

            for m in event_markets:
                outcomes = m.get("outcomes", [])
                prices = m.get("outcomePrices", [])
                tokens = m.get("clobTokenIds", [])
                vol = float(m.get("volume", 0) or 0)
                liq = float(m.get("liquidity", 0) or 0)
                total_volume += vol
                total_liquidity += liq

                if not outcomes or not prices:
                    continue

                for i, price_str in enumerate(prices):
                    try:
                        price = float(price_str)
                        token_id = tokens[i] if i < len(tokens) else ""
                        outcome_data.append({
                            "market_slug": m.get("slug", ""),
                            "outcome": outcomes[i] if i < len(outcomes) else f"outcome_{i}",
                            "price": price,
                            "token_id": token_id,
                            "volume": vol,
                        })
                    except (ValueError, TypeError):
                        continue

            if len(outcome_data) < params["min_outcomes"]:
                continue
            if total_volume < params["min_volume"]:
                continue
            if total_liquidity < params["min_liquidity"]:
                continue

            # Sum of all YES prices
            price_sum = sum(o["price"] for o in outcome_data)

            # Check for arbitrage
            if price_sum > params["overpriced_threshold"]:
                # OVERPRICED: sum > 1.0 → sell the most overpriced outcome
                # Edge = price_sum - 1.0 (guaranteed profit if we sell all)
                edge = price_sum - 1.0
                if edge < params["min_edge"]:
                    continue

                # Find the most overpriced outcome to sell
                overpriced = max(outcome_data, key=lambda o: o["price"])

                size = min(
                    params["max_position_size"],
                    ctx.bankroll * params["bankroll_pct"],
                )
                size = max(size, params["min_size_usd"])

                if size <= 0:
                    continue

                # We SELL the overpriced outcome (buy NO)
                decision = {
                    "market_ticker": overpriced["market_slug"],
                    "token_id": overpriced["token_id"],
                    "direction": "no",  # sell = buy NO
                    "decision": "BUY",
                    "entry_price": round(1.0 - overpriced["price"], 4),  # NO price
                    "size": round(size, 2),
                    "suggested_size": round(size, 2),
                    "edge": round(edge, 4),
                    "confidence": round(min(edge * 10, 0.95), 2),
                    "model_probability": round(1.0 - overpriced["price"] + edge, 4),
                    "market_probability": round(overpriced["price"], 4),
                    "platform": "polymarket",
                    "strategy_name": self.name,
                }

                result.decisions.append(decision)
                result.decisions_recorded += 1
                result.trades_attempted += 1
                arb_count += 1

                ctx.logger.info(
                    f"[multi_outcome_arb] OVERPRICED: sum={price_sum:.3f} "
                    f"selling {overpriced['outcome']}@{overpriced['price']:.3f} "
                    f"edge={edge:.3f} size=${size:.2f}"
                )

            elif price_sum < params["underpriced_threshold"]:
                # UNDERPRICED: sum < 1.0 → buy the most underpriced outcome
                edge = 1.0 - price_sum
                if edge < params["min_edge"]:
                    continue

                underpriced = min(outcome_data, key=lambda o: o["price"])

                size = min(
                    params["max_position_size"],
                    ctx.bankroll * params["bankroll_pct"],
                )
                size = max(size, params["min_size_usd"])

                if size <= 0:
                    continue

                decision = {
                    "market_ticker": underpriced["market_slug"],
                    "token_id": underpriced["token_id"],
                    "direction": "yes",
                    "decision": "BUY",
                    "entry_price": round(underpriced["price"], 4),
                    "size": round(size, 2),
                    "suggested_size": round(size, 2),
                    "edge": round(edge, 4),
                    "confidence": round(min(edge * 10, 0.95), 2),
                    "model_probability": round(underpriced["price"] + edge, 4),
                    "market_probability": round(underpriced["price"], 4),
                    "platform": "polymarket",
                    "strategy_name": self.name,
                }

                result.decisions.append(decision)
                result.decisions_recorded += 1
                result.trades_attempted += 1
                arb_count += 1

                ctx.logger.info(
                    f"[multi_outcome_arb] UNDERPRICED: sum={price_sum:.3f} "
                    f"buying {underpriced['outcome']}@{underpriced['price']:.3f} "
                    f"edge={edge:.3f} size=${size:.2f}"
                )

        return result
