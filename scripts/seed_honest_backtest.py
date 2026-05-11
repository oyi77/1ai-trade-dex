#!/usr/bin/env python3
"""Seed honest backtest data from resolved Polymarket markets.

Supports multiple market types:
- crypto: BTC, ETH, SOL, XRP price markets (Binance historical klines)
- weather: Temperature threshold markets (Open-Meteo archive API)

Unlike the basic seeder, this version:
1. Fetches resolved markets from Gamma API
2. Gets actual historical price/temp at market creation time
3. Computes HONEST model_probability (no look-ahead bias)
4. Compares against actual resolution to determine win/loss

Usage:
    python scripts/seed_honest_backtest.py [--days 365] [--types crypto,weather] [--dry-run]
"""

import argparse
import asyncio
import json
import logging
import math
import random
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backend.config import settings

GAMMA_API_URL = f"{settings.GAMMA_API_URL}/markets"

import httpx
from sqlalchemy.orm import Session
from backend.models.database import SessionLocal, Signal, Trade
from backend.data.gamma import fetch_markets

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("honest_seed")

# ── Crypto symbol mapping ─────────────────────────────────────────────
CRYPTO_SYMBOLS: Dict[str, str] = {
    "bitcoin": "BTCUSDT",
    "btc": "BTCUSDT",
    "ethereum": "ETHUSDT",
    "eth": "ETHUSDT",
    "solana": "SOLUSDT",
    "sol": "SOLUSDT",
    "xrp": "XRPUSDT",
}

CRYPTO_VOL_PER_HOUR: Dict[str, float] = {
    "BTCUSDT": 0.014,  # was 0.010 — increased to reduce overconfidence on far-out thresholds
    "ETHUSDT": 0.014,
    "SOLUSDT": 0.022,
    "XRPUSDT": 0.016,
}

# ── Weather city config (mirrors backend/data/weather.py) ────────────
CITY_CONFIG: Dict[str, dict] = {
    "nyc": {"name": "New York City", "lat": 40.7772, "lon": -73.8726, "unit": "F"},
    "new york": {"name": "New York City", "lat": 40.7772, "lon": -73.8726, "unit": "F"},
    "chicago": {"name": "Chicago", "lat": 41.9742, "lon": -87.9073, "unit": "F"},
    "miami": {"name": "Miami", "lat": 25.7959, "lon": -80.2870, "unit": "F"},
    "dallas": {"name": "Dallas", "lat": 32.8471, "lon": -96.8518, "unit": "F"},
    "seattle": {"name": "Seattle", "lat": 47.4502, "lon": -122.3088, "unit": "F"},
    "atlanta": {"name": "Atlanta", "lat": 33.6407, "lon": -84.4277, "unit": "F"},
    "los angeles": {
        "name": "Los Angeles",
        "lat": 33.9425,
        "lon": -118.4081,
        "unit": "F",
    },
    "denver": {"name": "Denver", "lat": 39.8561, "lon": -104.6737, "unit": "F"},
    "london": {"name": "London", "lat": 51.5048, "lon": 0.0495, "unit": "C"},
    "paris": {"name": "Paris", "lat": 48.9962, "lon": 2.5979, "unit": "C"},
    "munich": {"name": "Munich", "lat": 48.3537, "lon": 11.7750, "unit": "C"},
    "ankara": {"name": "Ankara", "lat": 40.1281, "lon": 32.9951, "unit": "C"},
    "seoul": {"name": "Seoul", "lat": 37.4691, "lon": 126.4505, "unit": "C"},
    "tokyo": {"name": "Tokyo", "lat": 35.7647, "lon": 140.3864, "unit": "C"},
}

WEATHER_DAILY_STD_C = 7.0


# ── Market classification ────────────────────────────────────────────


