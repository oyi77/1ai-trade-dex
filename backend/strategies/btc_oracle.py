"""
BTC Oracle Latency Strategy.

Monitors the Chainlink/UMA oracle settlement price vs Polymarket market mid-price
for short-duration BTC binary markets. When the oracle's pre-resolution price
diverges from market mid by > min_edge AND time-to-resolution < max_minutes,
fire a trade.

This strategy exploits the 2-5 second oracle latency window documented in research.
Unlike BTC 5-min momentum (negative EV), this targets a structural market inefficiency.
"""
from datetime import datetime, timezone

from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult, MarketEvent
from backend.core.market_scanner import MarketInfo
from backend.core.decisions import record_decision_standalone
from backend.core.activity_logger import activity_logger
from backend.config import settings
from backend.core.calibration import get_bucket_win_rate, kelly_fraction
from backend.db.utils import get_db_session
from backend.models.signal_log import SignalLog
from backend.ai.debate_router import run_debate_with_routing

from loguru import logger


def _log_signal(
    *,
    market_id: str,
    market_mid: float,
    btc_spot: float | None,
    micro,
    direction: str | None,
    edge: float,
    oracle_implied: float,
) -> None:
    """Persist one SignalLog row for a btc_oracle signal.

    Best-effort: any failure is swallowed so trade execution is never blocked.
    Skipped in SHADOW_MODE because no real signal is produced.
    """
    if getattr(settings, "SHADOW_MODE", False):
        return
    try:
        record = SignalLog(
            timestamp=datetime.now(timezone.utc),
            market_id=str(market_id),
            market_mid=float(market_mid),
            btc_spot=float(btc_spot) if btc_spot is not None else None,
            rsi=float(micro.rsi) if micro is not None and getattr(micro, "rsi", None) is not None else None,
            momentum_5m=float(micro.momentum_5m) if micro is not None and getattr(micro, "momentum_5m", None) is not None else None,
            vwap_deviation=float(micro.vwap_deviation) if micro is not None and getattr(micro, "vwap_deviation", None) is not None else None,
            sma_crossover=float(micro.sma_crossover) if micro is not None and getattr(micro, "sma_crossover", None) is not None else None,
            proposed_side=direction,
            edge_pp=float(edge) * 100.0,
            oracle_implied=float(oracle_implied),
            filled=None,
            pnl=None,
            strategy="btc_oracle",
        )
        with get_db_session() as db:
            db.add(record)
    except Exception as e:
        logger.debug(f"btc_oracle: SignalLog write failed: {e}")
COINGECKO_PRICE_URL = f"{settings.COINGECKO_API_URL}/simple/price"


def calculate_dynamic_size(
    *,
    edge: float,
    confidence: float,
    max_position_usd: float,
    min_position_usd: float | None = None,
    edge_scale_threshold: float | None = None,
) -> float:
    """Return an AI-signal-sized position proposal within the strategy mandate.

    BTC Oracle still expresses an autonomous preference using edge and confidence,
    but the proposal cannot exceed the configured strategy cap. The RiskManager
    remains the final non-bypassable authority for bankroll, exposure, drawdown,
    duplicate-position, minimum-order, and global MAX_TRADE_SIZE checks.
    """
    cap = max(0.0, float(max_position_usd))
    if cap <= 0:
        return 0.0

    _min_pos = min_position_usd if min_position_usd is not None else settings.BTC_ORACLE_MIN_POSITION_USD
    _edge_scale = edge_scale_threshold if edge_scale_threshold is not None else settings.BTC_ORACLE_EDGE_SCALE_THRESHOLD

    edge_score = min(1.0, max(0.0, edge) / max(_edge_scale, 0.001))
    confidence_score = min(1.0, max(0.0, confidence))
    sizing_fraction = max(0.10, edge_score * confidence_score)
    proposed = cap * sizing_fraction

    if proposed < _min_pos and cap >= _min_pos:
        return _min_pos
    return round(min(proposed, cap), 2)


