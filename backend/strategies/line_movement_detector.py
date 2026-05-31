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
from backend.ai.debate_router import run_debate_with_routing

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
    liquidity: float = 0.0


class LineMovementDetectorStrategy(BaseStrategy):
    """Detects and analyzes sharp market line movements."""

    name = "line_movement_detector"
    description = "Detect sharp price movements (5%+ in 1 hour) and research cause"
    category = "edge_discovery"
    # ── Risk management constants ──
    # Polymarket round-trip fee ~2% (1% taker buy + 1% taker sell).
    # Net R:R after fees: (8%-2%) vs (5%+2%) → 6% net win vs 7% net loss → R:R ~0.86:1
    # With trailing stop at +6%, winners that run get breakeven floor → effective R:R > 1:1
    AUTO_SELL_PROFIT_TARGET_PCT: float = 0.08   # 8% take-profit (net ~6% after fees)
    AUTO_SELL_STOP_LOSS_PCT: float = 0.05       # 5% stop-loss
    AUTO_SELL_MAX_HOLD_SECONDS: int = 600        # 10 min (was 5 — give moves room)
    # Trailing stop: once position is +6% in profit, move stop to breakeven
    TRAILING_STOP_ACTIVATION_PCT: float = 0.06
    # Max risk per trade as fraction of bankroll
    MAX_RISK_PER_TRADE_PCT: float = 0.02  # 2% of bankroll
    # Kelly defaults for sizing (historical: 79% WR, small wins)
    HISTORICAL_WIN_RATE: float = 0.79
    HISTORICAL_AVG_WIN: float = 1.0     # normalized
    HISTORICAL_AVG_LOSS: float = 1.0    # normalized
    KELLY_FRACTION: float = 0.25        # quarter-Kelly

    default_params = {
        "min_price_change_pct": settings.LINE_MOVE_MIN_PRICE_CHANGE_PCT,
        "min_volume_24h": settings.LINE_MOVE_MIN_VOLUME_24H,
        "min_liquidity": settings.LINE_MOVE_MIN_LIQUIDITY,
        "lookback_hours": settings.LINE_MOVE_LOOKBACK_HOURS,
        "max_markets_per_cycle": settings.GENERAL_MARKET_SCANNER_MAX_MARKETS_PER_CYCLE,
        "web_search_enabled": settings.LINE_MOVE_WEB_SEARCH_ENABLED,
        "min_confidence_to_signal": settings.LINE_MOVE_MIN_CONFIDENCE_TO_SIGNAL,
        "max_spread_pct": 0.05,
        "min_imbalance_ratio": -0.6,
        "min_top_size": 5.0,
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
            # ── Pre-settlement auto-sell: check existing open positions ──
            try:
                from backend.core.auto_sell import (
                    check_strategy_positions_for_auto_sell,
                )

                sell_results = await check_strategy_positions_for_auto_sell(
                    strategy_name=self.name,
                    clob_client=ctx.clob,
                    profit_target_pct=self.AUTO_SELL_PROFIT_TARGET_PCT,
                    stop_loss_pct=self.AUTO_SELL_STOP_LOSS_PCT,
                    max_hold_seconds=self.AUTO_SELL_MAX_HOLD_SECONDS,
                    trailing_stop_activation_pct=self.TRAILING_STOP_ACTIVATION_PCT,
                )
                if sell_results:
                    logger.info(
                        "[{}] Auto-sell: {} positions sold",
                        self.name,
                        len(sell_results),
                    )
            except Exception as exc:
                logger.debug("[{}] Auto-sell check skipped: {}", self.name, exc)

            movements = await self._detect_line_movements(params)

            if not movements:
                logger.debug(f"[{self.name}] No significant line movements detected")
                return result

            logger.info(
                f"[{self.name}] Found {len(movements)} markets with sharp movement"
            )

            # Parallelize market analysis — debate + websearch per market is I/O-bound,
            # running sequentially wastes 10× the wall-clock time and congests the event loop.
            import asyncio
            sem = asyncio.Semaphore(3)  # cap concurrent LLM calls to avoid rate limits

            async def _analyze_one(mv):
                async with sem:
                    try:
                        return await self._analyze_movement(mv, params, ctx)
                    except Exception as e:
                        logger.warning(f"[{self.name}] Error analyzing {mv.ticker}: {e}")
                        return None

            tasks = [_analyze_one(m) for m in movements[: params["max_markets_per_cycle"]]]
            signals = await asyncio.gather(*tasks)
            for signal in signals:
                if signal:
                    result.decisions_recorded += 1
                    result.trades_attempted += 1
                    result.decisions.append(signal)

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
                liquidity=float(market.get("liquidity", 0) or 0),
            )

        except Exception as e:
            logger.debug(f"[{self.name}] Error parsing market: {e}")
            return None

    async def _analyze_movement(
        self, movement: LineMovement, params: dict, ctx: StrategyContext
    ) -> Optional[dict]:
        direction = "up" if movement.price_change_pct > 0 else "down"

        # 1. Dynamically scaled thresholds check based on price move magnitude
        move_magnitude = abs(movement.price_change_pct)
        scaling_factor = max(1.0, move_magnitude / 5.0)
        dynamic_min_volume = params.get("min_volume_24h", 5000) * scaling_factor
        dynamic_min_liquidity = params.get("min_liquidity", 5000) * scaling_factor

        if movement.volume_24h < dynamic_min_volume:
            logger.info(
                f"[{self.name}] skipping {movement.ticker} — volume ${movement.volume_24h:,.0f} below dynamic threshold ${dynamic_min_volume:,.0f}"
            )
            return None

        if movement.liquidity < dynamic_min_liquidity:
            logger.info(
                f"[{self.name}] skipping {movement.ticker} — liquidity ${movement.liquidity:,.0f} below dynamic threshold ${dynamic_min_liquidity:,.0f}"
            )
            return None

        # 2. Fetch CLOB order book for spread and kinetics checks
        top_bid = 0.0
        top_ask = 0.0
        book_spread = 0.0
        imbalance = 0.0
        top_bid_size = 0.0
        top_ask_size = 0.0

        if movement.token_id:
            try:
                async with httpx.AsyncClient(timeout=5.0) as clob_client:
                    book_resp = await clob_client.get(
                        f"{settings.CLOB_API_URL}/book",
                        params={"token_id": movement.token_id},
                    )
                    if book_resp.status_code == 200:
                        book_data = book_resp.json()
                        bids = [
                            [float(b["price"]), float(b["size"])]
                            for b in book_data.get("bids", [])
                            if b.get("price") and b.get("size")
                        ]
                        asks = [
                            [float(a["price"]), float(a["size"])]
                            for a in book_data.get("asks", [])
                            if a.get("price") and a.get("size")
                        ]
                        bid_depth = sum(s for _, s in bids)
                        ask_depth = sum(s for _, s in asks)
                        total_depth = bid_depth + ask_depth
                        if total_depth > 0:
                            imbalance = (bid_depth - ask_depth) / total_depth

                        top_bid = bids[0][0] if bids else 0.0
                        top_ask = asks[0][0] if asks else 0.0
                        top_bid_size = bids[0][1] if bids else 0.0
                        top_ask_size = asks[0][1] if asks else 0.0
                        if top_bid and top_ask:
                            book_spread = top_ask - top_bid
            except Exception as e:
                logger.warning(f"[{self.name}] CLOB order book fetch failed for {movement.ticker}: {e}")

        # 3. Volatility spread validation
        if top_bid > 0 and top_ask > 0:
            mid_price = (top_bid + top_ask) / 2.0
            max_spread_pct = params.get("max_spread_pct", 0.05)
            if mid_price > 0 and (book_spread / mid_price) > max_spread_pct:
                logger.info(
                    f"[{self.name}] skipping {movement.ticker} — spread {(book_spread/mid_price):.1%} wider than max {max_spread_pct:.1%}"
                )
                return None

            # 4. Kinetics check: top sizes stability (no rapid flickering of tiny sizes)
            min_top_size = params.get("min_top_size", 5.0)
            if top_bid_size < min_top_size or top_ask_size < min_top_size:
                logger.info(
                    f"[{self.name}] skipping {movement.ticker} — order book unstable/flickering (bid_size={top_bid_size:.1f}, ask_size={top_ask_size:.1f} < {min_top_size})"
                )
                return None

            # 5. Kinetics check: imbalance ratio (no buying if opposite liquidity dries up)
            target_imbalance = imbalance if direction == "up" else -imbalance
            min_imbalance = params.get("min_imbalance_ratio", -0.6)
            if target_imbalance < min_imbalance:
                logger.info(
                    f"[{self.name}] skipping {movement.ticker} — buy-side liquidity drying up (imbalance={target_imbalance:.2f} < {min_imbalance})"
                )
                return None

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

        # ── Debate gate: validate signal via MiroFish/local debate ──
        debate_enabled = params.get("debate_enabled", True)
        if debate_enabled:
            try:
                debate_result = await run_debate_with_routing(
                    db=getattr(ctx, "db", None),
                    question=movement.question or movement.ticker,
                    market_price=movement.current_price,
                    context=(
                        f"Price move: {movement.price_change_pct:+.1f}% in 1h. "
                        f"Volume 24h: ${movement.volume_24h:,.0f}. "
                        f"Liquidity: ${movement.liquidity:,.0f}. "
                        f"Web news context: {news_context[:1000] if news_context else 'No breaking news found.'}"
                    ),
                    max_rounds=2,
                )
                if debate_result and debate_result.confidence > 0:
                    if debate_result.confidence < 0.55:
                        logger.info(
                            "[%s] debate rejected BUY for %s (confidence=%.2f)",
                            self.name,
                            movement.ticker,
                            debate_result.confidence,
                        )
                        return None
                    confidence = max(confidence, debate_result.confidence)
            except Exception:
                logger.warning(
                    "[%s] debate validation failed for %s, allowing trade",
                    self.name,
                    movement.ticker,
                )

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
            from backend.bot.notification.registry import registry

            await registry.send_to(
                "telegram", "high_confidence_signal",
                f"{self.name}|{movement.question[:80]}|{side}|{confidence}|{abs(movement.price_change_pct) / 100}|"
                f"Sharp {direction} move: {movement.price_change_pct:+.1f}% in 1h. Vol: ${movement.volume_24h:,.0f}|"
                f"{settings.POLYMARKET_BASE_URL}/event/{movement.ticker if movement.ticker else ''}",
            )

        # ── Position sizing: Kelly-based with 2% bankroll risk cap ──
        from backend.core.risk.position_sizer import kelly_criterion
        kelly_frac = kelly_criterion(
            win_rate=self.HISTORICAL_WIN_RATE,
            avg_win=self.HISTORICAL_AVG_WIN,
            avg_loss=self.HISTORICAL_AVG_LOSS,
            kelly_fraction=self.KELLY_FRACTION,
        )
        # Scale Kelly by confidence (lower confidence → smaller size)
        kelly_size = ctx.bankroll * kelly_frac * min(confidence, 1.0)

        # Edge-scaled component: bigger moves warrant bigger positions
        move_magnitude = abs(movement.price_change_pct)
        edge_factor = min(2.0, max(0.5, move_magnitude / 5.0))
        # Volume boost: scale up to 1.5x for high-volume moves
        vol_factor = min(
            1.5,
            max(0.5, movement.volume_24h / _cfg("LINE_MOVE_VOL_SCALE_DENOM", 50000.0)),
        )
        size = round(kelly_size * edge_factor * vol_factor, 2)

        # Hard floor: 2% of bankroll max risk per trade
        max_risk = ctx.bankroll * self.MAX_RISK_PER_TRADE_PCT
        size = min(size, max_risk)
        # Also respect global position fraction cap
        max_position_frac = getattr(ctx.settings, "MAX_POSITION_FRACTION", 0.30)
        size = min(size, ctx.bankroll * max_position_frac)
        # Ensure positive
        size = max(size, 0.0)

        return {
            "decision": action,
            "market_ticker": movement.ticker,
            "direction": side,
            "confidence": confidence,
            "edge": abs(movement.price_change_pct) / 100,
            "entry_price": entry_price,
            "model_probability": clamp_probability(float(movement.current_price)),
            "market_probability": clamp_probability(float(movement.current_price)),
            "size": size,
            "platform": settings.DEFAULT_VENUE,
            "strategy_name": self.name,
            "token_id": movement.token_id,
            "condition_id": movement.condition_id,
            "stop_loss_pct": self.AUTO_SELL_STOP_LOSS_PCT,
            "profit_target_pct": self.AUTO_SELL_PROFIT_TARGET_PCT,
            "trailing_stop_activation_pct": self.TRAILING_STOP_ACTIVATION_PCT,
            "max_risk_per_trade_pct": self.MAX_RISK_PER_TRADE_PCT,
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