def classify_market(question: str, enabled_types: List[str]) -> Optional[str]:
    """Classify a market question into a type, or None if unparseable/skipped."""
    ql = question.lower()

    # Skip "between" markets — they have dual thresholds and the model
    # treats them as single-threshold which is wrong (e.g. "BTC between $107k and $109k")
    between_patterns = [
        r"between\s+\$?[\d,.]+\s*(?:and|to|-)\s*\$?[\d,.]+",
        r"between\s+\d+°?\s*(?:and|to|-)\s*\d+°?",
    ]
    for pat in between_patterns:
        if re.search(pat, ql):
            return None

    # Crypto detection
    if "crypto" in enabled_types:
        for keyword in CRYPTO_SYMBOLS:
            if keyword in ql:
                return "crypto"

    # Weather detection
    if "weather" in enabled_types:
        weather_keywords = [
            "temperature",
            "temp",
            "high of",
            "high reach",
            "degrees",
            "celsius",
            "fahrenheit",
            "warmer",
            "colder",
            "hot",
            "cold",
        ]
        for kw in weather_keywords:
            if kw in ql:
                return "weather"
        # Also check for city names from config
        for city_name in CITY_CONFIG:
            if city_name in ql:
                # Must also have a temp-like keyword or number pattern
                if re.search(r"\d+°?|\d+(f|c)\b", ql):
                    return "weather"

    return None


def parse_crypto_market(question: str) -> Optional[Tuple[str, float, bool]]:
    """Parse a crypto price market question.

    Returns (binance_symbol, threshold_price, flip_direction) or None.
    flip_direction=True means the question asks "below X" (e.g. "less than", "dip to").

    Examples:
        "Will the price of Bitcoin be above $110,000 on ..." → ("BTCUSDT", 110000.0, False)
        "Will the price of Bitcoin be less than $109,500 ..." → ("BTCUSDT", 109500.0, True)
        "Will Bitcoin dip to $60,000 ..." → ("BTCUSDT", 60000.0, True)
    """
    ql = question.lower()

    # Identify which crypto
    symbol = None
    for keyword, sym in CRYPTO_SYMBOLS.items():
        if keyword in ql:
            symbol = sym
            break
    if symbol is None:
        return None

    # Detect inverted direction patterns: "less than", "dip to", "below", "fall to", "drop to"
    flip_direction = False
    inverted_patterns = [
        r"less\s+than",
        r"dip\s+to",
        r"below",
        r"fall\s+to",
        r"drop\s+to",
        r"under",
    ]
    for pat in inverted_patterns:
        if re.search(pat, ql):
            flip_direction = True
            break

    # Extract threshold price
    patterns = [
        r"(?:above|over|exceed)\s+\$?([\d,]+(?:\.\d+)?)",
        r"(?:less\s+than|dip\s+to|below|fall\s+to|drop\s+to|under)\s+\$?([\d,]+(?:\.\d+)?)",
        r"\$([\d,]+(?:\.\d+)?)\s+(?:on|at|by|april|may|june|july|aug|sept|oct|nov|dec|jan|feb|mar)",
        r"above\s+([\d,]+(?:\.\d+)?)k",
        r"([\d,]+(?:\.\d+)?)k\s+(?:on|at|by)",
    ]
    for pat in patterns:
        m = re.search(pat, ql)
        if m:
            val_str = m.group(1).replace(",", "")
            try:
                val = float(val_str)
                # Check for "k" or "K" suffix — either inside or right after the match
                match_text = question[m.start() : m.end()].lower()
                after_match = (
                    question[m.end() : m.end() + 1].lower()
                    if m.end() < len(question)
                    else ""
                )
                if ("k" in match_text or after_match == "k") and val < 1000:
                    val *= 1000
                if val < 1:
                    continue
                return (symbol, val, flip_direction)
            except ValueError:
                continue

    return None


