"""Signal generator for weather temperature markets using ensemble forecasts."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from scipy.stats import norm

from backend.config import settings
from backend.core.learning.calibration import get_sigma
from backend.core.signals import calculate_edge, calculate_kelly_size
from backend.data.weather import fetch_ensemble_forecast
from backend.data.weather_markets import WeatherMarket, fetch_polymarket_weather_markets
from backend.models.database import Signal

from loguru import logger


@dataclass
class WeatherTradingSignal:
    """A trading signal for a weather temperature market."""

    market: WeatherMarket

    # Core signal data
    model_probability: float = 0.5  # Ensemble probability of YES outcome
    market_probability: float = 0.5  # Market's implied YES probability
    edge: float = 0.0
    direction: str = "yes"  # "yes" or "no"

    # Confidence and sizing
    confidence: float = 0.5
    kelly_fraction: float = 0.0
    suggested_size: float = 0.0

    # Metadata
    sources: List[str] = field(default_factory=list)
    reasoning: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Forecast context
    ensemble_mean: float = 0.0
    ensemble_std: float = 0.0
    ensemble_members: int = 0

    @property
    def passes_threshold(self) -> bool:
        """Check if signal passes minimum edge threshold."""
        return abs(self.edge) >= settings.WEATHER_MIN_EDGE_THRESHOLD


async def generate_weather_signal(
    market: WeatherMarket,
    mode: str = None,
) -> Optional[WeatherTradingSignal]:
    """
    Generate a trading signal for a weather temperature market.

    Uses ensemble forecast to estimate probability:
    - Count fraction of ensemble members above/below the threshold
    - Compare to market price to find edge
    - Size using Kelly criterion
    """
    forecast = await fetch_ensemble_forecast(market.city_key, market.target_date)
    if not forecast or not forecast.member_highs:
        return None

    # Calculate model probability based on market's question
    if market.metric == "high":
        if market.direction == "above":
            model_yes_prob = forecast.probability_high_above(market.threshold_f)
        else:
            model_yes_prob = forecast.probability_high_below(market.threshold_f)
    else:  # "low"
        if market.direction == "above":
            model_yes_prob = forecast.probability_low_above(market.threshold_f)
        else:
            model_yes_prob = forecast.probability_low_below(market.threshold_f)

    # Clip extreme probabilities (ensemble can be unanimous but don't bet 100%)
    model_yes_prob = max(0.05, min(0.95, model_yes_prob))

    # Secondary: Gaussian CDF using calibrated sigma for this city
    # Provides a cross-check against pure ensemble counting
    city_sigma_f = get_sigma(market.city_key, source="gefs")
    gaussian_prob = None
    if city_sigma_f > 0:
        mean_f = forecast.mean_high if market.metric == "high" else forecast.mean_low
        if market.direction == "above":
            gaussian_prob = float(
                norm.sf(market.threshold_f, loc=mean_f, scale=city_sigma_f)
            )
        else:
            gaussian_prob = float(
                norm.cdf(market.threshold_f, loc=mean_f, scale=city_sigma_f)
            )
        gaussian_prob = max(0.05, min(0.95, gaussian_prob))
        # Blend: 70% ensemble count, 30% Gaussian CDF
        model_yes_prob = 0.70 * model_yes_prob + 0.30 * gaussian_prob
        model_yes_prob = max(0.05, min(0.95, model_yes_prob))

    market_yes_prob = market.yes_price

    # Use existing edge calculation (treats yes=up, no=down)
    edge, direction_raw = calculate_edge(model_yes_prob, market_yes_prob)
    direction = "yes" if direction_raw == "up" else "no"

    # Entry price filter
    entry_price = market.yes_price if direction == "yes" else market.no_price
    if entry_price > settings.WEATHER_MAX_ENTRY_PRICE:
        edge = 0.0  # Zero out but still return for UI visibility

    # Confidence = ensemble agreement (how one-sided the members are)
    if market.metric == "high":
        members = forecast.member_highs
    else:
        members = forecast.member_lows

    above_count = sum(1 for m in members if m > market.threshold_f)
    agreement_frac = (
        max(above_count, len(members) - above_count) / len(members) if members else 0.5
    )
    confidence = min(0.9, agreement_frac)

    # Kelly sizing — use current bankroll from BotState, not static INITIAL_BANKROLL
    bankroll = settings.INITIAL_BANKROLL
    effective_mode = mode or settings.TRADING_MODE
    try:
        from backend.models.database import BotState, for_update

        from backend.db.utils import get_db_session

        with get_db_session() as _db:
            _state = for_update(_db, _db.query(BotState)).first()
            if _state:
                if effective_mode == "paper":
                    bankroll = float(
                        _state.paper_bankroll
                        if _state.paper_bankroll is not None
                        else settings.INITIAL_BANKROLL
                    )
                elif effective_mode == "testnet":
                    bankroll = float(
                        _state.testnet_bankroll
                        if _state.testnet_bankroll is not None
                        else settings.INITIAL_BANKROLL
                    )
                else:
                    bankroll = float(
                        _state.bankroll
                        if _state.bankroll is not None
                        else settings.INITIAL_BANKROLL
                    )
    except Exception as _e:
        logger.debug(f"Bankroll read failed, using INITIAL_BANKROLL: {_e}")
    suggested_size = calculate_kelly_size(
        edge=abs(edge),
        probability=model_yes_prob,
        market_price=market_yes_prob,
        direction=direction_raw,  # calculate_kelly_size expects "up"/"down"
        bankroll=bankroll,
    )
    suggested_size = min(suggested_size, settings.WEATHER_MAX_TRADE_SIZE)

    # Ensemble stats for display
    mean_val = forecast.mean_high if market.metric == "high" else forecast.mean_low
    std_val = forecast.std_high if market.metric == "high" else forecast.std_low

    # Build reasoning
    filter_status = (
        "ACTIONABLE" if abs(edge) >= settings.WEATHER_MIN_EDGE_THRESHOLD else "FILTERED"
    )
    filter_notes = []
    if entry_price > settings.WEATHER_MAX_ENTRY_PRICE:
        filter_notes.append(
            f"entry {entry_price:.0%} > {settings.WEATHER_MAX_ENTRY_PRICE:.0%}"
        )
    filter_note = f" [{', '.join(filter_notes)}]" if filter_notes else ""

    gaussian_note = (
        f" | Gaussian: {gaussian_prob:.0%}" if gaussian_prob is not None else ""
    )

    reasoning = (
        f"[{filter_status}]{filter_note} "
        f"{market.city_name} {market.metric} {market.direction} {market.threshold_f:.0f}F on {market.target_date} | "
        f"Ensemble: {mean_val:.1f}F +/- {std_val:.1f}F ({forecast.num_members} members) | "
        f"Model YES: {model_yes_prob:.0%} vs Market: {market_yes_prob:.0%}"
        f"{gaussian_note} | "
        f"Edge: {edge:+.1%} -> {direction.upper()} @ {entry_price:.0%} | "
        f"Agreement: {agreement_frac:.0%}"
    )

    sources = [f"open_meteo_ensemble_{forecast.num_members}m"]
    if gaussian_prob is not None:
        sources.append("gaussian_calibrated")
    sources.append(f"city:{market.city_key}")

    return WeatherTradingSignal(
        market=market,
        model_probability=model_yes_prob,
        market_probability=market_yes_prob,
        edge=edge,
        direction=direction,
        confidence=confidence,
        kelly_fraction=suggested_size / bankroll if bankroll > 0 else 0,
        suggested_size=suggested_size,
        sources=sources,
        reasoning=reasoning,
        ensemble_mean=mean_val,
        ensemble_std=std_val,
        ensemble_members=forecast.num_members,
    )


async def scan_for_weather_signals(mode: str = None) -> List[WeatherTradingSignal]:
    """
    Scan weather markets and generate ensemble-based signals.
    """
    signals = []

    city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]

    logger.info("=" * 50)
    logger.info("WEATHER SCAN: Fetching temperature markets...")

    markets = []

    # Polymarket
    try:
        poly_markets = await fetch_polymarket_weather_markets(city_keys)
        markets.extend(poly_markets)
        logger.info(f"Polymarket: {len(poly_markets)} weather markets")
    except Exception as e:
        logger.error(f"Failed to fetch Polymarket weather markets: {e}")

    # Kalshi
    if settings.KALSHI_ENABLED:
        try:
            from backend.data.kalshi_client import kalshi_credentials_present
            from backend.data.kalshi_markets import fetch_kalshi_weather_markets

            if kalshi_credentials_present():
                kalshi_markets = await fetch_kalshi_weather_markets(city_keys)
                markets.extend(kalshi_markets)
                logger.info(f"Kalshi: {len(kalshi_markets)} weather markets")
        except Exception as e:
            logger.error(f"Failed to fetch Kalshi weather markets: {e}")

    logger.info(f"Found {len(markets)} total weather temperature markets")

    sem = asyncio.Semaphore(5)

    async def _gen_with_sem(market):
        async with sem:
            return await generate_weather_signal(market, mode=mode)

    results = await asyncio.gather(
        *[_gen_with_sem(m) for m in markets], return_exceptions=True
    )
    signals = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.debug(
                f"Weather signal generation failed for {markets[i].title}: {result}"
            )
        elif result is not None:
            signals.append(result)

    # Sort by absolute edge
    signals.sort(key=lambda s: abs(s.edge), reverse=True)

    actionable = [s for s in signals if s.passes_threshold]
    logger.info(
        f"WEATHER SCAN COMPLETE: {len(signals)} signals, {len(actionable)} actionable"
    )

    for signal in actionable[:5]:
        logger.info(
            f"  {signal.market.city_name}: {signal.market.metric} {signal.market.direction} "
            f"{signal.market.threshold_f:.0f}F | Edge: {signal.edge:+.1%}"
        )

    # Persist signals to DB
    _persist_weather_signals(signals, mode=mode)

    return signals


def _persist_weather_signals(signals: list, mode: str = None):
    """Save weather signals to DB for calibration tracking."""
    to_save = [s for s in signals if abs(s.edge) > 0]
    if not to_save:
        return

    effective_mode = mode or settings.TRADING_MODE

    from backend.db.utils import get_db_session

    try:
        with get_db_session() as db:
            for signal in to_save:
                # Dedup: skip if already logged for this market
                existing = (
                    db.query(Signal)
                    .filter(
                        Signal.market_ticker == signal.market.market_id,
                        Signal.timestamp
                        >= signal.timestamp.replace(second=0, microsecond=0),
                    )
                    .first()
                )
                if existing:
                    continue

                db_signal = Signal(
                    market_ticker=signal.market.market_id,
                    platform=signal.market.platform,
                    market_type="weather",
                    timestamp=signal.timestamp,
                    direction=signal.direction,
                    model_probability=signal.model_probability,
                    market_price=signal.market_probability,
                    edge=signal.edge,
                    confidence=signal.confidence,
                    kelly_fraction=signal.kelly_fraction,
                    suggested_size=signal.suggested_size,
                    sources=signal.sources,
                    reasoning=signal.reasoning,
                    track_name="weather_emos",
                    execution_mode=effective_mode,
                    executed=False,
                )
                db.add(db_signal)
                try:
                    from backend.core.event_bus import _broadcast_event

                    _broadcast_event(
                        "signal_found",
                        {
                            "market_ticker": db_signal.market_ticker,
                            "direction": db_signal.direction,
                            "confidence": db_signal.confidence,
                            "reasoning": db_signal.reasoning,
                            "suggested_size": db_signal.suggested_size,
                        },
                    )
                except Exception as e:
                    logger.debug(f"Failed to broadcast signal_found event: {e}")

            db.commit()
    except Exception as e:
        logger.warning(f"Failed to persist weather signals: {e}")
        db.rollback()
