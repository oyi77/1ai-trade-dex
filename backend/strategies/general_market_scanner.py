"""General market scanner — finds edge across all Polymarket markets using AI analysis."""

import math
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import not_

import json

from backend.strategies.base import BaseStrategy, CycleResult, StrategyContext
from backend.config import settings

from loguru import logger


async def _fetch_web_context(question: str) -> str:
    try:
        from backend.clients.websearch import get_websearch

        client = get_websearch()
        if not client.is_enabled:
            return ""
        return await client.search_for_market(question, max_results=3)
    except Exception:
        logger.exception("Failed to fetch web context for market enrichment")
        return ""


async def _fetch_brain_context(question: str) -> str:
    """Retrieve memories from BigBrainClient; returns empty string on failure."""
    try:
        from backend.clients.bigbrain import BigBrainClient

        brain = BigBrainClient()
        results = await brain.search_context(question, limit=5)
        if not results:
            return ""
        parts = []
        for item in results[:5]:
            text = item.get("text") or item.get("content") or ""
            if text:
                parts.append(text[:200])
        return " | ".join(parts) if parts else ""
    except Exception:
        logger.exception("Failed to fetch brain context for market enrichment")
        return ""


async def _run_debate_gate(
    question: str,
    market_price: float,
    volume: float,
    category: str,
    context: str,
    data_sources: list[str] | None = None,
    db: Optional[object] = None,
) -> Optional[object]:
    """Run debate with routing (MiroFish or local); returns DebateResult or None on failure."""
    try:
        from backend.ai.debate_router import run_debate_with_routing

        if db is None:
            logger.warning(
                "[general_scanner._run_debate_gate] No database session provided, falling back to local debate"
            )
            from backend.ai.debate_engine import run_debate

            return await run_debate(
                question=question,
                market_price=market_price,
                volume=volume,
                category=category,
                context=context,
                data_sources=data_sources,
            )

        return await run_debate_with_routing(
            db=db,
            question=question,
            market_price=market_price,
            volume=volume,
            category=category,
            context=context,
            data_sources=data_sources,
        )
    except Exception as exc:
        logger.exception("Failed to run debate gate for general scanner")
        logger.warning(
            "[general_scanner._run_debate_gate] %s: %s - routing decision",
            type(exc).__name__,
            exc,
        )
        return None


def _compute_composite_confidence(
    llm_confidence: float,
    raw_edge: float,
    volume: float,
    engine_confidence: float | None = None,
    debate_confidence: float | None = None,
    data_source_count: int = 0,
) -> float:
    """Compute a composite confidence score that genuinely varies per market.

    Blends multiple independent signals:
    - LLM confidence (40% weight) — the AI's self-reported certainty
    - Edge magnitude (25% weight) — larger edges = higher conviction
    - Prediction engine confidence (15% weight) — logistic regression model
    - Volume signal (10% weight) — higher volume = more liquid/reliable
    - Data richness (10% weight) — more data sources = better informed

    When debate or prediction engine didn't run, their weight is
    redistributed proportionally to the other components.
    """
    components: list[tuple[float, float]] = []  # (score, weight)

    # 1. LLM confidence — already 0-1
    components.append((max(0.0, min(1.0, llm_confidence)), 0.40))

    # 2. Edge magnitude — map raw edge to 0-1 score
    #    0.02 edge → 0.3 score, 0.05 → 0.5, 0.10 → 0.7, 0.20+ → 0.9
    edge_score = min(1.0, 1.0 - math.exp(-20.0 * raw_edge))
    components.append((edge_score, 0.25))

    # 3. Prediction engine confidence — 0-1 if available
    if engine_confidence is not None:
        components.append((max(0.0, min(1.0, engine_confidence)), 0.15))

    # 4. Debate confidence — if debate gate fired
    if debate_confidence is not None:
        components.append((max(0.0, min(1.0, debate_confidence)), 0.10))

    # 5. Volume signal — log-scale, map to 0-1
    #    $1K → 0.3, $10K → 0.5, $100K → 0.7, $1M+ → 0.9
    vol_capped = max(1.0, volume)
    vol_score = min(1.0, math.log10(vol_capped) / 7.0)  # log10(10M)=7 → 1.0
    components.append((vol_score, 0.10))

    # 6. Data richness — more sources = better informed
    #    0 sources → 0.2, 1 → 0.4, 2 → 0.6, 3+ → 0.8
    richness_score = min(1.0, 0.2 + 0.2 * data_source_count)
    components.append((richness_score, 0.10))

    # Weighted average with normalization (handles missing components)
    total_weight = sum(w for _, w in components)
    if total_weight <= 0:
        return 0.5

    composite = sum(s * w for s, w in components) / total_weight
    return round(max(0.0, min(1.0, composite)), 4)