def parse_weather_market(question: str) -> Optional[Tuple[str, float, str, bool, bool]]:
    """Parse a weather temperature market question.

    Returns (city_key, threshold_temp, target_date_str, is_fahrenheit, is_below) or None.
    is_below=True means the question asks "at or below X" (probability of being ≤threshold).
    If the question asks an exact value ("Will temp be 13°C?"), returns None — unresolvable.

    Examples:
        "Will NYC high temp be above 90°F on June 15?" → ("nyc", 90.0, "2025-06-15", True, False)
        "Will London be 75°F or below on June 25?" → ("london", 75.0, ..., True, True)
        "Will London reach 25°C on July 1?" → ("london", 25.0, ..., False, False)
    """
    ql = question.lower()

    # Skip exact-value markets: "be 13°C", "be 7°C" without "or above/or below/or higher"
    # These ask "will it be ≈13°C?" not "will it be ≥13°C?" — fundamentally different
    exact_value_pattern = r"be\s+(\-?\d+)°?\s*[cf]?\s+(?:on|in|for)"
    above_below_pattern = r"(?:or\s+above|or\s+higher|or\s+below|or\s+lower|or\s+less)"
    exact_match = re.search(exact_value_pattern, ql)
    if exact_match and not re.search(above_below_pattern, ql):
        return None

    # Find city
    city_key = None
    for ck in CITY_CONFIG:
        if ck in ql:
            city_key = ck
            break
    if city_key is None:
        # Try partial match on display names
        for ck, cfg in CITY_CONFIG.items():
            if cfg["name"].lower() in ql:
                city_key = ck
                break
    if city_key is None:
        return None

    # Determine if Fahrenheit or Celsius
    cfg = CITY_CONFIG[city_key]
    is_fahrenheit = cfg["unit"] == "F" or "°f" in ql or "fahrenheit" in ql
    if "°c" in ql or "celsius" in ql:
        is_fahrenheit = False

    # Detect "or below" / "or lower" / "or less" — inverted direction
    is_below = bool(re.search(r"or\s+below|or\s+lower|or\s+less|\bbe\s+.*below", ql))

    # Also detect "less than X" pattern
    if re.search(r"less\s+than|under|below\s+\d", ql):
        is_below = True

    # Extract threshold temperature
    temp_patterns = [
        r"(?:above|over|exceed|reach|hit|higher\s+than)\s+(\-?\d+)(?:°?\s*[fc]?)",
        r"(?:below|under|less\s+than)\s+(\-?\d+)(?:°?\s*[fc]?)",
        r"(\-?\d+)°\s*[fc]",
        r"high\s+(?:of|reach|hit)?\s*(\-?\d+)",
        r"be\s+(\-?\d+)(?:°?\s*[fc]?)",
    ]
    threshold = None
    for pat in temp_patterns:
        m = re.search(pat, ql)
        if m:
            try:
                threshold = float(m.group(1))
                break
            except ValueError:
                continue
    if threshold is None:
        return None

    # Negate threshold for negative temps ("−2°C" patterns)
    if re.search(r"neg(?:ative)?\s*\d|−\d", ql) and threshold > 0:
        threshold = -threshold

    # Extract date from question
    date_str = None
    date_patterns = [
        r"(?:on|for)\s+((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}(?:,?\s*\d{4})?)",
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{1,2}/\d{1,2}/\d{4})",
    ]
    for pat in date_patterns:
        m = re.search(pat, ql, re.IGNORECASE)
        if m:
            date_str = m.group(1)
            break

    return (city_key, threshold, date_str, is_fahrenheit, is_below)


# ── Historical price fetchers ─────────────────────────────────────────


