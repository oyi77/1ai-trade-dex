"""
Multi-Asset Crypto Oracle Latency Strategy.

Generalizes btc_oracle.py to trade ETH, SOL, and BTC 5-min markets on Polymarket.
Monitors the oracle settlement price vs Polymarket market mid-price for short-duration
crypto binary markets. When the oracle's pre-resolution price diverges from market mid
by > min_edge AND time-to-resolution < max_minutes, fire a trade.

Starts DISABLED (same as btc_oracle). Enable via StrategyConfig DB table.
"""

from datetime import datetime, timezone
from typing import Dict, Optional

from backend.strategies.base import (
    BaseStrategy,
    StrategyContext,
    CycleResult,
    MarketEvent,
)
from backend.core.market_scanner import MarketInfo
from backend.core.decisions import record_decision_standalone
from backend.core.activity_logger import activity_logger
from backend.config import settings
from backend.core.calibration import get_bucket_win_rate, kelly_fraction
from backend.core.crypto_oracle_tracker import CryptoOracleTracker
from backend.db.utils import get_db_session
from backend.models.signal_log import SignalLog
from backend.ai.debate_router import run_debate_with_routing

from loguru import logger

# Supported assets: CoinGecko IDs
SUPPORTED_ASSETS = [
    a.strip()
    for a in getattr(settings, "CRYPTO_ORACLE_ASSETS", "bitcoin,ethereum,solana").split(
        ","
    )
    if a.strip()
]

# Mapping from CoinGecko ID to asset prefix for market slugs
_COINGECKO_TO_ASSET_PREFIX = {
    "bitcoin": "btc",
    "ethereum": "eth",
    "solana": "sol",
}

# Reverse: asset prefix -> CoinGecko ID
_ASSET_PREFIX_TO_COINGECKO = {v: k for k, v in _COINGECKO_TO_ASSET_PREFIX.items()}