GAMMA_API_URL = f"{settings.GAMMA_API_URL}/markets"

SPORTS_KEYWORDS = frozenset(
    {
        "nba",
        "nfl",
        "mlb",
        "nhl",
        "epl",
        "ufc",
        "mls",
        "soccer",
        "football",
        "basketball",
        "baseball",
        "hockey",
        "tennis",
        "cricket",
        "boxing",
        "mma",
        "la liga",
        "serie a",
        "bundesliga",
        "ligue 1",
        "champions league",
        "copa",
        "rugby",
        "f1",
        "formula 1",
        "grand prix",
    }
)


class GeneralMarketScanner(BaseStrategy):
    name = "general_scanner"
    description = "AI-powered scanner across all Polymarket markets — politics, sports, crypto, events"
    category = "ai_driven"
    default_params = {
        "min_volume": 5000,
        "min_edge": settings.GENERAL_MARKET_SCANNER_MIN_EDGE,
        "max_price": settings.GENERAL_MARKET_SCANNER_MAX_PRICE,
        "min_price": settings.GENERAL_MARKET_SCANNER_MIN_PRICE,
        "max_position_size": 8.0,
        "min_position_size": 5.0,
        "scan_limit": 500,
        "categories": "politics,crypto,science,culture",
        "max_ai_calls_per_cycle": 40,
        "max_concurrent": 25,
        "min_reward_risk": settings.GENERAL_MARKET_SCANNER_MIN_REWARD_RISK,
        "max_days_to_end": 2,
        "max_low_prob_size": settings.GENERAL_MARKET_SCANNER_MAX_LOW_PROB_SIZE,
        "low_prob_threshold": settings.GENERAL_MARKET_SCANNER_LOW_PROB_THRESHOLD,
        "edge_dampening": settings.GENERAL_MARKET_SCANNER_EDGE_DAMPENING,
        "sports_edge_multiplier": settings.GENERAL_MARKET_SCANNER_SPORTS_EDGE_MULTIPLIER,
        "max_raw_edge": settings.GENERAL_MARKET_SCANNER_MAX_RAW_EDGE,
        "market_anchor_weight": settings.GENERAL_MARKET_SCANNER_MARKET_ANCHOR_WEIGHT,
        "min_ai_confidence": settings.GENERAL_MARKET_SCANNER_MIN_AI_CONFIDENCE,
        "skip_hours": [2, 4],
        "safe_harvest_enabled": True,
        "harvest_yes_ceiling": settings.GENERAL_MARKET_SCANNER_HARVEST_YES_CEILING,
        "harvest_ai_override_threshold": settings.GENERAL_MARKET_SCANNER_HARVEST_AI_OVERRIDE_THRESHOLD,
        "market_agree_enabled": True,
        "market_agree_low": settings.GENERAL_MARKET_SCANNER_MARKET_AGREE_LOW,
        "market_agree_high": settings.GENERAL_MARKET_SCANNER_MARKET_AGREE_HIGH,
        "min_expected_profit": settings.GENERAL_MARKET_SCANNER_MIN_EXPECTED_PROFIT,
        "dynamic_max_tiers": [
            (0.90, 0.20, 16.0),
            (0.85, 0.15, 12.0),
            (0.75, 0.10, 8.0),
            (0.65, 0.06, 5.0),
        ],
        "category_caps": {
            "sports": settings.GM_SCANNER_CATEGORY_CAP_SPORTS,
            "politics": settings.GM_SCANNER_CATEGORY_CAP_POLITICS,
            "crypto": settings.GM_SCANNER_CATEGORY_CAP_CRYPTO,
        },
        "low_prob_yes_cap": settings.GENERAL_MARKET_SCANNER_LOW_PROB_YES_CAP,
    }

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)

        # AI is required for this strategy to have any edge — check first to skip early
        if not getattr(ctx.settings, "AI_ENABLED", False):
            ctx.logger.info(
                "[general_scanner] AI disabled — skipping cycle (AI required for edge)"
            )
            result.errors.append("AI disabled")
            return result

        rejected_raw_edge = 0
        rejected_edge_low = 0
        rejected_rr = 0

        params = {**self.default_params, **(ctx.params or {})}
        min_volume = float(params["min_volume"])
        min_edge = float(params["min_edge"])
        max_price = float(params["max_price"])
        min_price = float(params["min_price"])
        max_position_size = float(params["max_position_size"])
        min_position_size = float(params.get("min_position_size", 0.50))
        scan_limit = int(params["scan_limit"])
        max_ai_calls_per_cycle = int(params.get("max_ai_calls_per_cycle", 40))
        max_concurrent = int(params.get("max_concurrent", 25))
        max_days_to_end = int(params.get("max_days_to_end", 30))
        max_low_prob_size = float(params.get("max_low_prob_size", 0.50))
        low_prob_threshold = float(params.get("low_prob_threshold", 0.20))
        edge_dampening = float(params.get("edge_dampening", 0.5))
        sports_edge_multiplier = float(params.get("sports_edge_multiplier", 3.0))
        max_raw_edge = float(params.get("max_raw_edge", 0.15))
        market_anchor_weight = float(params.get("market_anchor_weight", 0.45))
        safe_harvest_enabled = bool(params.get("safe_harvest_enabled", True))
        harvest_yes_ceiling = float(params.get("harvest_yes_ceiling", 0.35))
        harvest_ai_override = float(params.get("harvest_ai_override_threshold", 0.65))
        market_agree_enabled = bool(params.get("market_agree_enabled", True))
        market_agree_low = float(params.get("market_agree_low", 0.50))
        market_agree_high = float(params.get("market_agree_high", 0.65))
        allowed_categories_raw = params.get("categories", "")
        allowed_categories = {
            c.strip().lower()
            for c in str(allowed_categories_raw).split(",")
            if c.strip()
        }

        # Time-of-day filter: skip hours where historical losses cluster
        skip_hours = params.get("skip_hours", [2, 4])
        current_hour = datetime.now(timezone.utc).hour
        if current_hour in skip_hours:
            ctx.logger.info(
                f"[general_scanner] Skipping cycle — hour {current_hour} UTC in skip_hours {skip_hours}"
            )
            return result

        # Fetch top markets by volume
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    GAMMA_API_URL,
                    params={
                        "active": "true",
                        "closed": "false",
                        "limit": scan_limit,
                        "order": "volume",
                        "ascending": "false",
                    },
                )
                resp.raise_for_status()
                markets = resp.json()
        except Exception as e:
            ctx.logger.warning(f"[general_scanner] Gamma API fetch failed: {e}")
            result.errors.append(str(e))
            return result

        if not isinstance(markets, list):
            ctx.logger.warning("[general_scanner] Unexpected Gamma API response format")
            return result

        # Load AI analyzer
        try:
            from backend.ai.market_analyzer import analyze_market
        except ImportError as e:
            ctx.logger.warning(
                f"[general_scanner] AI market_analyzer not available: {e}"
            )
            result.errors.append(f"AI module unavailable: {e}")
            return result

        min_debate_edge = float(getattr(ctx.settings, "MIN_DEBATE_EDGE", 0.04))

        bankroll = 100.0
        try:
            from backend.models.database import BotState, for_update

            state = for_update(ctx.db, ctx.db.query(BotState)).first()
            if state:
                if ctx.mode == "paper":
                    bankroll = float(
                        state.paper_bankroll
                        if state.paper_bankroll is not None
                        else ctx.settings.INITIAL_BANKROLL
                    )
                elif ctx.mode == "testnet":
                    bankroll = float(
                        state.testnet_bankroll
                        if state.testnet_bankroll is not None
                        else ctx.settings.INITIAL_BANKROLL
                    )
                else:
                    bankroll = float(
                        state.bankroll
                        if state.bankroll is not None
                        else ctx.settings.INITIAL_BANKROLL
                    )
        except Exception as e:
            ctx.logger.error(f"[general_scanner] Bankroll fetch failed: {e}")

        ai_calls_this_cycle = 0
        existing_tickers: set = set()
        open_trade_count = 0
        try:
            from backend.models.database import Trade

            open_trades = (
                ctx.db.query(Trade)
                .filter(not_(Trade.settled), Trade.trading_mode == ctx.mode)
                .all()
            )
            existing_tickers = {t.market_ticker for t in open_trades if t.market_ticker}
            open_trade_count = len(open_trades)
        except Exception as e:
            ctx.logger.error(f"[general_scanner] Open trades fetch failed: {e}")

        if max_concurrent > 0 and open_trade_count >= max_concurrent:
            ctx.logger.info(
                f"[general_scanner] At max concurrent trades ({open_trade_count}/{max_concurrent}), skipping cycle"
            )
            return result

        for market in markets:
            # Volume filter
            volume = float(market.get("volume", 0) or 0)
            if volume < min_volume:
                continue

            # Category filter — skip when API returns null/empty categories
            category_raw = market.get("category") or market.get("tags") or ""
            if isinstance(category_raw, list):
                market_categories = {str(c).lower().strip() for c in category_raw if c}
            else:
                cat_str = str(category_raw).lower().strip()
                market_categories = {cat_str} if cat_str else set()

            # Only apply category filter if the market actually HAS category data
            # Gamma API often returns category=null, so pass those through to AI
            if (
                market_categories
                and allowed_categories
                and not (market_categories & allowed_categories)
            ):
                # Try substring match on question text as fallback
                question = market.get("question", "").lower()
                combined = " ".join(market_categories) + " " + question
                if not any(cat in combined for cat in allowed_categories):
                    continue

            # Extract YES price (first outcome price)
            outcome_prices_raw = market.get("outcomePrices") or []
            if isinstance(outcome_prices_raw, str):
                try:
                    outcome_prices_raw = json.loads(outcome_prices_raw)
                except Exception:
                    logger.exception("Failed to parse outcome prices JSON")
                    continue

            if not outcome_prices_raw:
                continue

            try:
                yes_price = float(outcome_prices_raw[0])
            except (TypeError, ValueError, IndexError):
                continue

            no_price = 1.0 - yes_price

            # Price range filter (both sides)
            if yes_price < min_price or yes_price > max_price:
                # Check NO side
                if no_price < min_price or no_price > max_price:
                    continue

            slug = market.get("slug") or market.get("conditionId") or ""

            # Skip markets we already have an open trade on
            if slug and slug in existing_tickers:
                continue

            # End-date filter: skip markets that have already expired or resolve too far in the future
            end_date_str = market.get("endDate") or ""
            if end_date_str:
                try:
                    end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    days_until = (end_dt - datetime.now(timezone.utc)).days
                    if days_until < 0:
                        # Market already expired - past markets should only be used for backtesting
                        continue
                    if days_until > max_days_to_end:
                        continue
                except (ValueError, TypeError):
                    pass

            # In-loop concurrent check: stop placing if we hit the limit
            trades_placed_this_cycle = result.decisions_recorded
            if (
                max_concurrent > 0
                and open_trade_count + trades_placed_this_cycle >= max_concurrent
            ):
                ctx.logger.info(
                    f"[general_scanner] Hit max concurrent during cycle ({open_trade_count + trades_placed_this_cycle}/{max_concurrent}), stopping"
                )
                break

            question = market.get("question") or market.get("title") or slug

            # ============================================================
            # DATA ENRICHMENT: Build context from available market data
            # ============================================================

            # --- 1. Gamma API top-of-book data (free, always available) ---
            best_bid = market.get("bestBid")
            best_ask = market.get("bestAsk")
            gamma_spread = market.get("spread")
            context_parts = []

            if best_bid is not None and best_ask is not None:
                try:
                    bb = float(best_bid)
                    ba = float(best_ask)
                    if ba > bb > 0:
                        spread = (
                            float(gamma_spread) if gamma_spread is not None else ba - bb
                        )
                        ob_imbalance = (
                            bb / ba - 1.0
                        ) * 10  # rough imbalance [-1,1] scale
                        context_parts.append(
                            f"ORDER_BOOK: best_bid={bb:.4f}, best_ask={ba:.4f}, "
                            f"spread={spread:.4f}, "
                            f"imbalance={ob_imbalance:+.2f}"
                        )
                except (ValueError, TypeError):
                    pass

            # --- 2. CLOB REST order book (one call per candidate, only for AI markets) ---
            clob_token_id = None
            clob_token_ids = market.get("clobTokenIds") or []
            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except Exception:
                    logger.exception(
                        "general_market_scanner: failed to process market batch"
                    )
                    clob_token_ids = []
            if clob_token_ids:
                clob_token_id = str(clob_token_ids[0])

            if clob_token_id:
                try:
                    async with httpx.AsyncClient(timeout=10.0) as clob_client:
                        book_resp = await clob_client.get(
                            f"{settings.CLOB_API_URL}/book",
                            params={"token_id": clob_token_id},
                        )
                        if book_resp.status_code == 200:
                            book_data = book_resp.json()
                            bids_raw = book_data.get("bids", [])
                            asks_raw = book_data.get("asks", [])
                            # Parse bids [[price, size], ...]
                            bids = [
                                [float(b["price"]), float(b["size"])]
                                for b in bids_raw
                                if b.get("price") and b.get("size")
                            ]
                            asks = [
                                [float(a["price"]), float(a["size"])]
                                for a in asks_raw
                                if a.get("price") and a.get("size")
                            ]
                            bid_depth = sum(s for _, s in bids)
                            ask_depth = sum(s for _, s in asks)
                            total_depth = bid_depth + ask_depth
                            imbalance = (
                                (bid_depth - ask_depth) / total_depth
                                if total_depth > 0
                                else 0.0
                            )
                            # Top-of-book
                            top_bid = bids[0][0] if bids else 0.0
                            top_ask = asks[0][0] if asks else 0.0
                            book_spread = (
                                top_ask - top_bid if top_bid and top_ask else 0.0
                            )
                            # Large orders (>5x avg size)
                            avg_bid_size = bid_depth / len(bids) if bids else 1.0
                            avg_ask_size = ask_depth / len(asks) if asks else 1.0
                            large_bids = sum(1 for _, s in bids if s > 5 * avg_bid_size)
                            large_asks = sum(1 for _, s in asks if s > 5 * avg_ask_size)
                            context_parts.append(
                                f"CLOB_ORDER_BOOK: spread={book_spread:.4f}, "
                                f"bid_depth=${bid_depth:.0f}, ask_depth=${ask_depth:.0f}, "
                                f"imbalance={imbalance:+.2f}, "
                                f"large_bids={large_bids}, large_asks={large_asks}"
                            )
                except Exception as e:
                    ctx.logger.error(f"[general_scanner] CLOB fetch failed: {e}")

            # --- 3. Whale pressure from WalletConfig (top whales per market, if available) ---
            # We skip per-market whale API calls (too slow). Whale discovery runs independently.
            # Just pass a note that whale context is available in the signal data.
            context_parts.append(
                f"MARKET_DATA: volume=${volume:,.0f}, liquidity=${float(market.get('liquidity') or 0):,.0f}"
            )

            enriched_context = " | ".join(context_parts)

            brain_context = await _fetch_brain_context(question)
            if brain_context:
                enriched_context = f"{enriched_context} | BRAIN: {brain_context}"

            web_context = await _fetch_web_context(question)
            if web_context:
                enriched_context = f"{enriched_context} | WEB: {web_context}"

            data_sources = [
                part.split(":")[0].strip().lower()
                for part in context_parts
                if ":" in part
            ]
            if brain_context:
                data_sources.append("bigbrain_memory")
            if web_context:
                data_sources.append("web_search")

            # AI analysis — enforce per-cycle call cap
            if ai_calls_this_cycle >= max_ai_calls_per_cycle:
                ctx.logger.debug(
                    f"AI call cap reached ({max_ai_calls_per_cycle}), using technical signals for remaining markets"
                )
                continue

            try:
                ai_result = await analyze_market(
                    question=question,
                    current_price=yes_price,
                    volume=volume,
                    category=next(iter(market_categories), "general"),
                    context=enriched_context,
                )
            except Exception as e:
                ctx.logger.debug(
                    f"[general_scanner] AI analysis failed for {slug}: {e}"
                )
                continue

            ai_calls_this_cycle += 1

            if not ai_result:
                continue

            llm_confidence = float(getattr(ai_result, "confidence", 0.0))
            min_ai_confidence = float(params.get("min_ai_confidence", 0.6))
            if llm_confidence < min_ai_confidence:
                ctx.logger.debug(
                    f"[general_scanner] FILTER:CONFIDENCE {slug}: conf={llm_confidence:.2f} < min={min_ai_confidence}"
                )
                continue

            ai_prob = float(ai_result.probability)
            market_price = yes_price

            # Market-anchor the AI probability: blend toward market consensus.
            raw_ai_prob = ai_prob
            ai_prob = (
                market_anchor_weight * market_price
                + (1.0 - market_anchor_weight) * raw_ai_prob
            )

            # ============================================================
            # PREDICTION ENGINE: Ensemble layer combining LLM signal with
            # quantitative features via logistic regression.
            # ============================================================
            engine_conf_value: float | None = None
            try:
                from backend.ai.prediction_engine import PredictionEngine

                vol_capped = min(max(volume, 0.0), 1000.0)
                signal_data = {
                    "edge": float(abs(raw_ai_prob - market_price)),
                    "model_probability": float(raw_ai_prob),
                    "market_probability": float(market_price),
                    "whale_pressure": 0.0,
                    "sentiment": 0.0,
                    "volume_log": math.log1p(vol_capped),
                }
                engine = PredictionEngine()
                engine_pred = engine.predict(signal_data)
                engine_prob = float(engine_pred.probability_yes)
                engine_conf_value = float(engine_pred.confidence)
                engine_weight = min(engine_conf_value, 0.4)
                ai_prob = (1.0 - engine_weight) * ai_prob + engine_weight * engine_prob
                ctx.logger.debug(
                    f"[general_scanner] PRED_ENGINE {slug}: "
                    f"engine_prob={engine_prob:.4f} engine_conf={engine_conf_value:.3f} "
                    f"blended={ai_prob:.4f}"
                )
            except Exception as e:
                ctx.logger.debug(
                    f"[general_scanner] Prediction engine failed for {slug}: {e}"
                )

            # Determine direction and edge
            if ai_prob > market_price:
                direction = "yes"
                edge = ai_prob - market_price
                entry_price = yes_price
            else:
                direction = "no"
                edge = market_price - ai_prob
                entry_price = no_price

            raw_edge = abs(raw_ai_prob - market_price)
            debate_result = None

            if raw_edge > min_debate_edge:
                debate_result = await _run_debate_gate(
                    question=question,
                    market_price=market_price,
                    volume=volume,
                    category=next(iter(market_categories), "general"),
                    context=enriched_context,
                    data_sources=data_sources,
                    db=ctx.db,
                )
                if debate_result is not None:
                    debate_prob = float(debate_result.consensus_probability)
                    debate_conf = float(debate_result.confidence)
                    ctx.logger.info(
                        f"[general_scanner] DEBATE {slug}: "
                        f"single_pass={ai_prob:.4f} debate={debate_prob:.4f} "
                        f"conf={debate_conf:.2f} rounds={debate_result.rounds_completed}"
                    )
                    ai_prob = debate_prob
                    raw_ai_prob = debate_prob
                    raw_edge = abs(raw_ai_prob - market_price)
                    if ai_prob > market_price:
                        direction = "yes"
                        edge = ai_prob - market_price
                        entry_price = yes_price
                    else:
                        direction = "no"
                        edge = market_price - ai_prob
                        entry_price = no_price
                else:
                    ctx.logger.debug(
                        f"[general_scanner] DEBATE_FALLBACK {slug}: "
                        f"debate failed, using single-pass result"
                    )

            debate_conf_value = (
                float(debate_result.confidence) if debate_result is not None else None
            )
            ai_confidence = _compute_composite_confidence(
                llm_confidence=llm_confidence,
                raw_edge=raw_edge,
                volume=volume,
                engine_confidence=engine_conf_value,
                debate_confidence=debate_conf_value,
                data_source_count=len(data_sources),
            )
            ctx.logger.debug(
                f"[general_scanner] COMPOSITE_CONF {slug}: "
                f"llm={llm_confidence:.2f} "
                f"engine={engine_conf_value} debate={debate_conf_value} "
                f"sources={len(data_sources)} → composite={ai_confidence:.4f}"
            )

            # Safe harvesting: for low-YES markets, force NO direction
            # unless the AI is VERY confident it will resolve YES.
            if safe_harvest_enabled and market_price < harvest_yes_ceiling:
                if raw_ai_prob < harvest_ai_override:
                    if direction == "yes":
                        ctx.logger.info(
                            f"[general_scanner] HARVEST: flipping {slug} from YES→NO "
                            f"(mkt={market_price:.3f} < ceiling={harvest_yes_ceiling}, "
                            f"ai_raw={raw_ai_prob:.3f} < override={harvest_ai_override})"
                        )
                        direction = "no"
                        entry_price = no_price
                        edge = market_price - ai_prob
                        if edge <= 0:
                            edge = (1.0 - market_price) * 0.05

            # Hard block: NO yes bets below 50¢ market price.
            # Research: YES on <50¢ = systematic losses (49.7% win at best in 20-40¢ range,
            # worse below 20¢). Only NO harvesting is profitable in this range.
            if direction == "yes" and market_price < 0.50:
                ctx.logger.info(
                    f"[general_scanner] FILTER:YES_BLOCK {slug}: "
                    f"market={market_price:.3f} < 0.50, blocking YES bet"
                )
                rejected_edge_low += 1
                continue

            # Market-agree filter: only trade in the direction the market leans.
            if market_agree_enabled:
                if market_price < market_agree_low and direction == "yes":
                    ctx.logger.info(
                        f"[general_scanner] FILTER:MARKET_AGREE {slug}: "
                        f"market={market_price:.3f} < {market_agree_low} but AI says YES, rejecting"
                    )
                    rejected_edge_low += 1
                    continue
                if market_price > market_agree_high and direction == "no":
                    ctx.logger.info(
                        f"[general_scanner] FILTER:MARKET_AGREE {slug}: "
                        f"market={market_price:.3f} > {market_agree_high} but AI says NO, rejecting"
                    )
                    rejected_edge_low += 1
                    continue

            if raw_edge > max_raw_edge:
                ctx.logger.info(
                    f"[general_scanner] FILTER:RAW_EDGE {slug}: raw_edge={raw_edge:.4f} > max={max_raw_edge} "
                    f"(ai_raw={raw_ai_prob:.3f}, mkt={market_price:.3f})"
                )
                rejected_raw_edge += 1
                continue

            # Dampen the anchored edge further
            dampened_edge = edge * edge_dampening

            # Sports markets are hyper-efficient; require higher edge to trade
            q_lower = question.lower() if question else ""
            cats_lower = " ".join(market_categories)
            is_sports = (
                "sports" in market_categories
                or any(kw in q_lower for kw in SPORTS_KEYWORDS)
                or any(kw in cats_lower for kw in SPORTS_KEYWORDS)
            )
            required_edge = min_edge * sports_edge_multiplier if is_sports else min_edge

            if dampened_edge < required_edge:
                ctx.logger.info(
                    f"[general_scanner] FILTER:EDGE_LOW {slug}: dampened={dampened_edge:.4f} < required={required_edge:.4f}"
                    f" (raw={raw_edge:.4f}, anchored={edge:.4f}, dampen={edge_dampening}, sports={is_sports})"
                )
                rejected_edge_low += 1
                continue

            # R:R floor filter — reject trades where potential reward is too
            # low relative to risk.  Exempt safe-harvest NO bets: their edge
            # comes from high win-rate (>80%), not high R:R.
            is_harvest_trade = (
                safe_harvest_enabled
                and direction == "no"
                and market_price < harvest_yes_ceiling
            )
            min_rr = float(params.get("min_reward_risk", 0.3))
            if entry_price > 0 and not is_harvest_trade:
                reward_risk = (1.0 / entry_price) - 1.0
                if reward_risk < min_rr:
                    ctx.logger.info(
                        f"[general_scanner] FILTER:RR_LOW {slug}: R:R={reward_risk:.2f}x < min={min_rr}x (entry={entry_price:.4f})"
                    )
                    rejected_rr += 1
                    continue

            # Kelly criterion sizing (fractional)
            kelly_fraction = ctx.settings.KELLY_FRACTION
            if entry_price > 0 and entry_price < 1:
                b = (1.0 - entry_price) / entry_price  # net odds
                q = 1.0 - ai_prob
                kelly_full = (ai_prob * b - q) / b
                kelly_size = max(0.0, kelly_full * kelly_fraction * bankroll)
            else:
                kelly_size = max_position_size

            # ============================================================
            # DYNAMIC POSITION SIZING: Scale max based on AI confidence
            # Higher confidence = larger allowed position (up to bankroll %)
            # ============================================================
            base_max = max_position_size
            dynamic_max = base_max
            tiers = params.get("dynamic_max_tiers", [])
            for conf_thresh, pct, cap in tiers:
                if ai_confidence >= conf_thresh:
                    dynamic_max = min(bankroll * pct, cap)
                    break

            ctx.logger.debug(
                f"[general_scanner] DYNAMIC_SIZE {slug}: "
                f"confidence={ai_confidence:.2f} base_max=${base_max:.2f} "
                f"dynamic_max=${dynamic_max:.2f} bankroll=${bankroll:.2f}"
            )

            size = min(dynamic_max, kelly_size)
            size = max(min_position_size, size)

            if entry_price < low_prob_threshold:
                size = min(size, max_low_prob_size)

            # --- Asymmetric risk/reward sizing adjustment ---
            # High-entry NO bets (harvest) need bigger size to generate meaningful
            # profit per trade.  Low-entry YES bets need smaller size because full
            # stake is lost on failure.
            profit_per_dollar = (1.0 / entry_price) - 1.0 if entry_price > 0 else 0
            min_profit = float(params.get("min_expected_profit", 0.10))
            if profit_per_dollar > 0:
                # Scale size up so expected profit >= min_profit (if we win)
                min_size_for_profit = min_profit / profit_per_dollar
                if size < min_size_for_profit:
                    size = min(min_size_for_profit, max_position_size)
            # For YES bets at low probability, aggressively cap size
            if direction == "yes" and entry_price < 0.50:
                size = min(size, params["low_prob_yes_cap"])

            category_caps = params.get("category_caps", {})
            for cat_key, cap in category_caps.items():
                if cat_key in market_categories or (is_sports and cat_key == "sports"):
                    size = min(size, cap)
                    break

            min_profit_filter = float(params.get("min_expected_profit", 0.10))
            if entry_price > 0:
                expected_profit = (size / entry_price) - size
                if expected_profit < min_profit_filter:
                    ctx.logger.info(
                        f"[general_scanner] FILTER:PROFIT_LOW {slug}: "
                        f"expected_profit=${expected_profit:.2f} < min=${min_profit_filter:.2f} "
                        f"(size=${size:.2f}, entry={entry_price:.4f})"
                    )
                    rejected_rr += 1
                    continue

            reasoning = getattr(ai_result, "reasoning", "") or ""

            decision = {
                "market_ticker": slug,
                "token_id": clob_token_id,
                "market_question": question,
                "direction": direction,
                "decision": "BUY",
                "entry_price": entry_price,
                "size": size,
                "suggested_size": size,
                "edge": round(dampened_edge, 4),
                "raw_edge": round(raw_edge, 4),
                "confidence": ai_confidence,
                "model_probability": ai_prob,
                "raw_ai_probability": raw_ai_prob,
                "market_probability": market_price,
                "platform": settings.DEFAULT_VENUE,
                "strategy_name": self.name,
                "volume": volume,
                "reasoning": reasoning,
                "market_end_date": end_date_str,
                "debate_transcript": (
                    debate_result.to_transcript_dict() if debate_result else None
                ),
            }

            result.decisions.append(decision)
            result.decisions_recorded += 1
            result.trades_attempted += 1

            try:
                from backend.models.database import DecisionLog

                signal_payload = dict(decision)
                signal_payload["data_sources"] = data_sources
                log_row = DecisionLog(
                    strategy=self.name,
                    market_ticker=slug[:64] if slug else "unknown",
                    decision="BUY",
                    confidence=ai_confidence,
                    signal_data=json.dumps(signal_payload),
                    reason=(
                        f"AI edge: {direction.upper()} @ {entry_price:.2%} | "
                        f"AI raw={raw_ai_prob:.2%} anchored={ai_prob:.2%} market={market_price:.2%} "
                        f"raw_edge={raw_edge:.2%} dampened={dampened_edge:.2%}"
                    ),
                )
                ctx.db.add(log_row)
            except Exception as e:
                ctx.logger.warning(f"[general_scanner] DecisionLog write failed: {e}")

            try:
                from backend.core.calibration_tracker import calibration_tracker

                calibration_tracker.record_prediction(
                    ctx.db,
                    self.name,
                    slug,
                    ai_prob,
                    direction,
                )
            except Exception as e:
                ctx.logger.debug(f"[general_scanner] Calibration record failed: {e}")

        try:
            ctx.db.commit()
        except Exception as e:
            ctx.logger.warning(f"[general_scanner] DB commit failed: {e}")
            ctx.db.rollback()

        ctx.logger.info(
            f"[general_scanner] Cycle done: {result.decisions_recorded} BUYs | "
            f"Rejected: raw_edge={rejected_raw_edge}, edge_low={rejected_edge_low}, rr_low={rejected_rr} | "
            f"AI calls={ai_calls_this_cycle}"
        )
        return result