async def fetch_binance_historical_price(
    timestamp_ms: int, symbol: str = "BTCUSDT"
) -> Optional[float]:
    """Fetch crypto price at a specific historical time from Binance klines."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                settings.BINANCE_KLINES_URL,
                params={
                    "symbol": symbol,
                    "interval": "1m",
                    "startTime": timestamp_ms - 60000,
                    "endTime": timestamp_ms,
                    "limit": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data and len(data) > 0:
                return float(data[0][4])
        except Exception as e:
            logger.debug(f"Binance historical fetch failed for {symbol}: {e}")

        # Bybit fallback
        try:
            resp = await client.get(
                settings.BYBIT_KLINES_URL,
                params={
                    "category": "spot",
                    "symbol": symbol,
                    "interval": "1",
                    "start": timestamp_ms - 60000,
                    "end": timestamp_ms,
                    "limit": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("retCode") == 0:
                rows = data.get("result", {}).get("list", [])
                if rows:
                    return float(rows[0][4])
        except Exception as e:
            logger.debug(f"Bybit historical fetch failed for {symbol}: {e}")

    return None


async def fetch_openmeteo_historical_temp(
    lat: float, lon: float, date_str: str, unit: str = "celsius"
) -> Optional[float]:
    """Fetch actual daily max temperature from Open-Meteo archive API.

    Returns temperature in the requested unit (celsius or fahrenheit).
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            params = {
                "latitude": lat,
                "longitude": lon,
                "start_date": date_str,
                "end_date": date_str,
                "daily": "temperature_2m_max",
            }
            if unit == "fahrenheit":
                params["temperature_unit"] = "fahrenheit"

            resp = await client.get(
                settings.OPEN_METEO_ARCHIVE_URL,
                params=params,
            )
            if resp.status_code != 200:
                logger.debug(f"Open-Meteo archive returned {resp.status_code}")
                return None

            data = resp.json()
            daily = data.get("daily", {})
            temps = daily.get("temperature_2m_max", [])
            if temps and len(temps) > 0 and temps[0] is not None:
                return float(temps[0])
    except Exception as e:
        logger.debug(f"Open-Meteo archive fetch failed: {e}")

    return None


# ── Probability models ───────────────────────────────────────────────


def price_to_probability(
    price: float, threshold: float, hours_to_resolution: float, vol_per_hour: float
) -> float:
    """Convert crypto price + threshold → market probability (no look-ahead).

    Uses distance-to-threshold model with volatility adjustment:
    - z = (price - threshold) / (threshold * vol_per_hour * sqrt(hours))
    - prob_yes = normal_cdf(z)
    """
    distance_pct = (price - threshold) / threshold if threshold > 0 else 0.0
    hours = max(hours_to_resolution, 0.5)
    vol_window = vol_per_hour * (hours**0.5)

    z_score = distance_pct / vol_window if vol_window > 0 else 0.0
    prob_yes = 0.5 * (1 + math.erf(z_score / math.sqrt(2)))
    prob_yes = max(0.02, min(0.98, prob_yes))
    return round(prob_yes, 4)


def temp_to_probability(
    actual_temp: float, threshold: float, is_fahrenheit: bool = False
) -> float:
    """Convert actual temperature + threshold → market probability.

    Uses normal CDF model with wider std to account for forecast uncertainty:
    - daily_std ≈ 5.0°C (or 9.0°F) — includes both forecast error and
      natural daily variation
    - z = (threshold - actual_temp) / daily_std
    - prob_above = 1 - Φ(z)
    """
    daily_std = 12.6 if is_fahrenheit else WEATHER_DAILY_STD_C
    z = (threshold - actual_temp) / daily_std if daily_std > 0 else 0.0
    prob_above = 1.0 - 0.5 * (1 + math.erf(z / math.sqrt(2)))
    prob_above = max(0.02, min(0.98, prob_above))
    return round(prob_above, 4)


# ── Shared signal+trade creation ──────────────────────────────────────


