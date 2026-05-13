"""
Line Movement Detector Strategy.

Detects sharp price movements (5%+ in 1 hour) that indicate informed money
or breaking news affecting a market. Sharp line movement often precedes
further price continuation or creates value opportunities.

Edge Hypothesis:
When a market moves 5%+ quickly, something significant happened. Either:
1. Informed traders know something (follow the move)
2. Market overreacted (fade the move if fundamentals unchanged)

We use web search to determine which scenario applies.
"""

import json
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from backend.strategies.base import (
    BaseStrategy,
    StrategyContext,
    CycleResult,
    MarketInfo,
)
from backend.core.decisions import record_decision_standalone
from backend.config import settings
from backend.ai.probability_utils import clamp_probability

from loguru import logger
def _cfg(name, default):
    return getattr(settings, name, default)

GAMMA_EVENTS_URL = f"{settings.GAMMA_API_URL}/events"


@dataclass
class LineMovement:
    ticker: str
    question: str
    current_price: float
    price_1h_ago: float
    price_change_pct: float
    volume_24h: float
    condition_id: str
    token_id: Optional[str] = None


class LineMovementDetectorStrategy(BaseStrategy):
    """Detects and analyzes sharp market line movements."""

    name = "line_movement_detector"
    description = "Detect sharp price movements (5%+ in 1 hour) and research cause"
    category = "edge_discovery"
    default_params = {
        "min_price_change_pct": settings.LINE_MOVE_MIN_PRICE_CHANGE_PCT,
        "min_volume_24h": settings.LINE_MOVE_MIN_VOLUME_24H,
        "min_liquidity": settings.LINE_MOVE_MIN_LIQUIDITY,
        "lookback_hours": settings.LINE_MOVE_LOOKBACK_HOURS,
        "max_markets_per_cycle": settings.GENERAL_MARKET_SCANNER_MAX_MARKETS_PER_CYCLE,
        "web_search_enabled": settings.LINE_MOVE_WEB_SEARCH_ENABLED,
        "min_confidence_to_signal": settings.LINE_MOVE_MIN_CONFIDENCE_TO_SIGNAL,
    }

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        params = self.default_params
        return [
            m
            for m in markets
            if m.volume >= params["min_volume_24h"]
            and m.liquidity >= params["min_liquidity"]
        ]

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(
            decisions_recorded=0,
            trades_attempted=0,
            trades_placed=0,
        )

        params = {**self.default_params, **(ctx.params or {})}

        try:
            movements = await self._detect_line_movements(params)

            if not movements:
                logger.debug(f"[{self.name}] No significant line movements detected")
                return result

            logger.info(
                f"[{self.name}] Found {len(movements)} markets with sharp movement"
            )

            for movement in movements[: params["max_markets_per_cycle"]]:
                try:
                    signal = await self._analyze_movement(movement, params, ctx)
                    if signal:
                        result.decisions_recorded += 1
                        result.trades_attempted += 1
                        result.decisions.append(signal)
                except Exception as e:
                    logger.warning(
                        f"[{self.name}] Error analyzing {movement.ticker}: {e}"
                    )
                    result.errors.append(str(e))

        except Exception as e:
            result.errors.append(str(e))
            logger.error(f"[{self.name}] Error in run_cycle: {e}")

        return result

    async def _detect_line_movements(self, params: dict) -> list[LineMovement]:
        movements = []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    GAMMA_EVENTS_URL,
                    params={
                        "active": "true",
                        "closed": "false",
                        "limit": 100,
                        "order": "volume24hr",
                        "ascending": "false",
                    },
                )
                resp.raise_for_status()
                events = resp.json()

                for event in events:
                    for market in event.get("markets", []):
                        movement = self._check_market_movement(market, params)
                        if movement:
                            movements.append(movement)

        except Exception as e:
            logger.warning(f"[{self.name}] Failed to fetch events: {e}")

        movements.sort(key=lambda m: abs(m.price_change_pct), reverse=True)
        return movements

    def _check_market_movement(
        self, market: dict, params: dict
    ) -> Optional[LineMovement]:
        try:
            raw_outcomes = market.get("outcomePrices")
            if not raw_outcomes:
                return None

            if isinstance(raw_outcomes, str):
                try:
                    prices = [float(p) for p in json.loads(raw_outcomes) if p]
                except (json.JSONDecodeError, ValueError):
                    prices = [
                        float(p)
                        for p in raw_outcomes.strip("[]").split(",")
                        if p.strip()
                    ]
            elif isinstance(raw_outcomes, list):
                prices = [float(p) for p in raw_outcomes if p is not None]
            else:
                return None

            if not prices:
                return None

            current_price = prices[0]

            one_day_pct = market.get("oneDayPriceChange")
            if one_day_pct is not None:
                try:
                    price_change_pct = float(one_day_pct) * 100
                except (ValueError, TypeError):
                    price_change_pct = 0.0
            else:
                price_history = market.get("priceHistory")
                if price_history and isinstance(price_history, list) and price_history:
                    now = time.time()
                    lookback_seconds = params["lookback_hours"] * 3600
                    target_time = now - lookback_seconds

                    price_1h_ago = None
                    for point in reversed(price_history):
                        ts = point.get("t", 0)
                        if ts <= target_time:
                            price_1h_ago = point.get("p", current_price)
                            break

                    if price_1h_ago is None:
                        price_1h_ago = price_history[0].get("p", current_price)

                    if price_1h_ago == 0:
                        return None

                    price_change_pct = (
                        (current_price - price_1h_ago) / price_1h_ago
                    ) * 100
                else:
                    return None

            if abs(price_change_pct) < params["min_price_change_pct"]:
                return None

            volume_24h = float(market.get("volume24hr", 0) or 0)
            if volume_24h < params["min_volume_24h"]:
                return None

            raw_tokens = market.get("clobTokenIds", "")
            token_id = None
            if isinstance(raw_tokens, list):
                token_id = str(raw_tokens[0]) if raw_tokens else None
            elif isinstance(raw_tokens, str) and raw_tokens:
                try:
                    parsed = json.loads(raw_tokens)
                    token_id = str(parsed[0]) if parsed else None
                except (json.JSONDecodeError, IndexError):
                    tokens = raw_tokens.strip("[]").split(",")
                    token_id = tokens[0].strip().strip('"') if tokens else None

            price_1h_ago = (
                current_price / (1 + price_change_pct / 100)
                if price_change_pct != 0
                else current_price
            )

            return LineMovement(
                ticker=market.get("slug", market.get("question", "")[:50]),
                question=market.get("question", ""),
                current_price=current_price,
                price_1h_ago=price_1h_ago,
                price_change_pct=price_change_pct,
                volume_24h=volume_24h,
                condition_id=market.get("conditionId", ""),
                token_id=token_id,
            )

        except Exception as e:
            logger.debug(f"[{self.name}] Error parsing market: {e}")
            return None

    async def _analyze_movement(
        self, movement: LineMovement, params: dict, ctx: StrategyContext
    ) -> Optional[dict]:
        direction = "up" if movement.price_change_pct > 0 else "down"
        news_context = ""

        if params.get("web_search_enabled", True):
            try:
                from backend.clients.websearch import get_websearch

                ws = get_websearch()
                news_context = await ws.search_for_market(
                    movement.question, max_results=3
                )
            except Exception as e:
                logger.debug(f"[{self.name}] Web search failed: {e}")

        confidence = self._calculate_confidence(movement, news_context)

        if confidence < params["min_confidence_to_signal"]:
            record_decision_standalone(
                self.name,
                movement.ticker,
                "SKIP",
                confidence=confidence,
                signal_data={
                    "price_change_pct": movement.price_change_pct,
                    "direction": direction,
                    "volume_24h": movement.volume_24h,
                    "has_news": bool(news_context),
                    "sources": ["line_movement_detector", "tavily"],
                },
                reason=f"Confidence {confidence:.2f} below threshold {params['min_confidence_to_signal']}",
            )
            return None

        action = "BUY"
        side = "yes" if direction == "up" else "no"
        raw_entry_price = (
            movement.current_price
            if direction == "up"
            else round(1.0 - movement.current_price, 4)
        )
        entry_price = round(clamp_probability(float(raw_entry_price)), 4)

        record_decision_standalone(
            self.name,
            movement.ticker,
            action,
            confidence=confidence,
            signal_data={
                "price_change_pct": movement.price_change_pct,
                "direction": direction,
                "current_price": clamp_probability(float(movement.current_price)),
                "price_1h_ago": movement.price_1h_ago,
                "volume_24h": movement.volume_24h,
                "news_context": news_context[:500] if news_context else "",
                "condition_id": movement.condition_id,
                "token_id": movement.token_id,
                "sources": ["line_movement_detector", "tavily", "polymarket_gamma"],
            },
            reason=f"Sharp {direction} move: {movement.price_change_pct:+.1f}% in 1h, vol=${movement.volume_24h:,.0f}",
        )

        logger.info(
            f"[{self.name}] SIGNAL: {movement.ticker} moved {movement.price_change_pct:+.1f}% "
            f"(${movement.current_price:.2f} from ${movement.price_1h_ago:.2f}), "
            f"confidence={confidence:.2f}"
        )

        if confidence >= 0.75 and ctx.settings.TELEGRAM_HIGH_CONFIDENCE_ALERTS:
            from backend.bot.notifier import notify_high_confidence_signal

            notify_high_confidence_signal(
                strategy=self.name,
                market_title=movement.question[:80],
                direction=side,
                confidence=confidence,
                edge=abs(movement.price_change_pct) / 100,
                reasoning=f"Sharp {direction} move: {movement.price_change_pct:+.1f}% in 1h. Vol: ${movement.volume_24h:,.0f}",
                market_url=f"{settings.POLYMARKET_BASE_URL}/event/{movement.ticker}"
                if movement.ticker
                else "",
            )

        # Size: scale with edge (price_change_pct) and volume confidence.
        # Stronger moves + higher volume → larger position.
        move_magnitude = abs(movement.price_change_pct)
        base_size = min(move_magnitude * _cfg("LINE_MOVE_SIZE_PER_PCT", 5.0), _cfg("LINE_MOVE_MAX_SIGNAL_SIZE", 100.0))
        # Volume boost: scale up to 2x for high-volume moves
        vol_factor = min(2.0, max(0.5, movement.volume_24h / _cfg("LINE_MOVE_VOL_SCALE_DENOM", 50000.0)))
        size = round(base_size * vol_factor * confidence, 2)

        return {
            "decision": action,
            "market_ticker": movement.ticker,
            "direction": side,
            "confidence": confidence,
            "edge": abs(movement.price_change_pct) / 100,
            "entry_price": entry_price,
            "model_probability": confidence,
            "market_probability": clamp_probability(float(movement.current_price)),
            "size": size,
            "platform": settings.DEFAULT_VENUE,
            "strategy_name": self.name,
            "token_id": movement.token_id,
            "condition_id": movement.condition_id,
            "reasoning": f"Line moved {movement.price_change_pct:+.1f}% in 1h",
            "news_context": news_context[:200] if news_context else "",
        }

    def _calculate_confidence(self, movement: LineMovement, news_context: str) -> float:
        base_confidence = _cfg("LINE_MOVE_BASE_CONFIDENCE", 0.5)

        move_size = abs(movement.price_change_pct)
        if move_size >= _cfg("LINE_MOVE_HUGE_THRESHOLD", 15.0):
            base_confidence += _cfg("LINE_MOVE_HUGE_BOOST", 0.2)
        elif move_size >= _cfg("LINE_MOVE_LARGE_THRESHOLD", 10.0):
            base_confidence += _cfg("LINE_MOVE_LARGE_BOOST", 0.15)
        elif move_size >= _cfg("LINE_MOVE_MEDIUM_THRESHOLD", 7.0):
            base_confidence += _cfg("LINE_MOVE_MEDIUM_BOOST", 0.1)
        else:
            base_confidence += _cfg("LINE_MOVE_SMALL_BOOST", 0.05)

        if movement.volume_24h >= _cfg("LINE_MOVE_HIGH_VOL_THRESHOLD", 100000.0):
            base_confidence += _cfg("LINE_MOVE_HIGH_VOL_BOOST", 0.1)
        elif movement.volume_24h >= _cfg("LINE_MOVE_MED_VOL_THRESHOLD", 50000.0):
            base_confidence += _cfg("LINE_MOVE_MED_VOL_BOOST", 0.05)

        if news_context:
            base_confidence += _cfg("LINE_MOVE_NEWS_BOOST", 0.1)

        return min(base_confidence, _cfg("LINE_MOVE_MAX_CONFIDENCE", 0.95))