def _log_signal(
    *,
    market_id: str,
    market_mid: float,
    crypto_spot: Optional[float],
    micro,
    direction: Optional[str],
    edge: float,
    oracle_implied: float,
    asset: str = "bitcoin",
) -> None:
    """Persist one SignalLog row for a crypto_oracle signal.

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
            btc_spot=float(crypto_spot) if crypto_spot is not None else None,
            rsi=(
                float(micro.rsi)
                if micro is not None and getattr(micro, "rsi", None) is not None
                else None
            ),
            momentum_5m=(
                float(micro.momentum_5m)
                if micro is not None and getattr(micro, "momentum_5m", None) is not None
                else None
            ),
            vwap_deviation=(
                float(micro.vwap_deviation)
                if micro is not None
                and getattr(micro, "vwap_deviation", None) is not None
                else None
            ),
            sma_crossover=(
                float(micro.sma_crossover)
                if micro is not None
                and getattr(micro, "sma_crossover", None) is not None
                else None
            ),
            proposed_side=direction,
            edge_pp=float(edge) * 100.0,
            oracle_implied=float(oracle_implied),
            filled=None,
            pnl=None,
            strategy="crypto_oracle",
        )
        with get_db_session() as db:
            db.add(record)
    except Exception as e:
        logger.debug(f"crypto_oracle: SignalLog write failed: {e}")


COINGECKO_PRICE_URL = f"{settings.COINGECKO_API_URL}/simple/price"

# Module-level tracker instance (lazy init)
_tracker: Optional[CryptoOracleTracker] = None


def _get_tracker() -> CryptoOracleTracker:
    global _tracker
    if _tracker is None:
        _tracker = CryptoOracleTracker()
    return _tracker


def _get_time_multiplier() -> float:
    """Return Kelly sizing multiplier based on UTC hour."""
    hour = datetime.now(timezone.utc).hour
    peak = getattr(settings, "CRYPTO_ORACLE_PEAK_HOURS", [17, 18])
    normal = getattr(
        settings, "CRYPTO_ORACLE_NORMAL_HOURS", [13, 14, 15, 16, 19, 20, 21]
    )
    weights = getattr(
        settings,
        "CRYPTO_ORACLE_TIME_WEIGHTS",
        {"peak": 1.0, "normal": 0.5, "off_peak": 0.25},
    )
    if hour in peak:
        return weights.get("peak", 1.0)
    if hour in normal:
        return weights.get("normal", 0.5)
    return weights.get("off_peak", 0.25)


def _compute_asset_weights(assets: list[str]) -> Dict[str, float]:
    """Compute per-asset allocation weights from rolling WR.

    Higher WR -> more capital. Capped at 50% per asset to prevent concentration.
    Returns dict of asset -> weight (sums to 1.0).
    """
    tracker = _get_tracker()
    raw: Dict[str, float] = {}
    for asset in assets:
        stats = tracker.get_asset_stats(asset, lookback_trades=20)
        if stats.trade_count >= 5:
            raw[asset] = max(0.1, stats.win_rate)  # floor at 0.1 so no asset gets zero
        else:
            raw[asset] = 1.0  # default weight for new assets

    total = sum(raw.values())
    if total <= 0:
        return {a: 1.0 / len(assets) for a in assets}

    weights = {a: w / total for a, w in raw.items()}
    # Cap at 50%
    capped = {a: min(w, 0.50) for a, w in weights.items()}
    cap_total = sum(capped.values())
    if cap_total > 0:
        capped = {a: w / cap_total for a, w in capped.items()}
    return capped


def calculate_dynamic_size(
    *,
    edge: float,
    confidence: float,
    max_position_usd: float,
    min_position_usd: Optional[float] = None,
    edge_scale_threshold: Optional[float] = None,
) -> float:
    """Return an AI-signal-sized position proposal within the strategy mandate."""
    cap = max(0.0, float(max_position_usd))
    if cap <= 0:
        return 0.0

    _min_pos = (
        min_position_usd
        if min_position_usd is not None
        else settings.CRYPTO_ORACLE_MIN_POSITION_USD
    )
    _edge_scale = (
        edge_scale_threshold
        if edge_scale_threshold is not None
        else settings.CRYPTO_ORACLE_EDGE_SCALE_THRESHOLD
    )

    edge_score = min(1.0, max(0.0, edge) / max(_edge_scale, 0.001))
    confidence_score = min(1.0, max(0.0, confidence))
    sizing_fraction = max(0.10, edge_score * confidence_score)
    proposed = cap * sizing_fraction

    if proposed < _min_pos and cap >= _min_pos:
        return _min_pos
    return round(min(proposed, cap), 2)


def _kelly_size(
    market_mid: float, bankroll: float, cap: float, strategy_name: str = "crypto_oracle"
) -> float:
    """Compute Kelly-calibrated size from bucket win rate and market price."""
    win_rate = get_bucket_win_rate(market_mid, strategy_name)
    if win_rate is None:
        return 0.0
    kelly = kelly_fraction(win_rate, market_mid)
    return min(bankroll * kelly, bankroll * 0.02, cap)


async def fetch_crypto_price_for_asset(asset: str = "bitcoin") -> Optional[float]:
    """Fetch current crypto/USD price from multi-exchange klines.

    Args:
        asset: CoinGecko ID ("bitcoin", "ethereum", "solana").
    """
    try:
        from backend.data.crypto import compute_crypto_microstructure

        micro = await compute_crypto_microstructure(asset)
        if micro and micro.price > 0:
            return micro.price
    except Exception as e:
        logger.warning(
            f"CryptoOracleStrategy: microstructure fetch failed for {asset}: {e}"
        )

    try:
        from backend.data.crypto import fetch_crypto_price

        # Map CoinGecko ID to symbol for fetch_crypto_price
        _id_to_symbol = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL"}
        symbol = _id_to_symbol.get(asset, asset.upper())
        result = await fetch_crypto_price(symbol)
        if result and result.current_price > 0:
            return result.current_price
    except Exception as e:
        logger.warning(
            f"CryptoOracleStrategy: CoinGecko fallback failed for {asset}: {e}"
        )
    return None


def parse_end_date(end_date_str: Optional[str]) -> Optional[datetime]:
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


def implied_direction(question: str, crypto_price: float) -> Optional[str]:
    """
    Infer YES/NO from market question and current price.
    e.g. "Will BTC exceed $95,000 on March 15?" + crypto_price=96000 -> "yes"
    Returns "yes", "no", or None if cannot determine.
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
        return "yes" if crypto_price > threshold else "no"
    if is_below:
        return "yes" if crypto_price < threshold else "no"
    return None