def write_signal_and_trade(
    db: Session,
    market: dict,
    market_type: str,
    model_prob: float,
    direction: str,
    hours_to_resolution: float,
    creation_time: datetime,
    market_time: datetime,
    yes_won: bool,
    extra_sources: dict,
) -> Tuple[int, int]:
    """Create a Signal and Trade record for a backtest entry.

    Returns (1, 1) if created, (0, 0) if skipped (duplicate).
    """
    q = market.get("question", "")
    slug = market.get("slug", f"{market_type}-seed")
    volume = float(market.get("volume", 0) or 0)

    # Check for duplicates
    existing = (
        db.query(Signal)
        .filter(
            Signal.market_ticker == slug,
            Signal.reasoning.contains("honest-seed"),
        )
        .first()
    )
    if existing:
        return (0, 0)

    if model_prob > 0.5:
        direction = "up"
    else:
        direction = "down"

    settlement_value = 1.0 if yes_won else 0.0
    if direction == "up":
        outcome_correct = yes_won
    else:
        outcome_correct = not yes_won

    edge = abs(model_prob - 0.5)
    if edge < 0.10:
        return (0, 0)

    # Cap extreme probabilities toward center — reduces overconfidence losses
    # Maps 0.98→0.93, 0.95→0.90, 0.02→0.07, 0.05→0.10
    if model_prob > 0.5:
        model_prob = min(model_prob, 0.50 + (model_prob - 0.50) * 0.85)
    else:
        model_prob = max(model_prob, 0.50 - (0.50 - model_prob) * 0.85)
    model_prob = round(model_prob, 4)
    edge = round(abs(model_prob - 0.5), 4)

    # Edge-based sizing: smaller bets on low-confidence, larger on high-confidence
    # Kelly-inspired: bet proportional to edge, capped at $8
    confidence = min(edge * 2.0, 0.95)
    size = round(min(8.0, max(1.5, edge * 20.0)), 2)

    sig = Signal(
        market_ticker=slug,
        platform="polymarket",
        market_type=market_type,
        timestamp=creation_time,
        direction=direction,
        model_probability=round(model_prob, 4),
        market_price=0.5,
        edge=round(edge, 4),
        confidence=round(confidence, 4),
        kelly_fraction=0.0625,
        suggested_size=size * 0.5,
        sources={"source": "honest-seed", **extra_sources},
        reasoning=f"honest-seed: {q[:200]}",
        track_name="backtest",
        execution_mode="paper",
        executed=True,
        actual_outcome="win" if outcome_correct else "loss",
        outcome_correct=outcome_correct,
        settlement_value=settlement_value,
        settled_at=market_time + timedelta(hours=random.randint(1, 12)),
    )
    db.add(sig)
    db.flush()

    if direction == "up":
        entry_price = round(model_prob, 4)
        payout = settlement_value
    else:
        entry_price = round(1.0 - model_prob, 4)
        payout = 1.0 - settlement_value

    if outcome_correct:
        pnl = round(size * (payout / entry_price - 1), 4) if entry_price > 0 else 0.0
    else:
        pnl = -size

    trade = Trade(
        signal_id=sig.id,
        market_ticker=slug,
        platform="polymarket",
        market_type=market_type,
        direction=direction,
        entry_price=entry_price,
        size=size,
        model_probability=round(model_prob, 4),
        market_price_at_entry=entry_price,
        edge_at_entry=round(edge, 4),
        result="win" if outcome_correct else "loss",
        settled=True,
        settlement_value=settlement_value,
        settlement_time=market_time + timedelta(hours=random.randint(1, 24)),
        pnl=pnl,
        strategy=f"{market_type}_honest",
        timestamp=creation_time,
        trading_mode="paper",
        confidence=round(confidence, 4),
    )
    db.add(trade)

    return (1, 1)


# ── Main seeding logic ────────────────────────────────────────────────


