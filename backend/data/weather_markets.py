"""Weather temperature market fetcher from Polymarket."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

from backend.core.market_scanner import fetch_markets_by_keywords
from backend.data.market_types import UnifiedMarketView

from loguru import logger

# Month name to number
MONTH_MAP = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_DEFAULT_WEATHER_KEYWORDS = [
    "temperature",
    "weather",
    "degrees fahrenheit",
    "high temperature",
    "low temperature",
]


@dataclass
class WeatherMarket:
    """A weather temperature prediction market."""

    slug: str
    market_id: str
    platform: str
    title: str
    city_key: str
    city_name: str
    target_date: date
    threshold_f: float  # Temperature threshold in Fahrenheit
    metric: str  # "high" or "low"
    direction: str  # "above" or "below"
    yes_price: float  # Price of YES outcome (0-1)
    no_price: float  # Price of NO outcome (0-1)
    volume: float = 0.0
    closed: bool = False

    def to_unified(self) -> UnifiedMarketView:
        """
        Convert to UnifiedMarketView for API responses.

        This is a lightweight adapter, not a base class inheritance pattern.
        BtcMarket and WeatherMarket remain independent domain models.
        """
        # Convert date to datetime for closes_at (end of day UTC)
        closes_at = datetime.combine(self.target_date, datetime.min.time()).replace(
            tzinfo=None
        )

        return UnifiedMarketView(
            slug=self.slug,
            platform=self.platform,
            title=self.title,
            yes_price=self.yes_price,
            no_price=self.no_price,
            volume=self.volume,
            closes_at=closes_at,
            extra={
                "market_id": self.market_id,
                "city_key": self.city_key,
                "city_name": self.city_name,
                "target_date": self.target_date.isoformat(),
                "threshold_f": self.threshold_f,
                "metric": self.metric,
                "direction": self.direction,
                "type": "weather-temperature",
            },
        )


def _extract_city_from_title(title: str) -> Optional[str]:
    """
    Extract a city name from a weather market title using regex.

    Handles patterns like:
    - "Will the high temperature in New York exceed 75°F?"
    - "NYC high temperature above 80°F"
    - "Chicago daily high over 60°F"
    - "Will Miami's low be above 65°F?"
    - "Temperature in Denver above 70°F"
    - "High temperature in Los Angeles above 90°F"
    - "Will the high in San Francisco exceed 75°F?"

    Returns the extracted city name (proper-cased), or None.
    """
    import re as _re

    # Words to skip when they appear after "in"
    _SKIP_WORDS = frozenset(
        {
            "The",
            "This",
            "Which",
            "What",
            "How",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
            "January",
            "February",
            "Fahrenheit",
            "Celsius",
            "Addition",
            "Total",
            "Fact",
            "Order",
            "General",
        }
    )

    # Pattern A: "<CityName>'s" — e.g. "Miami's low", "Dallas's high"
    # Match a single capitalized word directly before 's.
    # Multi-word possessives (e.g. "New York's") handled by "in" pattern instead.
    m = _re.search(r"(?:^|\s)([A-Z][a-z]+)'s\b", title)
    if m:
        candidate = m.group(1).strip()
        # Skip common auxiliary verbs
        if candidate.lower() not in {"will", "can", "does", "is", "was", "it"}:
            return candidate

    # Pattern B: "in <CityName>" — most common (handles multi-word cities)
    m = _re.search(r"\bin\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)", title)
    if m:
        candidate = m.group(1).strip()
        if candidate not in _SKIP_WORDS:
            return candidate

    # Pattern C: Title starts with city name (handles ALL-CAPS like "NYC")
    # e.g. "NYC high temperature above 80°F" or "Chicago daily high over 60°F"
    m = _re.match(
        r"^([A-Z][A-Za-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:daily|high|low|temperature|temp)",
        title,
    )
    if m:
        return m.group(1).strip()

    return None


def _parse_weather_market_title(title: str) -> Optional[dict]:
    """
    Parse a weather market title to extract city, threshold, metric, date.

    City names are extracted directly from the title via regex — no
    hardcoded CITY_CONFIG dependency.  Unknown cities are resolved
    to coordinates at forecast-fetch time via geocoding.

    Handles patterns like:
    - "Will the high temperature in New York exceed 75°F on March 5?"
    - "NYC high temperature above 80°F on March 10, 2026"
    - "Chicago daily high over 60°F on March 3"
    - "Will Miami's low be above 65°F on March 7?"
    - "Temperature in Denver above 70°F on March 5, 2026"
    """
    title_lower = title.lower()

    # Must be temperature-related
    if not any(
        kw in title_lower
        for kw in ["temperature", "temp", "°f", "degrees", "high", "low"]
    ):
        return None

    # ── Extract city name from title ──────────────────────────────────
    city_name_raw = _extract_city_from_title(title)
    if not city_name_raw:
        return None

    # Resolve to a city_key: check static config first, then use slug
    from backend.data.weather import CITY_CONFIG, _slugify_city

    city_key = None
    city_name = city_name_raw

    # Try matching against static CITY_CONFIG names/keys
    for key, cfg in CITY_CONFIG.items():
        cfg_name_lower = cfg["name"].lower()
        raw_lower = city_name_raw.lower()
        # Exact name match or slug match
        if cfg_name_lower == raw_lower or key == _slugify_city(city_name_raw):
            city_key = key
            city_name = cfg["name"]
            break
        # Partial match: "New York" matches "New York City"
        if raw_lower in cfg_name_lower or cfg_name_lower in raw_lower:
            city_key = key
            city_name = cfg["name"]
            break

    # If not in static config, slugify for use as dynamic key
    if not city_key:
        city_key = _slugify_city(city_name_raw)

    # Extract threshold temperature
    temp_match = re.search(r"(\d+)\s*°?\s*f", title_lower)
    if not temp_match:
        temp_match = re.search(r"(\d+)\s*degrees", title_lower)
    if not temp_match:
        return None
    threshold_f = float(temp_match.group(1))

    # Determine metric (high vs low)
    metric = "high"  # default
    if "low" in title_lower:
        metric = "low"

    # Determine direction
    direction = "above"  # default
    if any(kw in title_lower for kw in ["below", "under", "less than", "drop below"]):
        direction = "below"

    # Extract date
    target_date = _extract_date(title_lower)
    if not target_date:
        return None

    return {
        "city_key": city_key,
        "city_name": city_name,
        "threshold_f": threshold_f,
        "metric": metric,
        "direction": direction,
        "target_date": target_date,
    }


def _extract_date(text: str) -> Optional[date]:
    """Extract a date from market title text."""
    today = date.today()

    # Build month name pattern for precise matching
    month_names = "|".join(MONTH_MAP.keys())

    # Pattern: "March 5, 2026" or "March 5 2026" or "March 5"
    for match in re.finditer(
        rf"({month_names})\s+(\d{{1,2}})(?:\s*,?\s*(\d{{4}}))?", text
    ):
        month_str = match.group(1)
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year

        month = MONTH_MAP.get(month_str)
        if month and 1 <= day <= 31:
            try:
                return date(year, month, day)
            except ValueError:
                continue

    # Pattern: "3/5/2026" or "03/05"
    match = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?", text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        try:
            return date(year, month, day)
        except ValueError:
            logger.debug("weather_markets: invalid date parsed")

    return None


async def fetch_polymarket_weather_markets(
    city_keys: Optional[List[str]] = None,
    keywords: Optional[List[str]] = None,
) -> List[WeatherMarket]:
    """
    Search Polymarket for weather temperature markets using keyword-based scanning.
    Dynamically geocodes and registers any city not already in CITY_CONFIG.
    """
    if keywords is None:
        keywords = _DEFAULT_WEATHER_KEYWORDS

    markets: List[WeatherMarket] = []
    seen_ids: set = set()

    try:
        scanner_results = await fetch_markets_by_keywords(keywords)
        for info in scanner_results:
            market = _parse_scanner_market(info, city_keys)
            if market and market.market_id not in seen_ids:
                # Ensure the city is registered (geocoded if new)
                await _ensure_market_city_registered(market)
                seen_ids.add(market.market_id)
                markets.append(market)
    except Exception as e:
        logger.warning(f"Failed to fetch weather markets: {e}")

    logger.info(f"Found {len(markets)} weather temperature markets")
    return markets


async def _ensure_market_city_registered(market: WeatherMarket) -> None:
    """
    If the market's city_key is not yet in any registry, geocode and
    register it so that forecast fetches will work.
    """
    from backend.data.weather import get_city_config, ensure_city_registered

    if get_city_config(market.city_key) is None:
        await ensure_city_registered(market.city_name)


def _parse_scanner_market(
    info,
    city_keys: Optional[List[str]] = None,
) -> Optional[WeatherMarket]:
    """Parse a MarketInfo from the scanner into a WeatherMarket if it's a temp market."""
    question = info.question
    if not question:
        return None

    parsed = _parse_weather_market_title(question)
    if not parsed:
        return None

    # Filter by requested cities
    if city_keys and parsed["city_key"] not in city_keys:
        return None

    # Only trade markets for dates in the future (or today)
    if parsed["target_date"] < date.today():
        return None

    yes_price = info.yes_price
    no_price = info.no_price

    # Skip near-resolved markets
    if yes_price > 0.98 or yes_price < 0.02:
        return None

    return WeatherMarket(
        slug=info.slug,
        market_id=info.ticker,
        platform="polymarket",
        title=question,
        city_key=parsed["city_key"],
        city_name=parsed["city_name"],
        target_date=parsed["target_date"],
        threshold_f=parsed["threshold_f"],
        metric=parsed["metric"],
        direction=parsed["direction"],
        yes_price=yes_price,
        no_price=no_price,
        volume=info.volume,
    )
