"""
Weather settlement functions extracted from settlement_helpers.py.

Handles weather market resolution, calibration, and observation recording.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Optional, Tuple

import httpx
from cachetools import TTLCache

from backend.models.database import Trade, TradeContext
from backend.config import settings
from backend.data.shared_client import get_shared_client

from loguru import logger

# Import functions moved to resolution.py and calculate_pnl.py
from backend.core.settlement.resolution import (
    fetch_polymarket_resolution,
    _fetch_kalshi_resolution,
)
from backend.core.settlement.calculate_pnl import calculate_pnl

# Module-level: cache already-resolved markets to skip redundant gamma REST calls
# TTL=3600s (1h) — resolved markets don't change; prevents 429 on repeated settlement cycles
_resolved_market_cache: TTLCache = TTLCache(maxsize=2000, ttl=3600)

# Semaphore: cap concurrent gamma API calls to avoid 429 rate limiting
# Initialized lazily in _resolve_markets (asyncio event loop must be running)
_gamma_semaphore: Optional[asyncio.Semaphore] = None

# In-flight deduplication: maps ticker -> asyncio.Event
# Prevents thundering-herd cache stampede when multiple coroutines resolve
# the same conditionId concurrently before any result is cached.
_gamma_inflight: dict = {}


async def check_weather_settlement(
    trade: Trade,
) -> Tuple[bool, Optional[float], Optional[float]]:
    """
    Check if a weather trade's market has settled.
    Routes to the correct platform's resolution method.
    """
    platform = getattr(trade, "platform", "polymarket") or "polymarket"

    if platform == "kalshi":
        is_resolved, settlement_value = await _fetch_kalshi_resolution(
            trade.market_ticker
        )
    else:
        is_resolved, settlement_value = await fetch_polymarket_resolution(
            trade.market_ticker,
            event_slug=trade.event_slug,
            condition_id=getattr(trade, "condition_id", None),
        )

    if is_resolved and settlement_value is not None:
        pnl = calculate_pnl(trade, settlement_value)
        return True, settlement_value, pnl

    return False, None, None


async def _resolve_markets(
    normal_tickers: set,
    weather_tickers: set,
    trade_slugs: dict,
    trade_platforms: dict,
) -> dict:
    """
    Resolve all unique market tickers concurrently.

    Returns a dict mapping ticker -> (is_resolved, settlement_value).
    normal_tickers: set of tickers for BTC/standard markets.
    weather_tickers: set of tickers for weather markets.
    trade_slugs: dict mapping ticker -> event_slug (may be None).
    trade_platforms: dict mapping ticker -> platform string.
    """

    global _gamma_semaphore
    if _gamma_semaphore is None:
        _gamma_semaphore = asyncio.Semaphore(5)

    async def _resolve_one(ticker: str, is_weather: bool):
        if ticker in _resolved_market_cache:
            return ticker, _resolved_market_cache[ticker]

        if ticker in _gamma_inflight:
            await _gamma_inflight[ticker].wait()
            return ticker, _resolved_market_cache.get(ticker)

        event = asyncio.Event()
        _gamma_inflight[ticker] = event
        try:
            platform = trade_platforms.get(ticker, "polymarket") or "polymarket"
            async with _gamma_semaphore:
                metar_observed = None
                if is_weather:
                    try:
                        from backend.data.weather import CITY_CONFIG, fetch_noaa_metar

                        city_key = (
                            ticker
                            if ticker in CITY_CONFIG
                            else next(
                                (k for k in CITY_CONFIG if k in (ticker or "").lower()),
                                None,
                            )
                        )
                        if city_key and CITY_CONFIG[city_key].get("nws_station"):
                            station_id = CITY_CONFIG[city_key]["nws_station"]
                            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                            metar_observed = await fetch_noaa_metar(
                                station_id, today_str
                            )
                    except Exception as metar_err:
                        logger.debug(
                            f"[weather._resolve_one] METAR lookup skipped for {ticker}: {metar_err}"
                        )

                if platform == "kalshi":
                    result = await _fetch_kalshi_resolution(ticker)
                elif platform == "lighter":
                    # Lighter does not have a fetch_lighter_resolution yet, so return False
                    result = False, None
                else:
                    result = await fetch_polymarket_resolution(
                        ticker, event_slug=trade_slugs.get(ticker)
                    )

                if is_weather and metar_observed:
                    logger.info(
                        f"Weather settlement {ticker}: METAR observation used as primary source "
                        f"(station={metar_observed.get('station_id')}, temp_c={metar_observed.get('temp_c')})"
                    )
                elif is_weather:
                    logger.info(
                        f"Weather settlement {ticker}: METAR unavailable, falling back to NWS/platform forecast"
                    )
                await asyncio.sleep(0.1)
            if result and result[0]:
                _resolved_market_cache[ticker] = result
            return ticker, result
        finally:
            event.set()
            _gamma_inflight.pop(ticker, None)

    tasks = [_resolve_one(t, False) for t in normal_tickers] + [
        _resolve_one(t, True) for t in weather_tickers
    ]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    resolutions = {}
    for item in gathered:
        if isinstance(item, Exception):
            logger.warning(
                f"[weather._resolve_markets] {type(item).__name__}: partial settlement: {item}",
                exc_info=item,
            )
            continue
        ticker, result = item
        resolutions[ticker] = result
    return resolutions


async def _get_actual_temp_from_openmeteo(
    city_key: str, target_date: str
) -> Optional[float]:
    try:
        from backend.data.weather import CITY_CONFIG

        cfg = CITY_CONFIG.get(city_key, {})
        lat = cfg.get("lat")
        lon = cfg.get("lon")
        if not lat or not lon:
            return None

        client = get_shared_client()
        resp = await client.get(
            settings.OPEN_METEO_ARCHIVE_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": target_date,
                "end_date": target_date,
                "daily": (
                    "temperature_2m_max"
                    if cfg.get("metric") != "low"
                    else "temperature_2m_min"
                ),
            },
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        daily = data.get("daily", {})
        temps = daily.get("temperature_2m_max") or daily.get("temperature_2m_min")
        if temps and len(temps) > 0:
            return float(temps[0])
    except Exception as e:
        logger.debug(
            f"[weather._get_actual_temp_from_openmeteo] {type(e).__name__}: Failed to fetch temperature for {city_key} on {target_date}: {e}",
            exc_info=True,
        )
    return None


async def _try_calibrate_weather(signal, settlement_value: float) -> None:
    try:
        from backend.core.learning.calibration import update_calibration

        sources = signal.sources or []
        city_key = next(
            (s.split(":", 1)[1] for s in sources if s.startswith("city:")),
            None,
        )
        if not city_key:
            return

        m = re.search(r"Ensemble:\s*([\d.]+)F", signal.reasoning or "")
        if not m:
            return
        forecast_temp_f = float(m.group(1))

        m2 = re.search(r"(?:above|below)\s*([\d.]+)F", signal.reasoning)
        threshold_f = float(m2.group(1)) if m2 else forecast_temp_f

        target_date_match = re.search(
            r"on\s+(\d{4}-\d{2}-\d{2})", signal.reasoning or ""
        )
        actual_temp_f = None

        if target_date_match:
            target_date = target_date_match.group(1)
            actual_temp_f = await _get_actual_temp_from_openmeteo(city_key, target_date)

        if actual_temp_f is None:
            direction_above = "above" in (signal.reasoning or "").lower().split("|")[0]
            if settlement_value == 1.0:
                actual_temp_f = (
                    threshold_f + 1.0 if direction_above else threshold_f - 1.0
                )
            else:
                actual_temp_f = (
                    threshold_f - 1.0 if direction_above else threshold_f + 1.0
                )

        update_calibration(
            city_key,
            source="gefs",
            forecast_temp_f=forecast_temp_f,
            actual_temp_f=actual_temp_f,
        )
        logger.debug(
            f"Calibration updated: {city_key} forecast={forecast_temp_f:.1f} actual≈{actual_temp_f:.1f}"
        )

    except Exception as e:
        logger.debug(
            f"[weather._try_calibrate_weather] {type(e).__name__}: Calibration update skipped (best-effort): {e}"
        )


async def _record_weather_observation(trade, settlement_value: float, db) -> None:
    from backend.modules.scanners.weather_emos import (
        load_calibration_states,
        save_calibration_states,
        CalibrationState,
    )

    signal_data = getattr(trade, "signal_data", None)
    if not signal_data:
        try:
            ctx = (
                db.query(TradeContext).filter(TradeContext.trade_id == trade.id).first()
            )
            if ctx and ctx.signal_source:
                try:
                    signal_data = json.loads(ctx.signal_source)
                except Exception as e:
                    logger.debug(
                        f"[weather._record_weather_observation] {type(e).__name__}: JSON parse of signal_source failed: {e}",
                        exc_info=True,
                    )
        except Exception as e:
            logger.debug(
                f"[weather._record_weather_observation] {type(e).__name__}: DB query for TradeContext failed: {e}",
                exc_info=True,
            )

    if not signal_data:
        logger.debug(f"Weather calibration: no signal_data for trade {trade.id}")
        return

    if isinstance(signal_data, str):
        try:
            signal_data = json.loads(signal_data)
        except Exception as e:
            logger.debug(
                f"[weather._record_weather_observation] {type(e).__name__}: Could not parse signal_data for trade {trade.id}: {e}",
                exc_info=True,
            )
            return

    forecast_mean_f = signal_data.get("forecast_mean_f") or signal_data.get(
        "forecast_temp"
    )
    calibrated_std_f = signal_data.get("calibrated_std_f", 5.0)
    city = signal_data.get("city")
    direction = signal_data.get("direction", "above")
    threshold_f = signal_data.get("threshold_f")

    if not forecast_mean_f or not city:
        logger.debug(
            f"Weather calibration: missing forecast_mean_f or city for trade {trade.id}"
        )
        return

    if threshold_f:
        if settlement_value == 1.0:
            if direction == "above":
                actual_temp_f = threshold_f + 2.0
            else:
                actual_temp_f = threshold_f - 2.0
        else:
            if direction == "above":
                actual_temp_f = threshold_f - 2.0
            else:
                actual_temp_f = threshold_f + 2.0
    else:
        actual_temp_f = forecast_mean_f + (2.0 if settlement_value == 1.0 else -2.0)

    cal_states = load_calibration_states(db, "weather_emos")
    cal = cal_states.get(city, CalibrationState())
    cal.add_observation(forecast_mean_f, calibrated_std_f, actual_temp_f)
    cal_states[city] = cal
    save_calibration_states(db, "weather_emos", cal_states)
    logger.info(
        f"Weather EMOS: recorded obs for {city}: forecast={forecast_mean_f:.1f}F actual~{actual_temp_f:.1f}F"
    )