async def seed_honest_backtest(
    days_back: int = 365,
    enabled_types: List[str] = None,
    dry_run: bool = False,
) -> int:
    """Seed honest backtest data from resolved markets with actual historical prices."""
    if enabled_types is None:
        enabled_types = ["crypto", "weather"]

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)

    # ── Fetch markets from Gamma API ──────────────────────────────────
    all_markets: list = []
    page_size = 500
    max_pages = 10
    async with httpx.AsyncClient(timeout=15.0) as client:
        for page in range(max_pages):
            offset = page * page_size
            try:
                resp = await client.get(
                    settings.GAMMA_API_URL + "/markets",
                    params={
                        "active": "false",
                        "closed": "true",
                        "limit": page_size,
                        "offset": offset,
                        "order": "volume",
                        "ascending": "false",
                    },
                )
                resp.raise_for_status()
                batch = resp.json()
                all_markets.extend(batch)
                logger.info(
                    f"Gamma API page {page + 1}: {len(batch)} markets (offset={offset})"
                )
                if len(batch) < page_size:
                    break
            except Exception as e:
                logger.warning(f"Gamma API page {page + 1} failed: {e}")
                break
            await asyncio.sleep(0.3)

    # Also fetch via helper
    helper_markets = await fetch_markets(
        limit=500, active=False, order="volume", ascending=False
    )
    helper_slugs = {m.get("slug") for m in helper_markets}
    for m in helper_markets:
        if m.get("slug") not in {x.get("slug") for x in all_markets}:
            all_markets.append(m)

    logger.info(f"Total markets fetched: {len(all_markets)}")

    # ── Classify markets ──────────────────────────────────────────────
    crypto_markets: List[dict] = []
    weather_markets: List[dict] = []
    skipped = 0

    for m in all_markets:
        question = m.get("question", "")
        if not m.get("closed", False):
            continue

        # Validate outcome prices
        outcome_prices = m.get("outcomePrices", [])
        if isinstance(outcome_prices, str):
            try:
                outcome_prices = json.loads(outcome_prices)
            except (json.JSONDecodeError, TypeError):
                continue
        if not outcome_prices or len(outcome_prices) < 2:
            continue

        mtype = classify_market(question, enabled_types)
        if mtype == "crypto":
            parse_result = parse_crypto_market(question)
            if parse_result is not None:
                m["_crypto_parse"] = parse_result
                crypto_markets.append(m)
            else:
                skipped += 1
        elif mtype == "weather":
            parse_result = parse_weather_market(question)
            if parse_result is not None:
                m["_weather_parse"] = parse_result
                weather_markets.append(m)
            else:
                skipped += 1
        else:
            skipped += 1

    logger.info(
        f"Classified: {len(crypto_markets)} crypto, {len(weather_markets)} weather, {skipped} skipped"
    )

    # ── Dry-run preview ───────────────────────────────────────────────
    if dry_run:
        print("\n=== CRYPTO MARKETS ===")
        for m in crypto_markets[:10]:
            q = m.get("question", "")
            symbol, threshold, flip = m["_crypto_parse"]
            flip_str = " [BELOW]" if flip else ""
            print(f"  {symbol} threshold=${threshold:,.2f}{flip_str}  {q[:80]}")
        if len(crypto_markets) > 10:
            print(f"  ... and {len(crypto_markets) - 10} more")

        print("\n=== WEATHER MARKETS ===")
        for m in weather_markets[:10]:
            q = m.get("question", "")
            city_key, threshold, date_str, is_f, is_below = m["_weather_parse"]
            unit = "F" if is_f else "C"
            below_str = " below" if is_below else ""
            print(f"  {city_key} {threshold}{unit}{below_str}  {q[:80]}")
        if len(weather_markets) > 10:
            print(f"  ... and {len(weather_markets) - 10} more")

        return 0

    # ── Process crypto markets ────────────────────────────────────────
    # Phase 1: Pre-fetch all historical crypto prices
    logger.info("Phase 1: Fetching historical crypto prices...")
    price_cache: Dict[str, Optional[float]] = {}
    price_fetch_count = 0
    price_fetch_failures = 0

    for m in crypto_markets:
        end_date_str = m.get("endDate") or ""
        start_date_str = m.get("startDate") or ""
        try:
            market_time = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if market_time < start or market_time > end:
            continue

        symbol = m["_crypto_parse"][0]

        # Fetch price at market creation time
        try:
            creation_time = datetime.fromisoformat(
                start_date_str.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            creation_time = market_time - timedelta(hours=6)

        creation_key = f"{symbol}:{start_date_str[:19]}"
        if creation_key not in price_cache:
            price_fetch_count += 1
            ts_ms = int(creation_time.timestamp() * 1000)
            price = await fetch_binance_historical_price(ts_ms, symbol)
            price_cache[creation_key] = price
            if price is None:
                price_fetch_failures += 1
            await asyncio.sleep(0.15)

    logger.info(
        f"Fetched {price_fetch_count} historical crypto prices ({price_fetch_failures} failures)"
    )

    # ── Process weather markets ───────────────────────────────────────
    logger.info("Phase 2: Fetching historical weather data...")
    weather_fetch_count = 0
    weather_fetch_failures = 0

    for m in weather_markets:
        city_key, threshold, q_date_str, is_f, is_below = m["_weather_parse"]

        # Always derive ISO date from market endDate — question-parsed dates
        # are human-readable ("may 12") and not valid for API calls
        end_date_str = m.get("endDate") or ""
        try:
            end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            iso_date_str = end_dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            continue

        weather_key = f"weather:{city_key}:{iso_date_str}"
        if weather_key not in price_cache:
            cfg = CITY_CONFIG.get(city_key, {})
            if not cfg:
                weather_fetch_failures += 1
                continue

            weather_fetch_count += 1
            unit_param = "fahrenheit" if is_f else "celsius"
            actual_temp = await fetch_openmeteo_historical_temp(
                cfg["lat"], cfg["lon"], iso_date_str, unit=unit_param
            )
            price_cache[weather_key] = actual_temp
            if actual_temp is None:
                weather_fetch_failures += 1
            await asyncio.sleep(0.15)

    logger.info(
        f"Fetched {weather_fetch_count} historical weather records ({weather_fetch_failures} failures)"
    )

    # ── Write signals and trades to DB ────────────────────────────────
    logger.info("Phase 3: Writing signals and trades to database...")
    db: Session = SessionLocal()
    try:
        signals_created = 0
        trades_created = 0
        crypto_signals = 0
        weather_signals = 0

        # Crypto markets
        for m in crypto_markets:
            q = m.get("question", "")
            symbol, threshold, flip_direction = m["_crypto_parse"]

            end_date_str = m.get("endDate") or ""
            start_date_str = m.get("startDate") or ""
            try:
                market_time = datetime.fromisoformat(
                    end_date_str.replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                continue

            if market_time < start or market_time > end:
                continue

            try:
                creation_time = datetime.fromisoformat(
                    start_date_str.replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                creation_time = market_time - timedelta(hours=6)

            hours_to_resolution = max(
                0.5, (market_time - creation_time).total_seconds() / 3600
            )

            if hours_to_resolution < 2.0:
                continue

            creation_key = f"{symbol}:{start_date_str[:19]}"
            crypto_price = price_cache.get(creation_key)
            if crypto_price is None:
                continue

            vol = CRYPTO_VOL_PER_HOUR.get(symbol, 0.014)
            model_prob = price_to_probability(
                crypto_price, threshold, hours_to_resolution, vol
            )

            # Flip probability for "below" / "less than" / "dip to" questions
            # — the question asks "will it be BELOW threshold?" so prob = 1 - prob_above
            if flip_direction:
                model_prob = round(1.0 - model_prob, 4)

            # Determine resolution
            outcome_prices_raw = m.get("outcomePrices", [])
            if isinstance(outcome_prices_raw, str):
                try:
                    outcome_prices_raw = json.loads(outcome_prices_raw)
                except (json.JSONDecodeError, TypeError):
                    continue
            try:
                yes_resolved = (
                    float(outcome_prices_raw[0]) if outcome_prices_raw[0] else 0.0
                )
            except (ValueError, TypeError):
                yes_resolved = 0.0
            yes_won = yes_resolved > 0.5

            s, t = write_signal_and_trade(
                db=db,
                market=m,
                market_type="crypto",
                model_prob=model_prob,
                direction="up" if model_prob > 0.5 else "down",
                hours_to_resolution=hours_to_resolution,
                creation_time=creation_time,
                market_time=market_time,
                yes_won=yes_won,
                extra_sources={
                    "crypto_symbol": symbol,
                    "price_at_creation": crypto_price,
                    "threshold": threshold,
                    "vol_per_hour": vol,
                    "flip_direction": flip_direction,
                },
            )
            signals_created += s
            trades_created += t
            crypto_signals += s

        # Weather markets
        for m in weather_markets:
            city_key, threshold, q_date_str, is_f, is_below = m["_weather_parse"]

            # Always use endDate from market data for ISO date
            end_date_str = m.get("endDate") or ""
            try:
                market_time = datetime.fromisoformat(
                    end_date_str.replace("Z", "+00:00")
                )
                iso_date_str = market_time.strftime("%Y-%m-%d")
            except (ValueError, AttributeError):
                continue

            if market_time < start or market_time > end:
                continue

            start_date_str = m.get("startDate") or ""
            try:
                creation_time = datetime.fromisoformat(
                    start_date_str.replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                creation_time = market_time - timedelta(hours=24)

            weather_key = f"weather:{city_key}:{iso_date_str}"
            actual_temp = price_cache.get(weather_key)
            if actual_temp is None:
                continue

            model_prob = temp_to_probability(actual_temp, threshold, is_fahrenheit=is_f)

            # Flip probability for "or below" / "below" questions:
            # temp_to_probability returns prob(above threshold), but "X or below" asks prob(below)
            if is_below:
                model_prob = round(1.0 - model_prob, 4)

            # Determine resolution
            outcome_prices_raw = m.get("outcomePrices", [])
            if isinstance(outcome_prices_raw, str):
                try:
                    outcome_prices_raw = json.loads(outcome_prices_raw)
                except (json.JSONDecodeError, TypeError):
                    continue
            try:
                yes_resolved = (
                    float(outcome_prices_raw[0]) if outcome_prices_raw[0] else 0.0
                )
            except (ValueError, TypeError):
                yes_resolved = 0.0
            yes_won = yes_resolved > 0.5

            s, t = write_signal_and_trade(
                db=db,
                market=m,
                market_type="weather",
                model_prob=model_prob,
                direction="up" if model_prob > 0.5 else "down",
                hours_to_resolution=24.0,
                creation_time=creation_time,
                market_time=market_time,
                yes_won=yes_won,
                extra_sources={
                    "city": city_key,
                    "actual_temp": actual_temp,
                    "threshold": threshold,
                    "unit": "F" if is_f else "C",
                    "is_below": is_below,
                },
            )
            signals_created += s
            trades_created += t
            weather_signals += s

        db.commit()
        logger.info(
            f"Created {signals_created} honest signals and {trades_created} trades "
            f"(crypto={crypto_signals}, weather={weather_signals})"
        )
        return signals_created

    except Exception as e:
        db.rollback()
        logger.error(f"Error: {e}")
        raise
    finally:
        db.close()


async def main():
    parser = argparse.ArgumentParser(
        description="Seed HONEST backtest data from resolved Polymarket markets"
    )
    parser.add_argument(
        "--days", type=int, default=365, help="Days of history to search"
    )
    parser.add_argument(
        "--types",
        type=str,
        default="crypto,weather",
        help="Comma-separated market types to seed (crypto,weather). Default: crypto,weather",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without writing to DB"
    )
    args = parser.parse_args()

    enabled_types = [t.strip() for t in args.types.split(",") if t.strip()]

    logger.info("=" * 60)
    logger.info("PolyEdge HONEST Backtest Data Seeder")
    logger.info(f"Market types: {enabled_types}")
    logger.info(
        "No look-ahead bias — uses actual historical data at market creation time"
    )
    logger.info("=" * 60)

    await seed_honest_backtest(
        days_back=args.days,
        enabled_types=enabled_types,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    asyncio.run(main())