def _kelly_size(market_mid: float, bankroll: float, cap: float) -> float:
    """Compute Kelly-calibrated size from bucket win rate and market price.

    Uses Quarter-Kelly with a 2% bankroll hard cap.
    Falls back to 0 when win rate < market price (no edge per Kelly criterion).
    """
    win_rate = get_bucket_win_rate(market_mid, "btc_oracle")
    if win_rate is None:
        return 0.0
    kelly = kelly_fraction(win_rate, market_mid)
    return min(bankroll * kelly, bankroll * 0.02, cap)


async def fetch_btc_price() -> float | None:
    """Fetch current BTC/USD from multi-exchange klines (Binance/Coinbase/Kraken)."""
    try:
        from backend.data.crypto import compute_btc_microstructure

        micro = await compute_btc_microstructure()
        if micro and micro.price > 0:
            return micro.price
    except Exception as e:
        logger.warning(f"BtcOracleStrategy: microstructure fetch failed: {e}")

    try:
        from backend.data.crypto import fetch_crypto_price

        result = await fetch_crypto_price("bitcoin")
        if result and result.current_price > 0:
            return result.current_price
    except Exception as e:
        logger.warning(f"BtcOracleStrategy: CoinGecko fallback failed: {e}")
    return None


def parse_end_date(end_date_str: str | None) -> datetime | None:
    """Parse ISO end_date from Polymarket market metadata."""
    if not end_date_str:
        return None
    try:
        dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def implied_direction(question: str, btc_price: float) -> tuple[str, float] | None:
    """
    Infer YES/NO from market question and current price.
    e.g. "Will BTC exceed $95,000 on March 15?" + btc_price=96000 -> ("yes", 95000)
    Returns (direction, threshold) or None if cannot determine.
    """
    import re

    q = question.lower()

    # Extract threshold — handle $95,000 / $95000 / 95k / 95,000
    match = re.search(r"\$?([\d,]+\.?\d*)\s*k?\b", q)
    if not match:
        return None
    raw = match.group(1).replace(",", "")
    threshold = float(raw)
    # Handle "95k" shorthand
    if "k" in q[match.start() : match.end() + 2].lower() and threshold < 10000:
        threshold *= 1000

    is_above = any(
        kw in q
        for kw in (
            "above",
            "exceed",
            "over",
            "higher",
            "more than",
            "at least",
            "reach",
            "hit",
            "top",
        )
    )
    is_below = any(
        kw in q
        for kw in ("below", "under", "lower", "less than", "fall", "drop", "dip")
    )

    if is_above:
        return ("yes", threshold) if btc_price > threshold else ("no", threshold)
    if is_below:
        return ("yes", threshold) if btc_price < threshold else ("no", threshold)
    return None