class CryptoOracleStrategy(BaseStrategy):
    name = "crypto_oracle"
    description = (
        "Multi-asset crypto oracle latency arb: exploits 2-5s oracle settlement lag on "
        "short-duration BTC/ETH/SOL markets. Generalizes btc_oracle to all supported crypto assets."
    )
    category = "arbitrage"
    default_params = {
        "min_edge": settings.CRYPTO_ORACLE_MIN_EDGE,
        "max_minutes_to_resolution": settings.CRYPTO_ORACLE_MAX_MINUTES_TO_RESOLUTION,
        "interval_seconds": settings.CRYPTO_ORACLE_INTERVAL_SECONDS,
        "max_position_usd": settings.CRYPTO_ORACLE_MAX_POSITION_USD,
        "edge_scale_threshold": settings.CRYPTO_ORACLE_EDGE_SCALE_THRESHOLD,
        "min_position_usd": settings.CRYPTO_ORACLE_MIN_POSITION_USD,
        "oracle_implied_base": settings.CRYPTO_ORACLE_ORACLE_IMPLIED_BASE,
        "oracle_implied_scale": settings.CRYPTO_ORACLE_ORACLE_IMPLIED_SCALE,
        "debate_enabled": True,
        "debate_min_confidence": 0.55,
    }

    supported_assets = SUPPORTED_ASSETS

    async def _debate_validate(
        self, question: str, market_price: float, context: str = "", db=None
    ) -> tuple[bool, float]:
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
                return (
                    result.confidence
                    >= self.default_params.get("debate_min_confidence", 0.55),
                    result.confidence,
                )
        except Exception:
            logger.warning(
                "CryptoOracleStrategy: debate validation failed, allowing trade"
            )
        return True, 0.5

    # -- Event-driven (WebSocket) subscription config --
    subscribed_tokens: set[str] = set()
    subscribed_events: set[str] = {"last_trade_price", "price_change"}
    _tokens_populated: bool = False

    async def _populate_subscribed_tokens(self) -> None:
        """Discover active crypto markets and populate subscribed_tokens with their CLOB token IDs."""
        try:
            from backend.data.btc_markets import fetch_active_crypto_markets

            token_ids: set[str] = set()
            for asset_prefix in _COINGECKO_TO_ASSET_PREFIX.values():
                try:
                    markets = await fetch_active_crypto_markets(asset=asset_prefix)
                    for m in markets:
                        if m.up_token_id:
                            token_ids.add(m.up_token_id)
                        if m.down_token_id:
                            token_ids.add(m.down_token_id)
                except Exception as e:
                    logger.debug(
                        f"CryptoOracleStrategy: failed to fetch {asset_prefix} markets: {e}"
                    )

            self.subscribed_tokens = token_ids
            logger.info(
                "CryptoOracleStrategy: subscribed_tokens populated with %d token IDs",
                len(token_ids),
            )
            await self.register_with_event_bus()
        except Exception as e:
            logger.warning(
                "CryptoOracleStrategy: failed to populate subscribed_tokens: %s", e
            )

    async def on_market_event(self, event: MarketEvent) -> Optional[dict]:
        """Handle a real-time WS market event for a subscribed crypto token."""
        params = {**self.default_params}
        min_edge = params.get("min_edge", self.default_params["min_edge"])
        max_position_usd = float(
            params.get("max_position_usd", self.default_params["max_position_usd"])
        )
        edge_scale_threshold = params.get(
            "edge_scale_threshold", self.default_params["edge_scale_threshold"]
        )
        min_position_usd = params.get(
            "min_position_usd", self.default_params["min_position_usd"]
        )

        price_str = event.data.get("price") or event.data.get("last_trade_price")
        if not price_str:
            return None
        try:
            trade_price = float(price_str)
        except (ValueError, TypeError):
            return None

        if trade_price <= 0 or trade_price >= 1:
            return None

        direction = "up" if trade_price > 0.5 else "down"
        market_mid = trade_price

        # Price bucket filter: reject negative-EV territory
        min_price_bucket = params.get(
            "min_price_bucket",
            getattr(settings, "CRYPTO_ORACLE_MIN_PRICE_BUCKET", 0.35),
        )
        max_price_bucket = params.get(
            "max_price_bucket",
            getattr(settings, "CRYPTO_ORACLE_MAX_PRICE_BUCKET", 0.65),
        )
        if market_mid < min_price_bucket or market_mid > max_price_bucket:
            logger.debug(
                "CryptoOracleStrategy.on_market_event: skipping — market_mid=%.2f outside bucket [%.2f, %.2f]",
                market_mid,
                min_price_bucket,
                max_price_bucket,
            )
            return None

        # Determine asset from event metadata or default to bitcoin
        asset = event.data.get("asset", "bitcoin")

        crypto_price = await fetch_crypto_price_for_asset(asset)
        if crypto_price is None:
            logger.debug(
                "CryptoOracleStrategy.on_market_event: could not fetch %s price, skipping",
                asset,
            )
            return None

        from backend.data.crypto import compute_crypto_microstructure

        try:
            micro = await compute_crypto_microstructure(asset)
        except Exception:
            logger.exception(
                "crypto_oracle: failed to fetch %s price for oracle signal", asset
            )
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
            oracle_base = params.get(
                "oracle_implied_base", settings.CRYPTO_ORACLE_ORACLE_IMPLIED_BASE
            )
            oracle_scale = params.get(
                "oracle_implied_scale", settings.CRYPTO_ORACLE_ORACLE_IMPLIED_SCALE
            )
            oracle_implied = oracle_base + composite * oracle_scale
            if direction == "down":
                oracle_implied = 1.0 - oracle_implied
        else:
            oracle_implied = market_mid

        edge = abs(oracle_implied - market_mid) - min_edge

        if edge <= 0:
            return None

        confidence_score = (
            min(1.0, abs(edge + min_edge) / min_edge) if min_edge > 0 else 0.0
        )
        kelly = kelly_fraction(
            get_bucket_win_rate(market_mid, "crypto_oracle") or 0, market_mid
        )
        if kelly > 0:
            suggested_size = min(
                settings.INITIAL_BANKROLL * kelly,
                settings.INITIAL_BANKROLL * 0.02,
                max_position_usd,
            )
        else:
            suggested_size = calculate_dynamic_size(
                edge=edge,
                confidence=confidence_score,
                max_position_usd=max_position_usd,
                min_position_usd=min_position_usd,
                edge_scale_threshold=edge_scale_threshold,
            )

        market_ticker = (
            event.data.get("market_ticker")
            or event.data.get("market_id")
            or event.token_id
        )
        token_id = event.token_id

        record_decision_standalone(
            self.name,
            market_ticker,
            "BUY",
            confidence=confidence_score,
            signal_data={
                "oracle_price": crypto_price,
                "market_mid": market_mid,
                "implied_direction": direction,
                "edge": edge,
                "event_type": event.event_type,
                "source": "ws_event",
                "asset": asset,
            },
            reason=f"ws_oracle_edge={edge:.3f} {asset}=${crypto_price:,.0f} dir={direction} event={event.event_type}",
        )

        _log_signal(
            market_id=market_ticker,
            market_mid=market_mid,
            crypto_spot=crypto_price,
            micro=micro,
            direction=direction,
            edge=edge,
            oracle_implied=oracle_implied,
            asset=asset,
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
            "reasoning": f"ws_oracle_edge={edge:.3f} {asset}=${crypto_price:,.0f} dir={direction} event={event.event_type}",
        }

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Filter to active crypto binary markets resolving within max_minutes."""
        crypto_keywords = ["btc", "bitcoin", "eth", "ethereum", "sol", "solana"]
        return [
            m
            for m in markets
            if any(
                kw in m.slug.lower() or kw in m.question.lower()
                for kw in crypto_keywords
            )
            and m.end_date is not None
        ]

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        if not self._tokens_populated:
            await self._populate_subscribed_tokens()
            self._tokens_populated = True

        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        params = {**self.default_params, **(ctx.params or {})}
        min_edge = params.get("min_edge", self.default_params["min_edge"])
        max_minutes = params.get(
            "max_minutes_to_resolution",
            self.default_params["max_minutes_to_resolution"],
        )
        max_position_usd = float(
            params.get("max_position_usd", self.default_params["max_position_usd"])
        )

        from backend.data.btc_markets import fetch_active_crypto_markets
        from backend.core.market_scanner import fetch_markets_by_keywords

        now = datetime.now(timezone.utc)

        # Price bucket filter: only trade in the 40-60c range where edge is proven.
        # Negative-EV territory is below 35c and above 65c (backtest: 85.6% WR in 50-55c).
        min_price_bucket = params.get(
            "min_price_bucket",
            getattr(settings, "CRYPTO_ORACLE_MIN_PRICE_BUCKET", 0.35),
        )
        max_price_bucket = params.get(
            "max_price_bucket",
            getattr(settings, "CRYPTO_ORACLE_MAX_PRICE_BUCKET", 0.65),
        )

        # Dynamic allocation: compute per-asset weights from rolling WR
        asset_weights: Dict[str, float] = {}
        if getattr(settings, "CRYPTO_ORACLE_DYNAMIC_ALLOCATION", False):
            asset_weights = _compute_asset_weights(self.supported_assets)
            logger.info(
                "CryptoOracleStrategy: dynamic allocation weights = %s", asset_weights
            )

        # Time-of-day multiplier
        time_mult = _get_time_multiplier()
        if time_mult < 1.0:
            logger.debug(
                "CryptoOracleStrategy: time multiplier = %.2f (hour=%d UTC)",
                time_mult,
                now.hour,
            )

        # Iterate over all supported assets
        for coingecko_id in self.supported_assets:
            asset_prefix = _COINGECKO_TO_ASSET_PREFIX.get(
                coingecko_id, coingecko_id[:3]
            )

            crypto_price = await fetch_crypto_price_for_asset(coingecko_id)
            if crypto_price is None:
                logger.debug(
                    "CryptoOracleStrategy: could not fetch %s price, skipping",
                    coingecko_id,
                )
                continue

            # Fetch dedicated 5-min markets for this asset
            try:
                asset_markets = await fetch_active_crypto_markets(asset=asset_prefix)
            except Exception as e:
                logger.warning(
                    f"CryptoOracleStrategy.run_cycle: failed to fetch {coingecko_id} markets: {e}"
                )
                continue

            for market in asset_markets:
                end_dt = market.window_end
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                minutes_remaining = (end_dt - now).total_seconds() / 60.0
                if minutes_remaining < 0 or minutes_remaining > max_minutes:
                    continue

                from backend.data.crypto import compute_crypto_microstructure

                try:
                    micro = await compute_crypto_microstructure(coingecko_id)
                except Exception as e:
                    logger.debug(
                        "Crypto microstructure computation failed for %s: %s",
                        coingecko_id,
                        e,
                    )
                    micro = None

                if micro and micro.momentum_5m is not None:
                    direction = "up" if micro.momentum_5m > 0 else "down"
                else:
                    direction = "down" if market.up_price > market.down_price else "up"

                market_mid = market.up_price if direction == "up" else market.down_price

                # Price bucket filter: reject negative-EV territory
                if market_mid < min_price_bucket or market_mid > max_price_bucket:
                    logger.debug(
                        "CryptoOracleStrategy: skipping %s — market_mid=%.2f outside bucket [%.2f, %.2f]",
                        market.slug,
                        market_mid,
                        min_price_bucket,
                        max_price_bucket,
                    )
                    continue

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
                    oracle_base = params.get(
                        "oracle_implied_base",
                        settings.CRYPTO_ORACLE_ORACLE_IMPLIED_BASE,
                    )
                    oracle_scale = params.get(
                        "oracle_implied_scale",
                        settings.CRYPTO_ORACLE_ORACLE_IMPLIED_SCALE,
                    )
                    oracle_implied = oracle_base + composite * oracle_scale

                    if direction == "down":
                        oracle_implied = 1.0 - oracle_implied
                else:
                    oracle_implied = market_mid

                edge = abs(oracle_implied - market_mid) - min_edge

                decision = "BUY" if edge > 0 else "SKIP"
                confidence_score = (
                    min(1.0, abs(edge + min_edge) / min_edge) if min_edge > 0 else 0.0
                )

                record_decision_standalone(
                    self.name,
                    market.market_id,
                    decision,
                    confidence=confidence_score,
                    signal_data={
                        "oracle_price": crypto_price,
                        "market_mid": market_mid,
                        "implied_direction": direction,
                        "time_to_resolution_s": minutes_remaining * 60,
                        "edge": edge,
                        "slug": market.slug,
                        "asset": coingecko_id,
                    },
                    reason=f"oracle_edge={edge:.3f} {coingecko_id}=${crypto_price:,.0f} t={minutes_remaining:.1f}min dir={direction}",
                )
                result.decisions_recorded += 1

                if decision == "BUY":
                    debate_ok, debate_conf = await self._debate_validate(
                        question=market.slug,
                        market_price=market_mid,
                        context=f"{coingecko_id}=${crypto_price:,.0f} edge={edge:.3f} dir={direction} t={minutes_remaining:.1f}min",
                        db=getattr(ctx, "db", None),
                    )
                    if not debate_ok:
                        logger.info(
                            "CryptoOracleStrategy: debate rejected BUY for {} (confidence={:.2f})",
                            market.slug,
                            debate_conf,
                        )
                        continue
                    confidence_score = max(confidence_score, debate_conf)

                    result.trades_attempted += 1
                    _log_signal(
                        market_id=market.market_id,
                        market_mid=market_mid,
                        crypto_spot=crypto_price,
                        micro=micro,
                        direction=direction,
                        edge=edge,
                        oracle_implied=oracle_implied,
                        asset=coingecko_id,
                    )
                    entry_price = (
                        market.up_price if direction == "up" else market.down_price
                    )
                    token_id = (
                        market.up_token_id
                        if direction == "up"
                        else market.down_token_id
                    )
                    kelly = kelly_fraction(
                        get_bucket_win_rate(market_mid, "crypto_oracle") or 0,
                        market_mid,
                    )
                    # Apply time-of-day multiplier and asset weight to Kelly
                    asset_weight = asset_weights.get(coingecko_id, 1.0)
                    adjusted_kelly = kelly * time_mult * asset_weight
                    if adjusted_kelly > 0:
                        suggested_size = min(
                            settings.INITIAL_BANKROLL * adjusted_kelly,
                            settings.INITIAL_BANKROLL * 0.02,
                            max_position_usd,
                        )
                    else:
                        suggested_size = calculate_dynamic_size(
                            edge=edge,
                            confidence=confidence_score,
                            max_position_usd=max_position_usd,
                            min_position_usd=params.get(
                                "min_position_usd",
                                self.default_params["min_position_usd"],
                            ),
                            edge_scale_threshold=params.get(
                                "edge_scale_threshold",
                                self.default_params["edge_scale_threshold"],
                            ),
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
                            "reasoning": f"oracle_edge={edge:.3f} {coingecko_id}=${crypto_price:,.0f} t={minutes_remaining:.1f}min dir={direction}",
                            "slug": market.slug,
                            "market_end_date": end_dt.isoformat(),
                            "asset": coingecko_id,
                        }
                    )

            # Also try keyword-based scanner for any other crypto markets for this asset
            asset_keywords = [asset_prefix, coingecko_id]
            if coingecko_id == "bitcoin":
                asset_keywords.extend(["btc", "btc-up"])
            elif coingecko_id == "ethereum":
                asset_keywords.extend(["eth", "eth-up"])
            elif coingecko_id == "solana":
                asset_keywords.extend(["sol", "sol-up"])

            try:
                kw_markets = await fetch_markets_by_keywords(asset_keywords, limit=200)
                filtered_markets = await self.market_filter(kw_markets)

                for market in filtered_markets:
                    end_dt = parse_end_date(market.end_date)
                    if end_dt is None:
                        continue
                    minutes_remaining = (end_dt - now).total_seconds() / 60.0
                    if minutes_remaining < 0 or minutes_remaining > max_minutes:
                        continue

                    direction = implied_direction(market.question, crypto_price)
                    if direction is None:
                        continue

                    market_mid = (
                        market.yes_price if direction == "yes" else market.no_price
                    )

                    # Price bucket filter: reject negative-EV territory
                    if market_mid < min_price_bucket or market_mid > max_price_bucket:
                        logger.debug(
                            "CryptoOracleStrategy: skipping %s — market_mid=%.2f outside bucket [%.2f, %.2f]",
                            market.ticker,
                            market_mid,
                            min_price_bucket,
                            max_price_bucket,
                        )
                        continue

                    # Compute real edge: oracle probability from spot price vs strike
                    # Extract strike from question for edge calculation
                    import re as _re

                    _q = market.question.lower()
                    _match = _re.search(r"\$?([\d,]+\.?\d*)\s*k?\b", _q)
                    if _match:
                        _raw = _match.group(1).replace(",", "")
                        _threshold = float(_raw)
                        if (
                            "k" in _q[_match.start() : _match.end() + 2].lower()
                            and _threshold < 10000
                        ):
                            _threshold *= 1000
                        # pct_diff: how far spot is from strike (positive = above)
                        pct_diff = (
                            (crypto_price - _threshold) / _threshold
                            if _threshold > 0
                            else 0.0
                        )
                        # Oracle probability: sigmoid-like mapping centered at strike
                        # +2% above strike → ~0.60, +10% → ~0.95
                        if direction == "yes":
                            oracle_implied = max(0.05, min(0.95, 0.5 + pct_diff * 5.0))
                        else:
                            oracle_implied = max(0.05, min(0.95, 0.5 - pct_diff * 5.0))
                    else:
                        # Fallback: use moderate edge from market_mid
                        oracle_implied = market_mid + (
                            min_edge * 2 if direction == "yes" else -min_edge * 2
                        )
                        oracle_implied = max(0.05, min(0.95, oracle_implied))
                    edge = oracle_implied - market_mid
                    # No sign flip needed — market_mid is already market.no_price
                    # for NO direction (line 682), so oracle_implied - market_mid
                    # gives correct positive edge when NO is underpriced.

                    decision = "BUY" if edge > 0 else "SKIP"
                    confidence_score = (
                        min(1.0, abs(edge + min_edge) / min_edge)
                        if min_edge > 0
                        else 0.0
                    )

                    record_decision_standalone(
                        self.name,
                        market.ticker,
                        decision,
                        confidence=confidence_score,
                        signal_data={
                            "oracle_price": crypto_price,
                            "market_mid": market_mid,
                            "implied_direction": direction,
                            "time_to_resolution_s": minutes_remaining * 60,
                            "edge": edge,
                            "market_question": market.question,
                            "asset": coingecko_id,
                        },
                        reason=f"oracle_edge={edge:.3f} {coingecko_id}=${crypto_price:,.0f} t={minutes_remaining:.1f}min",
                    )
                    result.decisions_recorded += 1

                    activity_logger.log_entry(
                        strategy_name=self.name,
                        decision_type="entry" if decision == "BUY" else "hold",
                        data={
                            "market_ticker": market.ticker,
                            "oracle_price": crypto_price,
                            "market_mid": market_mid,
                            "direction": direction,
                            "edge": edge,
                            "minutes_remaining": minutes_remaining,
                            "question": market.question,
                            "asset": coingecko_id,
                        },
                        confidence=confidence_score,
                        mode=ctx.mode,
                        db=ctx.db,
                    )

                    if decision == "BUY":
                        debate_ok, debate_conf = await self._debate_validate(
                            question=market.question,
                            market_price=market_mid,
                            context=f"{coingecko_id}=${crypto_price:,.0f} edge={edge:.3f} dir={direction} t={minutes_remaining:.1f}min",
                            db=getattr(ctx, "db", None),
                        )
                        if not debate_ok:
                            logger.info(
                                "CryptoOracleStrategy: debate rejected BUY for {} (confidence={:.2f})",
                                market.ticker,
                                debate_conf,
                            )
                            continue
                        confidence_score = max(confidence_score, debate_conf)

                        result.trades_attempted += 1
                        _log_signal(
                            market_id=market.ticker,
                            market_mid=market_mid,
                            crypto_spot=crypto_price,
                            micro=None,
                            direction=direction,
                            edge=edge,
                            oracle_implied=oracle_implied,
                            asset=coingecko_id,
                        )

                        clob_token_id = None
                        clob_token_ids = market.metadata.get("clobTokenIds") or []
                        if isinstance(clob_token_ids, str):
                            import json as _json

                            try:
                                clob_token_ids = _json.loads(clob_token_ids)
                            except Exception as e:
                                logger.debug(
                                    "Failed to parse CLOB token IDs from JSON: %s", e
                                )
                                clob_token_ids = []
                        if clob_token_ids and len(clob_token_ids) >= 2:
                            clob_token_id = str(
                                clob_token_ids[0]
                                if direction in ("yes", "up")
                                else clob_token_ids[1]
                            )
                        elif clob_token_ids:
                            clob_token_id = str(clob_token_ids[0])

                        oracle_entry_price = (
                            market_mid
                            if direction in ("yes", "up")
                            else round(1.0 - market_mid, 6)
                        )
                        confidence_score = (
                            min(1.0, abs(edge + min_edge) / min_edge)
                            if min_edge > 0
                            else 0.0
                        )
                        kelly = kelly_fraction(
                            get_bucket_win_rate(market_mid, "crypto_oracle") or 0,
                            market_mid,
                        )
                        asset_weight = asset_weights.get(coingecko_id, 1.0)
                        adjusted_kelly = kelly * time_mult * asset_weight
                        if adjusted_kelly > 0:
                            suggested_size = min(
                                settings.INITIAL_BANKROLL * adjusted_kelly,
                                settings.INITIAL_BANKROLL * 0.02,
                                max_position_usd,
                            )
                        else:
                            suggested_size = calculate_dynamic_size(
                                edge=edge,
                                confidence=confidence_score,
                                max_position_usd=max_position_usd,
                                min_position_usd=params.get(
                                    "min_position_usd",
                                    self.default_params["min_position_usd"],
                                ),
                                edge_scale_threshold=params.get(
                                    "edge_scale_threshold",
                                    self.default_params["edge_scale_threshold"],
                                ),
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
                                "model_probability": max(
                                    0.05, min(0.95, oracle_implied)
                                ),
                                "market_probability": market_mid,
                                "platform": settings.DEFAULT_VENUE,
                                "strategy_name": self.name,
                                "reasoning": f"oracle_edge={edge:.3f} {coingecko_id}=${crypto_price:,.0f} t={minutes_remaining:.1f}min",
                                "slug": market.slug,
                                "asset": coingecko_id,
                            }
                        )
            except Exception as e:
                logger.debug(
                    f"CryptoOracleStrategy: keyword scan failed for {coingecko_id}: {e}"
                )

        return result


# Event bus registration happens in scheduler._register_event_driven_strategies()
