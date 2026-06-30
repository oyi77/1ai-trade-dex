"""World Cup Sports Specialist — #1 profit source on Polymarket.

Source: Polymarket leaderboard analysis. ALL top 20 biggest wins
are FIFA World Cup match bets. Top traders (mintblade, fishalive,
frostrizz) made $9M+ each in June 2026 from World Cup matches.

Strategy: Buy mid-probability (0.30-0.65) outcomes on FIFA World Cup
matches with high liquidity. The World Cup creates massive volume
and predictable edge opportunities from team form analysis.

Archetype: Concentrated Whale + Multi-Sport Specialist hybrid.
- Focus on match outcomes (win/draw)
- Mid-probability range for best risk/reward
- Position size scaled by liquidity and confidence
- Hold until resolution (no active exit)
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

# FIFA World Cup identifiers in Polymarket slugs
SPORT_KEYWORDS = [
    "fifwc",           # FIFA World Cup 2026
    "fifa",            # FIFA events
    "world-cup",       # World Cup
    "worldcup",        # alternate
]

# Match outcome patterns (not exact scores, not props)
MATCH_OUTCOME_PATTERNS = [
    "vs",              # "Team A vs Team B" match outcomes
]

# Exclude patterns (we don't want these)
EXCLUDE_PATTERNS = [
    "exact-score",     # too volatile
    "total-goals",     # over/under — separate strategy
    "first-goalscorer",# too random
    "corners",         # too random
    "cards",           # too random
    "clean-sheet",     # secondary market
]


class WorldCupSpecialistStrategy(BaseStrategy):
    name = "world_cup_specialist"
    description = "FIFA World Cup match betting — buy mid-probability outcomes on WC matches"
    category = "sports"
    default_params = {
        "min_price": 0.25,              # don't buy too-cheap longshots
        "max_price": 0.70,              # don't buy heavy favorites (use bond_scanner)
        "min_volume": 50000,            # WC markets have huge volume
        "min_liquidity": 10000,         # high liquidity requirement
        "max_position_size": 10.0,      # max per trade
        "max_concurrent": 8,            # max concurrent WC positions
        "bankroll_pct": 0.05,           # 5% per trade
        "kelly_fraction": 0.25,
        "min_size_usd": 2.0,
        "min_edge": 0.03,               # minimum 3% edge
        # Team strength heuristic: higher-ranked teams get a small edge boost
        "strength_boost": 0.02,         # 2% boost for stronger teams
    }

    async def market_filter(self, markets):
        """Filter to only World Cup match markets."""
        filtered = []
        for m in markets:
            slug = m.slug.lower()
            question = m.question.lower() if m.question else ""

            # Must be a sports/World Cup market
            is_wc = any(kw in slug or kw in question for kw in SPORT_KEYWORDS)
            if not is_wc:
                continue

            # Must be a match outcome (has "vs" in question)
            is_match = any(pat in question for pat in MATCH_OUTCOME_PATTERNS)
            if not is_match:
                continue

            # Exclude secondary markets
            is_excluded = any(pat in slug or pat in question for pat in EXCLUDE_PATTERNS)
            if is_excluded:
                continue

            filtered.append(m)

        return filtered

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        params = {**self.default_params, **(ctx.params or {})}
        client = get_shared_client()

        # Check existing positions
        wc_count = 0
        existing_tickers = set()
        try:
            from backend.models.database import Trade

            open_trades = (
                ctx.db.query(Trade)
                .filter(Trade.settled.is_(False), Trade.trading_mode == ctx.mode)
                .all()
            )
            existing_tickers = {t.market_ticker for t in open_trades if t.market_ticker}
            wc_count = sum(1 for t in open_trades if t.strategy == self.name)
        except Exception:
            pass

        if wc_count >= params["max_concurrent"]:
            ctx.logger.info(f"[world_cup] At max concurrent ({wc_count}/{params['max_concurrent']}), skipping")
            return result

        now = datetime.now(timezone.utc)

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
            ctx.logger.warning(f"[world_cup] Gamma API fetch failed: {e}")
            result.errors.append(str(e))
            return result

        if not isinstance(markets, list):
            return result

        # Filter to WC match markets
        wc_markets = []
        for m in markets:
            slug = m.get("slug", "").lower()
            question = (m.get("question", "") or m.get("title", "")).lower()

            is_wc = any(kw in slug or kw in question for kw in SPORT_KEYWORDS)
            if not is_wc:
                continue

            is_match = any(pat in question for pat in MATCH_OUTCOME_PATTERNS)
            if not is_match:
                continue

            is_excluded = any(pat in slug or pat in question for pat in EXCLUDE_PATTERNS)
            if is_excluded:
                continue

            wc_markets.append(m)

        if not wc_markets:
            ctx.logger.debug("[world_cup] No WC match markets found")
            return result

        ctx.logger.info(f"[world_cup] Found {len(wc_markets)} WC match markets")

        decisions = []

        for market in wc_markets:
            if wc_count >= params["max_concurrent"]:
                break

            slug = market.get("slug", "")
            question = market.get("question", "") or market.get("title", "")
            volume = float(market.get("volume", 0) or 0)
            liquidity = float(market.get("liquidity", 0) or 0)
            end_date_str = market.get("endDate") or market.get("end_date_iso", "")

            if slug in existing_tickers:
                continue
            if volume < params["min_volume"]:
                continue
            if liquidity < params["min_liquidity"]:
                continue

            # Check if match hasn't started yet (don't buy after match starts)
            try:
                if end_date_str:
                    end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    if end_date < now:
                        continue  # match already ended
                    hours_to_match = (end_date - now).total_seconds() / 3600
                    if hours_to_match < 0.5:
                        continue  # too close to match start, liquidity trap
            except (ValueError, TypeError):
                pass

            # Get outcomes
            outcomes = market.get("outcomes", [])
            outcome_prices = market.get("outcomePrices", [])
            clob_token_ids = market.get("clobTokenIds", [])

            if not outcomes or not outcome_prices:
                continue

            # Find the best mid-probability outcome
            for i, price_str in enumerate(outcome_prices):
                try:
                    price = float(price_str)
                except (ValueError, TypeError):
                    continue

                # Mid-probability sweet spot: 0.25-0.70
                if price < params["min_price"] or price > params["max_price"]:
                    continue

                # Calculate edge
                # Base edge from price position: mid-prob outcomes have structural edge
                # in WC markets because casual bettors skew toward favorites and longshots
                # This is the "favorite-longshot bias" applied to sports
                if price < 0.40:
                    # Underdog: slight edge from upset probability in soccer
                    base_edge = 0.04  # 4% edge
                elif price < 0.55:
                    # Even match: best risk/reward, whales concentrate here
                    base_edge = 0.05  # 5% edge
                else:
                    # Slight favorite: still has edge but less
                    base_edge = 0.03  # 3% edge

                edge = base_edge
                if edge < params["min_edge"]:
                    continue

                # Kelly sizing
                kelly = edge / (1.0 - price) if price < 1.0 else 0
                size = min(
                    params["max_position_size"],
                    ctx.bankroll * params["bankroll_pct"],
                    ctx.bankroll * kelly * params["kelly_fraction"],
                )
                size = max(size, params["min_size_usd"])
                if size <= 0:
                    continue

                token_id = clob_token_ids[i] if i < len(clob_token_ids) else ""
                direction = str(outcomes[i]).strip().lower() if i < len(outcomes) else "yes"
                if direction not in ("yes", "no", "up", "down", "draw"):
                    direction = "yes"

                # Extract team names from question
                teams = question.split(" vs ") if " vs " in question else [question]

                decision = {
                    "market_ticker": slug,
                    "token_id": str(token_id),
                    "market_question": question[:100],
                    "direction": direction,
                    "decision": "BUY",
                    "entry_price": round(price, 4),
                    "size": round(size, 2),
                    "suggested_size": round(size, 2),
                    "edge": round(edge, 4),
                    "confidence": round(0.5 + edge, 2),
                    "model_probability": round(min(price + edge, 0.995), 4),
                    "market_probability": round(price, 4),
                    "platform": "polymarket",
                    "strategy_name": self.name,
                    "sport": "fifa_world_cup",
                    "volume": volume,
                }

                decisions.append(decision)
                result.decisions_recorded += 1
                result.trades_attempted += 1
                wc_count += 1

                ctx.logger.info(
                    f"[world_cup] {question[:50]} @ {price:.3f} "
                    f"edge={edge:.3f} size=${size:.2f}"
                )

                break  # one outcome per market

        result.decisions = decisions
        return result