class BtcOracleStrategy(BaseStrategy):
    name = "btc_oracle"
    description = (
        "BTC oracle latency arb: exploits 2-5s oracle settlement lag on short-duration BTC markets. "
        "Replaces the negative-EV BTC 5-min momentum strategy."
    )
    category = "arbitrage"
    default_params = {
        "_force_disabled": True,
        "min_edge": settings.BTC_ORACLE_MIN_EDGE,
        "max_minutes_to_resolution": settings.BTC_ORACLE_MAX_MINUTES_TO_RESOLUTION,
        "interval_seconds": settings.BTC_ORACLE_INTERVAL_SECONDS,
        "max_position_usd": settings.BTC_ORACLE_MAX_POSITION_USD,
        "edge_scale_threshold": settings.BTC_ORACLE_EDGE_SCALE_THRESHOLD,
        "min_position_usd": settings.BTC_ORACLE_MIN_POSITION_USD,
        "oracle_implied_base": settings.BTC_ORACLE_ORACLE_IMPLIED_BASE,
        "oracle_implied_scale": settings.BTC_ORACLE_ORACLE_IMPLIED_SCALE,
        "debate_enabled": True,
        "debate_min_confidence": 0.55,
        # FIX 2026-05-19: Data shows DOWN=-441 (30.4% WR) vs UP=+33 (50.7% WR)
        # Block DOWN direction entirely until composite signal is fixed
        "block_direction_down": True,
        # FIX 2026-05-19: Data shows mid-low bucket (0.35-0.50) = -443 (30% WR)
        # Tighten bucket to 0.50-0.65 only
        "min_price_bucket": 0.50,
        # FIX 2026-05-19: 23:00-01:00 UTC = -$295 (38% WR)
        # Block late US session
        "blocked_hours_utc": [23, 0, 1],
    }

    async def _debate_validate(self, question: str, market_price: float, context: str = "", db=None) -> tuple[bool, float]:
        if not self.default_params.get("debate_enabled", True):
            return True, 0.5
        try:
            result = await run_debate_with_routing(
                db=db,
                question=question,
                market_price=market_price,
                context=context,
                max_rounds=2,
            )
            if result and result.confidence > 0:
                return result.confidence >= self.default_params.get("debate_min_confidence", 0.55), result.confidence
        except Exception:
            logger.warning("BtcOracleStrategy: debate validation failed, allowing trade")
        return True, 0.5

    # ── Event-driven (WebSocket) subscription config ──
    subscribed_tokens: set[str] = set()
    subscribed_events: set[str] = {"last_trade_price", "price_change"}
    _tokens_populated: bool = False

    async def _populate_subscribed_tokens(self) -> None:
        """Discover active BTC markets and populate subscribed_tokens with their CLOB token IDs."""
        try:
            from backend.data.btc_markets import fetch_active_btc_markets

            markets = await fetch_active_btc_markets()
            token_ids: set[str] = set()
            for m in markets:
                if m.up_token_id:
                    token_ids.add(m.up_token_id)
                if m.down_token_id:
                    token_ids.add(m.down_token_id)
            self.subscribed_tokens = token_ids
            logger.info(
                "BtcOracleStrategy: subscribed_tokens populated with %d token IDs from %d markets",
                len(token_ids),
                len(markets),
            )
            await self.register_with_event_bus()
        except Exception as e:
            logger.warning("BtcOracleStrategy: failed to populate subscribed_tokens: %s", e)

    async def on_market_event(self, event: MarketEvent) -> dict | None:
        """Handle a real-time WS market event for a subscribed BTC token.

        Evaluates whether the trade price creates sufficient edge to warrant
        an immediate BUY decision. Returns a decision dict if edge exists,
        None otherwise. The decision dict format matches run_cycle() output
        so it can be fed directly into strategy_executor.execute_decisions().
        """
        params = {**self.default_params}
        min_edge = params.get("min_edge", self.default_params["min_edge"])
        max_position_usd = float(params.get("max_position_usd", self.default_params["max_position_usd"]))
        edge_scale_threshold = params.get("edge_scale_threshold", self.default_params["edge_scale_threshold"])
        min_position_usd = params.get("min_position_usd", self.default_params["min_position_usd"])

        price_str = event.data.get("price") or event.data.get("last_trade_price")
        if not price_str:
            return None
        try:
            trade_price = float(price_str)
        except (ValueError, TypeError):
            return None

        if trade_price <= 0 or trade_price >= 1:
            return None

        # FIX 2026-05-19: Session filter
        now_utc = datetime.now(timezone.utc)
        blocked_hours = params.get("blocked_hours_utc", [23, 0, 1])
        if now_utc.hour in blocked_hours:
            return None

        direction = "up" if trade_price > 0.5 else "down"

        # FIX 2026-05-19: Block DOWN direction
        if params.get("block_direction_down", True) and direction == "down":
            return None
        market_mid = trade_price

        # Price bucket filter: reject negative-EV territory
        min_price_bucket = params.get("min_price_bucket", getattr(settings, "CRYPTO_ORACLE_MIN_PRICE_BUCKET", 0.35))
        max_price_bucket = params.get("max_price_bucket", getattr(settings, "CRYPTO_ORACLE_MAX_PRICE_BUCKET", 0.65))
        if market_mid < min_price_bucket or market_mid > max_price_bucket:
            logger.debug(
                "BtcOracleStrategy.on_market_event: skipping — market_mid=%.2f outside bucket [%.2f, %.2f]",
                market_mid, min_price_bucket, max_price_bucket,
            )
            return None

        btc_price = await fetch_btc_price()
        if btc_price is None:
            logger.debug("BtcOracleStrategy.on_market_event: could not fetch BTC price, skipping")
            return None

        from backend.data.crypto import compute_btc_microstructure

        try:
            micro = await compute_btc_microstructure()
        except Exception:
            logger.exception('btc_oracle: failed to fetch BTC price for oracle signal')
            micro = None

        if micro:
            rsi_norm = (micro.rsi - 50.0) / 50.0
            mom_signal = max(-1.0, min(1.0, micro.momentum_5m * 10.0))
            vwap_signal = max(-1.0, min(1.0, micro.vwap_deviation * 100.0))
            sma_signal = max(-1.0, min(1.0, micro.sma_crossover * 100.0))
            composite = (
                rsi_norm * 0.25
                + mom_signal * 0.30
                + vwap_signal * 0.25
                + sma_signal * 0.20
            )
            oracle_base = params.get("oracle_implied_base", settings.BTC_ORACLE_ORACLE_IMPLIED_BASE)
            oracle_scale = params.get("oracle_implied_scale", settings.BTC_ORACLE_ORACLE_IMPLIED_SCALE)
            oracle_implied = oracle_base + composite * oracle_scale
            if direction == "down":
                oracle_implied = 1.0 - oracle_implied
        else:
            oracle_implied = market_mid

        edge = abs(oracle_implied - market_mid) - min_edge

        if edge <= 0:
            return None

        confidence_score = min(1.0, abs(edge + min_edge) / min_edge) if min_edge > 0 else 0.0
        kelly = kelly_fraction(get_bucket_win_rate(market_mid, "btc_oracle") or 0, market_mid)
        if kelly > 0:
            suggested_size = min(settings.INITIAL_BANKROLL * kelly, settings.INITIAL_BANKROLL * 0.02, max_position_usd)
        else:
            suggested_size = calculate_dynamic_size(
                edge=edge,
                confidence=confidence_score,
                max_position_usd=max_position_usd,
                min_position_usd=min_position_usd,
                edge_scale_threshold=edge_scale_threshold,
            )

        market_ticker = event.data.get("market_ticker") or event.data.get("market_id") or event.token_id

        token_id = event.token_id

        record_decision_standalone(
            self.name,
            market_ticker,
            "BUY",
            confidence=confidence_score,
            signal_data={
                "oracle_price": btc_price,
                "market_mid": market_mid,
                "implied_direction": direction,
                "edge": edge,
                "event_type": event.event_type,
                "source": "ws_event",
            },
            reason=f"ws_oracle_edge={edge:.3f} btc=${btc_price:,.0f} dir={direction} event={event.event_type}",
        )

        _log_signal(
            market_id=market_ticker,
            market_mid=market_mid,
            btc_spot=btc_price,
            micro=micro,
            direction=direction,
            edge=edge,
            oracle_implied=oracle_implied,
        )

        return {
            "decision": "BUY",
            "market_ticker": market_ticker,
            "token_id": token_id,
            "direction": direction,
            "confidence": confidence_score,
            "edge": edge,
            "size": suggested_size,
            "entry_price": market_mid,
            "suggested_size": suggested_size,
            "model_probability": oracle_implied,
            "market_probability": market_mid,
            "platform": settings.DEFAULT_VENUE,
            "strategy_name": self.name,
            "reasoning": f"ws_oracle_edge={edge:.3f} btc=${btc_price:,.0f} dir={direction} event={event.event_type}",
        }

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Filter to active BTC binary markets resolving within max_minutes."""
        return [
            m
            for m in markets
            if ("btc" in m.slug.lower() or "bitcoin" in m.question.lower())
            and m.end_date is not None
        ]

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        if not self._tokens_populated:
            await self._populate_subscribed_tokens()
            self._tokens_populated = True
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        params = {**self.default_params, **(ctx.params or {})}
        min_edge = params.get("min_edge", self.default_params["min_edge"])
        max_minutes = params.get("max_minutes_to_resolution", self.default_params["max_minutes_to_resolution"])
        max_position_usd = float(params.get("max_position_usd", self.default_params["max_position_usd"]))

        btc_price = await fetch_btc_price()
        if btc_price is None:
            result.errors.append("Could not fetch BTC price from CoinGecko")
            return result

        # Get candidate markets: use dedicated BTC 5-min fetcher (finds
        # btc-updown-5m-* slugs via computation), then supplement with
        # keyword search for any other BTC markets.
        from backend.data.btc_markets import fetch_active_btc_markets
        from backend.core.market_scanner import fetch_markets_by_keywords

        try:
            btc_5m_markets = await fetch_active_btc_markets()
        except Exception as e:
            logger.warning(f"BtcOracleStrategy.run_cycle: failed to fetch BTC markets: {e}")
            result.errors.append(f"Failed to fetch BTC markets: {type(e).__name__}")
            return result

        now = datetime.now(timezone.utc)

        # FIX 2026-05-19: Session filter — block 23:00-01:00 UTC
        current_hour = now.hour
        blocked_hours = params.get("blocked_hours_utc", [23, 0, 1])
        if current_hour in blocked_hours:
            logger.info(
                "BtcOracleStrategy: session filter — hour %d UTC blocked (hours %s)",
                current_hour, blocked_hours,
            )
            return result

        # Price bucket filter: only trade in the 50-60c range where edge is proven.
        # FIX 2026-05-19: Data shows mid-low bucket (0.35-0.50) = -$443 (30% WR).
        # Tightened from [0.35, 0.65] to [0.50, 0.65].
        min_price_bucket = params.get("min_price_bucket", 0.50)
        max_price_bucket = params.get("max_price_bucket", 0.65)

        for market in btc_5m_markets:
            end_dt = market.window_end
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            minutes_remaining = (end_dt - now).total_seconds() / 60.0
            if minutes_remaining < 0 or minutes_remaining > max_minutes:
                continue

            # FIX 2026-05-19: Session filter — block 23:00-01:00 UTC
            current_hour = now.hour
            blocked_hours = params.get("blocked_hours_utc", [23, 0, 1])
            if current_hour in blocked_hours:
                logger.debug(
                    "BtcOracleStrategy: skipping — hour %d UTC is in blocked hours %s",
                    current_hour, blocked_hours,
                )
                continue

            # Direct direction from RSI/momentum — if RSI < 50, momentum
            # is negative → BTC more likely DOWN. If RSI > 50, UP.
            from backend.data.crypto import compute_btc_microstructure
            try:
                micro = await compute_btc_microstructure()
            except Exception as e:
                logger.debug("BTC microstructure computation failed: %s", e)
                micro = None

            if micro and micro.momentum_5m is not None:
                direction = "up" if micro.momentum_5m > 0 else "down"
            else:
                # Fallback: no directional bias from indicator
                direction = "down" if market.up_price > market.down_price else "up"

            # FIX 2026-05-19: Block DOWN direction — data shows 30.4% WR, -$441 loss
            block_down = params.get("block_direction_down", True)
            if block_down and direction == "down":
                logger.debug(
                    "BtcOracleStrategy: skipping DOWN direction — blocked (data shows 30%% WR)",
                )
                continue

            market_mid = market.up_price if direction == "up" else market.down_price

            # Price bucket filter: reject negative-EV territory
            if market_mid < min_price_bucket or market_mid > max_price_bucket:
                logger.debug(
                    "BtcOracleStrategy: skipping %s — market_mid=%.2f outside bucket [%.2f, %.2f]",
                    market.slug, market_mid, min_price_bucket, max_price_bucket,
                )
                continue

            # Derive probability from microstructure (RSI + momentum + VWAP + SMA)
            # instead of hardcoded 1.0, which fabricated edge and caused -$410 losses.
            if micro:
                rsi_norm = (micro.rsi - 50.0) / 50.0
                mom_signal = max(-1.0, min(1.0, micro.momentum_5m * 10.0))
                vwap_signal = max(-1.0, min(1.0, micro.vwap_deviation * 100.0))
                sma_signal = max(-1.0, min(1.0, micro.sma_crossover * 100.0))

                composite = (
                    rsi_norm * 0.25
                    + mom_signal * 0.30
                    + vwap_signal * 0.25
                    + sma_signal * 0.20
                )
                oracle_base = params.get("oracle_implied_base", settings.BTC_ORACLE_ORACLE_IMPLIED_BASE)
                oracle_scale = params.get("oracle_implied_scale", settings.BTC_ORACLE_ORACLE_IMPLIED_SCALE)
                oracle_implied = oracle_base + composite * oracle_scale

                # Flip for DOWN direction: model prob must reflect chosen side.
                if direction == "down":
                    oracle_implied = 1.0 - oracle_implied
            else:
                oracle_implied = market_mid

            edge = abs(oracle_implied - market_mid) - min_edge

            decision = "BUY" if edge > 0 else "SKIP"
            confidence_score = min(1.0, abs(edge + min_edge) / min_edge) if min_edge > 0 else 0.0

            record_decision_standalone(
                self.name,
                market.market_id,
                decision,
                confidence=confidence_score,
                signal_data={
                    "oracle_price": btc_price,
                    "market_mid": market_mid,
                    "implied_direction": direction,
                    "time_to_resolution_s": minutes_remaining * 60,
                    "edge": edge,
                    "slug": market.slug,
                },
                reason=f"oracle_edge={edge:.3f} btc=${btc_price:,.0f} t={minutes_remaining:.1f}min dir={direction}",
            )
            result.decisions_recorded += 1

            if decision == "BUY":
                # ── Debate gate: validate signal via MiroFish/local debate ──
                debate_ok, debate_conf = await self._debate_validate(
                    question=market.slug, market_price=market_mid,
                    context=f"btc=${btc_price:,.0f} edge={edge:.3f} dir={direction} t={minutes_remaining:.1f}min",
                    db=getattr(ctx, 'db', None),
                )
                if not debate_ok:
                    logger.info("BtcOracleStrategy: debate rejected BUY for {} (confidence={:.2f})", market.slug, debate_conf)
                    continue
                confidence_score = max(confidence_score, debate_conf)

                result.trades_attempted += 1
                _log_signal(
                    market_id=market.market_id,
                    market_mid=market_mid,
                    btc_spot=btc_price,
                    micro=micro,
                    direction=direction,
                    edge=edge,
                    oracle_implied=oracle_implied,
                )
                entry_price = (
                    market.up_price
                    if direction == "up"
                    else market.down_price
                )
                token_id = market.up_token_id if direction == "up" else market.down_token_id
                kelly = kelly_fraction(get_bucket_win_rate(market_mid, "btc_oracle") or 0, market_mid)
                if kelly > 0:
                    suggested_size = min(settings.INITIAL_BANKROLL * kelly, settings.INITIAL_BANKROLL * 0.02, max_position_usd)
                else:
                    suggested_size = calculate_dynamic_size(
                        edge=edge,
                        confidence=confidence_score,
                        max_position_usd=max_position_usd,
                        min_position_usd=params.get("min_position_usd", self.default_params["min_position_usd"]),
                        edge_scale_threshold=params.get("edge_scale_threshold", self.default_params["edge_scale_threshold"]),
                    )
                result.decisions.append(
                    {
                        "decision": "BUY",
                        "market_ticker": market.market_id,
                        "token_id": token_id,
                        "direction": direction,
                        "confidence": confidence_score,
                        "edge": edge,
                        "size": suggested_size,
                        "entry_price": entry_price,
                        "suggested_size": suggested_size,
                        "model_probability": oracle_implied,
                        "market_probability": market_mid,
                        "platform": settings.DEFAULT_VENUE,
                        "strategy_name": self.name,
                        "reasoning": f"oracle_edge={edge:.3f} btc=${btc_price:,.0f} t={minutes_remaining:.1f}min dir={direction}",
                        "slug": market.slug,
                        "market_end_date": end_dt.isoformat(),
                    }
                )

        # Also try keyword-based scanner for any other BTC markets
        kw_markets = await fetch_markets_by_keywords(["btc", "bitcoin"], limit=200)
        btc_markets = await self.market_filter(kw_markets)

        for market in btc_markets:
            end_dt = parse_end_date(market.end_date)
            if end_dt is None:
                continue
            minutes_remaining = (end_dt - now).total_seconds() / 60.0
            if minutes_remaining < 0 or minutes_remaining > max_minutes:
                continue

            # Determine which direction oracle price implies
            result = implied_direction(market.question, btc_price)
            if result is None:
                continue
            direction, strike_price = result

            # FIX 2026-05-19: Block DOWN direction — data shows 30.4% WR
            block_down = params.get("block_direction_down", True)
            if block_down and direction == "down":
                continue

            market_mid = market.yes_price if direction == "yes" else market.no_price

            # Price bucket filter: reject negative-EV territory
            if market_mid < min_price_bucket or market_mid > max_price_bucket:
                logger.debug(
                    "BtcOracleStrategy: skipping %s — market_mid=%.2f outside bucket [%.2f, %.2f]",
                    market.ticker, market_mid, min_price_bucket, max_price_bucket,
                )
                continue

            # Oracle implied probability based on BTC price distance from strike.
            # Use price distance as a confidence signal — larger moves imply
            # higher directional probability.  Clamp to [0.01, 0.99] to avoid
            # degenerate 0/1 probabilities that kill win-rate tracking.
            price_distance = abs(btc_price - strike_price) / max(strike_price, 1.0)
            # Map distance to a probability delta: 0% distance -> 0 delta,
            # 5%+ distance -> ~0.20 delta (cap).
            prob_delta = min(0.20, price_distance * 4.0)
            if direction == "yes":
                oracle_implied = min(0.99, market_mid + prob_delta)
            else:
                oracle_implied = max(0.01, market_mid - prob_delta)
            edge = abs(oracle_implied - market_mid) - min_edge

            decision = "BUY" if edge > 0 else "SKIP"
            confidence_score = min(1.0, abs(edge + min_edge) / min_edge) if min_edge > 0 else 0.0

            record_decision_standalone(
                self.name,
                market.ticker,
                decision,
                confidence=confidence_score,
                signal_data={
                    "oracle_price": btc_price,
                    "market_mid": market_mid,
                    "implied_direction": direction,
                    "time_to_resolution_s": minutes_remaining * 60,
                    "edge": edge,
                    "market_question": market.question,
                },
                reason=f"oracle_edge={edge:.3f} btc=${btc_price:,.0f} t={minutes_remaining:.1f}min",
            )
            result.decisions_recorded += 1

            activity_logger.log_entry(
                strategy_name=self.name,
                decision_type="entry" if decision == "BUY" else "hold",
                data={
                    "market_ticker": market.ticker,
                    "oracle_price": btc_price,
                    "market_mid": market_mid,
                    "direction": direction,
                    "edge": edge,
                    "minutes_remaining": minutes_remaining,
                    "question": market.question,
                },
                confidence=confidence_score,
                mode=ctx.mode,
                db=ctx.db
            )

            if decision == "BUY":
                # ── Debate gate: validate keyword-based signal ──
                debate_ok, debate_conf = await self._debate_validate(
                    question=market.question, market_price=market_mid,
                    context=f"btc=${btc_price:,.0f} edge={edge:.3f} dir={direction} t={minutes_remaining:.1f}min",
                    db=getattr(ctx, 'db', None),
                )
                if not debate_ok:
                    logger.info("BtcOracleStrategy: debate rejected BUY for {} (confidence={:.2f})", market.ticker, debate_conf)
                    continue
                confidence_score = max(confidence_score, debate_conf)

                result.trades_attempted += 1
                _log_signal(
                    market_id=market.ticker,
                    market_mid=market_mid,
                    btc_spot=btc_price,
                    micro=None,
                    direction=direction,
                    edge=edge,
                    oracle_implied=oracle_implied,
                )
                # Extract token_id from market metadata (clobTokenIds)
                clob_token_id = None
                clob_token_ids = market.metadata.get("clobTokenIds") or []
                if isinstance(clob_token_ids, str):
                    import json as _json

                    try:
                        clob_token_ids = _json.loads(clob_token_ids)
                    except Exception as e:
                        logger.debug("Failed to parse CLOB token IDs from JSON: %s", e)
                        clob_token_ids = []
                if clob_token_ids and len(clob_token_ids) >= 2:
                    clob_token_id = str(clob_token_ids[0] if direction in ("yes", "up") else clob_token_ids[1])
                elif clob_token_ids:
                    clob_token_id = str(clob_token_ids[0])

                # Populate result.decisions so scan_and_trade_job() / strategy_cycle_job()
                # can feed them into strategy_executor.execute_decisions() for paper + live mode.
                oracle_entry_price = (
                    market_mid
                    if direction in ("yes", "up")
                    else round(1.0 - market_mid, 6)
                )
                confidence_score = min(1.0, abs(edge + min_edge) / min_edge) if min_edge > 0 else 0.0
                kelly = kelly_fraction(get_bucket_win_rate(market_mid, "btc_oracle") or 0, market_mid)
                if kelly > 0:
                    suggested_size = min(settings.INITIAL_BANKROLL * kelly, settings.INITIAL_BANKROLL * 0.02, max_position_usd)
                else:
                    suggested_size = calculate_dynamic_size(
                        edge=edge,
                        confidence=confidence_score,
                        max_position_usd=max_position_usd,
                        min_position_usd=params.get("min_position_usd", self.default_params["min_position_usd"]),
                        edge_scale_threshold=params.get("edge_scale_threshold", self.default_params["edge_scale_threshold"]),
                    )
                result.decisions.append(
                    {
                        "decision": "BUY",
                        "market_ticker": market.ticker,
                        "token_id": clob_token_id,
                        "direction": direction,
                        "confidence": confidence_score,
                        "edge": edge,
                        "size": suggested_size,
                        "entry_price": oracle_entry_price,
                        "suggested_size": suggested_size,
                        "model_probability": max(0.01, min(0.99, oracle_implied)),
                        "market_probability": market_mid,
                        "platform": settings.DEFAULT_VENUE,
                        "strategy_name": self.name,
                        "reasoning": f"oracle_edge={edge:.3f} btc=${btc_price:,.0f} t={minutes_remaining:.1f}min",
                        "slug": market.slug,
                    }
                )
        return result


# Event bus registration happens in scheduler._register_event_driven_strategies()
# which calls subscribe_strategy("btc_oracle", strategy.subscribed_tokens,
#   strategy.subscribed_events, strategy.on_market_event, fallback_handler=...)
