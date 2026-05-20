"""Weather data fetcher using Open-Meteo Ensemble API and NWS observations."""

import httpx
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional
import statistics
import time

from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.core.external_rate_limiter import ExternalRateLimiter
from backend.config import settings

from loguru import logger

# Circuit breakers for weather API calls
openmeteo_breaker = CircuitBreaker("open_meteo")
nws_breaker = CircuitBreaker("nws_api", failure_threshold=5, recovery_timeout=60.0)
noaa_metar_breaker = CircuitBreaker(
    "noaa_metar", failure_threshold=5, recovery_timeout=60.0
)

# Rate limiter for weather API calls (30 requests/min default)
_weather_rate_limiter = ExternalRateLimiter(
    name="weather",
    max_calls_per_minute=getattr(settings, "RATE_LIMIT_WEATHER", 30),
)

# City configurations — AIRPORT coordinates matching METAR stations used by Polymarket
# Using airport lat/lon eliminates the systematic 3-8°F error from city-center coords
# These serve as a high-quality base set; new cities are added dynamically via geocoding.
CITY_CONFIG: Dict[str, dict] = {
    # US cities — airport coordinates (NOT city centers)
    "nyc": {
        "name": "New York City",
        "lat": 40.7772,
        "lon": -73.8726,
        "nws_station": "KLGA",
        "unit": "F",
    },  # LaGuardia
    "chicago": {
        "name": "Chicago",
        "lat": 41.9742,
        "lon": -87.9073,
        "nws_station": "KORD",
        "unit": "F",
    },  # O'Hare
    "miami": {
        "name": "Miami",
        "lat": 25.7959,
        "lon": -80.2870,
        "nws_station": "KMIA",
        "unit": "F",
    },  # Miami Intl
    "dallas": {
        "name": "Dallas",
        "lat": 32.8471,
        "lon": -96.8518,
        "nws_station": "KDAL",
        "unit": "F",
    },  # Love Field (NOT DFW!)
    "seattle": {
        "name": "Seattle",
        "lat": 47.4502,
        "lon": -122.3088,
        "nws_station": "KSEA",
        "unit": "F",
    },  # Sea-Tac
    "atlanta": {
        "name": "Atlanta",
        "lat": 33.6407,
        "lon": -84.4277,
        "nws_station": "KATL",
        "unit": "F",
    },  # Hartsfield
    "los_angeles": {
        "name": "Los Angeles",
        "lat": 33.9425,
        "lon": -118.4081,
        "nws_station": "KLAX",
        "unit": "F",
    },  # LAX
    "denver": {
        "name": "Denver",
        "lat": 39.8561,
        "lon": -104.6737,
        "nws_station": "KDEN",
        "unit": "F",
    },  # Denver Intl
    # European cities — airport coordinates
    "london": {
        "name": "London",
        "lat": 51.5048,
        "lon": 0.0495,
        "nws_station": "EGLC",
        "unit": "C",
    },  # London City
    "paris": {
        "name": "Paris",
        "lat": 48.9962,
        "lon": 2.5979,
        "nws_station": "LFPG",
        "unit": "C",
    },  # CDG
    "munich": {
        "name": "Munich",
        "lat": 48.3537,
        "lon": 11.7750,
        "nws_station": "EDDM",
        "unit": "C",
    },  # Munich Intl
    "ankara": {
        "name": "Ankara",
        "lat": 40.1281,
        "lon": 32.9951,
        "nws_station": "LTAC",
        "unit": "C",
    },  # Esenboga
    # Asian cities
    "seoul": {
        "name": "Seoul",
        "lat": 37.4691,
        "lon": 126.4505,
        "nws_station": "RKSI",
        "unit": "C",
    },  # Incheon
    "tokyo": {
        "name": "Tokyo",
        "lat": 35.7647,
        "lon": 140.3864,
        "nws_station": "RJTT",
        "unit": "C",
    },  # Haneda
    "shanghai": {
        "name": "Shanghai",
        "lat": 31.1443,
        "lon": 121.8083,
        "nws_station": "ZSPD",
        "unit": "C",
    },  # Pudong
    "singapore": {
        "name": "Singapore",
        "lat": 1.3502,
        "lon": 103.9940,
        "nws_station": "WSSS",
        "unit": "C",
    },  # Changi
    # Other regions
    "toronto": {
        "name": "Toronto",
        "lat": 43.6772,
        "lon": -79.6306,
        "nws_station": "CYYZ",
        "unit": "C",
    },  # Pearson
    "sao_paulo": {
        "name": "Sao Paulo",
        "lat": -23.4356,
        "lon": -46.4731,
        "nws_station": "SBGR",
        "unit": "C",
    },  # Guarulhos
    "buenos_aires": {
        "name": "Buenos Aires",
        "lat": -34.8222,
        "lon": -58.5358,
        "nws_station": "SAEZ",
        "unit": "C",
    },  # Ezeiza
    "wellington": {
        "name": "Wellington",
        "lat": -41.3272,
        "lon": 174.8052,
        "nws_station": "NZWN",
        "unit": "C",
    },  # Wellington Intl
}

# ── Dynamic city registry ──────────────────────────────────────────────
# Cities discovered at runtime from Polymarket titles that are NOT in
# the static CITY_CONFIG.  Populated by `register_city()` / `geocode_city()`.

_dynamic_cities: Dict[str, dict] = {}
_geocode_cache: Dict[str, Optional[dict]] = {}  # city_name -> geocoded result (or None)


def _slugify_city(name: str) -> str:
    """Normalize a city name to a slug key (lowercase, underscores)."""
    slug = name.lower().strip()
    # Remove diacritics (e.g. São Paulo -> Sao Paulo)
    slug = unicodedata.normalize("NFKD", slug).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    return slug


def get_city_config(city_key: str) -> Optional[dict]:
    """
    Look up a city by key, checking both static CITY_CONFIG and the
    dynamic registry.  Returns the config dict or None.
    """
    if city_key in CITY_CONFIG:
        return CITY_CONFIG[city_key]
    return _dynamic_cities.get(city_key)


def all_known_city_keys() -> List[str]:
    """Return keys from both static and dynamic registries."""
    return list(CITY_CONFIG.keys()) + list(_dynamic_cities.keys())


def register_city(key: str, name: str, lat: float, lon: float, unit: str = "F") -> dict:
    """
    Register a new city in the dynamic registry at runtime.
    Returns the config dict that was stored.
    """
    cfg = {"name": name, "lat": lat, "lon": lon, "unit": unit}
    _dynamic_cities[key] = cfg
    logger.info(f"Registered dynamic city: {name} ({key}) at ({lat}, {lon})")
    return cfg


async def geocode_city(city_name: str) -> Optional[dict]:
    """
    Geocode a city name using the free Open-Meteo Geocoding API.
    Returns {"lat": float, "lon": float} or None.
    Results are cached in-memory for the process lifetime.
    """
    if city_name in _geocode_cache:
        return _geocode_cache[city_name]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                settings.OPEN_METEO_GEOCODING_URL,
                params={
                    "name": city_name,
                    "count": 1,
                    "language": "en",
                    "format": "json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                _geocode_cache[city_name] = None
                logger.debug(f"Geocoding returned no results for '{city_name}'")
                return None
            top = results[0]
            result = {"lat": float(top["latitude"]), "lon": float(top["longitude"])}
            _geocode_cache[city_name] = result
            logger.info(f"Geocoded '{city_name}' -> ({result['lat']}, {result['lon']})")
            return result
    except Exception as e:
        logger.warning(f"Geocoding failed for '{city_name}': {e}")
        _geocode_cache[city_name] = None
        return None


async def ensure_city_registered(city_name: str) -> Optional[str]:
    """
    Given a human-readable city name, return its slug key.
    If the city is not yet in any registry, geocode it and register it.
    Returns None if geocoding fails.
    """
    slug = _slugify_city(city_name)
    # Check static config by slug
    if slug in CITY_CONFIG:
        return slug
    # Check static config by name match
    for key, cfg in CITY_CONFIG.items():
        if cfg["name"].lower() == city_name.lower():
            return key
    # Check dynamic registry
    if slug in _dynamic_cities:
        return slug
    # Geocode and register
    coords = await geocode_city(city_name)
    if coords is None:
        return None
    # Heuristic: if latitude > 23 and < 50 and lon < -50, probably US → Fahrenheit
    unit = "F" if -130 < coords["lon"] < -50 and 23 < coords["lat"] < 50 else "C"
    register_city(slug, city_name, coords["lat"], coords["lon"], unit)
    return slug


@dataclass
class EnsembleForecast:
    """Ensemble weather forecast with per-member data."""

    city_key: str
    city_name: str
    target_date: date
    member_highs: List[float]  # Daily max temps (F) per ensemble member
    member_lows: List[float]  # Daily min temps (F) per ensemble member
    mean_high: float = 0.0
    std_high: float = 0.0
    mean_low: float = 0.0
    std_low: float = 0.0
    num_members: int = 0
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if self.member_highs:
            self.mean_high = statistics.mean(self.member_highs)
            self.std_high = (
                statistics.stdev(self.member_highs)
                if len(self.member_highs) > 1
                else 0.0
            )
            self.num_members = len(self.member_highs)
        if self.member_lows:
            self.mean_low = statistics.mean(self.member_lows)
            self.std_low = (
                statistics.stdev(self.member_lows) if len(self.member_lows) > 1 else 0.0
            )

    def probability_high_above(self, threshold_f: float) -> float:
        """Fraction of ensemble members with daily high above threshold."""
        if not self.member_highs:
            return 0.5
        count = sum(1 for h in self.member_highs if h > threshold_f)
        return count / len(self.member_highs)

    def probability_high_below(self, threshold_f: float) -> float:
        """Fraction of ensemble members with daily high below threshold."""
        return 1.0 - self.probability_high_above(threshold_f)

    def probability_low_above(self, threshold_f: float) -> float:
        """Fraction of ensemble members with daily low above threshold."""
        if not self.member_lows:
            return 0.5
        count = sum(1 for m in self.member_lows if m > threshold_f)
        return count / len(self.member_lows)

    def probability_low_below(self, threshold_f: float) -> float:
        """Fraction of ensemble members with daily low below threshold."""
        return 1.0 - self.probability_low_above(threshold_f)

    @property
    def ensemble_agreement(self) -> float:
        """How one-sided the ensemble is (0.5 = split, 1.0 = unanimous)."""
        if not self.member_highs:
            return 0.5
        median = statistics.median(self.member_highs)
        above = sum(1 for h in self.member_highs if h > median)
        frac = above / len(self.member_highs)
        return max(frac, 1 - frac)


# Simple cache: (city_key, target_date_str) -> (timestamp, EnsembleForecast)
_forecast_cache: Dict[str, tuple] = {}
_CACHE_TTL = 900  # 15 minutes


def _celsius_to_fahrenheit(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


# WARNING: This function is for prediction purposes only — NOT for settlement resolution.
async def fetch_ensemble_forecast(
    city_key: str, target_date: Optional[date] = None
) -> Optional[EnsembleForecast]:
    """
    Fetch ensemble forecast from Open-Meteo Ensemble API (free, 31-member GFS).
    Returns per-member daily max/min temperatures in Fahrenheit.
    Works with both static CITY_CONFIG and dynamically registered cities.
    """
    city = get_city_config(city_key)
    if city is None:
        logger.warning(f"Unknown city key: {city_key}")
        return None

    if target_date is None:
        target_date = date.today()

    cache_key = f"{city_key}_{target_date.isoformat()}"
    now = time.time()
    if cache_key in _forecast_cache:
        cached_time, cached_forecast = _forecast_cache[cache_key]
        if now - cached_time < _CACHE_TTL:
            return cached_forecast

    try:
        city_unit = city.get("unit", "F")
        req_params = {
            "latitude": city["lat"],
            "longitude": city["lon"],
            "daily": "temperature_2m_max,temperature_2m_min",
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
            "models": "gfs_seamless",
        }
        if city_unit == "F":
            req_params["temperature_unit"] = "fahrenheit"

        async def _do_fetch():
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Open-Meteo Ensemble API — GFS ensemble with 31 members
                # For non-US cities (unit="C"), fetch Celsius and convert to Fahrenheit locally
                response = await client.get(
                    settings.OPEN_METEO_ENSEMBLE_URL,
                    params=req_params,
                )
                response.raise_for_status()
                return response.json()

        data = await openmeteo_breaker.call(_do_fetch)

        daily = data.get("daily", {})

        # Open-Meteo returns each ensemble member as a separate key:
        #   temperature_2m_max (control), temperature_2m_max_member01, ..., _member30
        # Collect all member values for highs and lows
        # All member temps stored in Fahrenheit regardless of source unit
        member_highs = []
        member_lows = []

        for key, values in daily.items():
            if not isinstance(values, list) or not values:
                continue
            val = values[0]
            if val is None:
                continue
            if "temperature_2m_max" in key:
                temp_f = (
                    float(val)
                    if city_unit == "F"
                    else _celsius_to_fahrenheit(float(val))
                )
                member_highs.append(temp_f)
            elif "temperature_2m_min" in key:
                temp_f = (
                    float(val)
                    if city_unit == "F"
                    else _celsius_to_fahrenheit(float(val))
                )
                member_lows.append(temp_f)

        if not member_highs:
            logger.warning(f"No ensemble data for {city_key} on {target_date}")
            return None

        forecast = EnsembleForecast(
            city_key=city_key,
            city_name=city["name"],
            target_date=target_date,
            member_highs=member_highs,
            member_lows=member_lows,
        )

        _forecast_cache[cache_key] = (now, forecast)
        logger.info(
            f"Ensemble forecast for {city['name']} on {target_date}: "
            f"High {forecast.mean_high:.1f}F +/- {forecast.std_high:.1f}F "
            f"({forecast.num_members} members)"
        )

        return forecast

    except CircuitOpenError:
        logger.warning(
            "Open-Meteo circuit OPEN, skipping ensemble forecast for %s", city_key
        )
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch ensemble forecast for {city_key}: {e}")
        return None


async def fetch_nws_observed_temperature(
    city_key: str, target_date: Optional[date] = None
) -> Optional[Dict[str, float]]:
    """
    Fetch observed temperature from NWS API for settlement.
    Returns dict with 'high' and 'low' in Fahrenheit, or None if not available.
    """
    city = get_city_config(city_key)
    if city is None:
        return None
    if target_date is None:
        target_date = date.today()

    async def _fetch_nws():
        async with httpx.AsyncClient(timeout=15.0) as client:
            # NWS observations endpoint
            station = city["nws_station"]
            url = f"{settings.NWS_BASE_URL}/stations/{station}/observations"
            headers = {"User-Agent": "(trading-bot, contact@example.com)"}

            # Get observations for the target date
            start = datetime.combine(target_date, datetime.min.time()).isoformat() + "Z"
            end = (
                datetime.combine(
                    target_date + timedelta(days=1), datetime.min.time()
                ).isoformat()
                + "Z"
            )

            response = await client.get(
                url, params={"start": start, "end": end}, headers=headers
            )
            response.raise_for_status()
            return response.json()

    try:
        data = await _weather_rate_limiter.call(nws_breaker.call, _fetch_nws)

        features = data.get("features", [])
        if not features:
            return None

        temps = []
        for obs in features:
            props = obs.get("properties", {})
            temp_c = props.get("temperature", {}).get("value")
            if temp_c is not None:
                temps.append(_celsius_to_fahrenheit(temp_c))

        if not temps:
            return None

        return {
            "high": max(temps),
            "low": min(temps),
        }

    except CircuitOpenError:
        logger.warning("NWS circuit OPEN, skipping observation fetch for %s", city_key)
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch NWS observations for {city_key}: {e}")
        return None


async def fetch_noaa_metar(station_id: str, date: str) -> Optional[dict]:
    """Fetch METAR observation for a specific station and date from NOAA Aviation Weather.

    Uses the NOAA Aviation Weather public API (no key required).
    Selects the observation nearest midday to represent the daily condition.

    Args:
        station_id: 4-char ICAO station code (e.g. "KLGA", "KORD").
        date: ISO date string "YYYY-MM-DD".

    Returns:
        dict with keys: station_id, time, temp_c, wind_kt, visibility_mi, weather.
        Returns None if the API fails or no observations exist for that date.
    """
    NOAA_METAR_URL = "https://aviationweather.gov/cgi-bin/data/api/v1/aoaws/metar"
    params = {
        "dataSource": "metars",
        "requestType": "retrieve",
        "format": "json",
        "stationString": station_id,
        "startTime": f"{date}T00:00Z",
        "endTime": f"{date}T23:59Z",
    }

    async def _fetch_metar():
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(NOAA_METAR_URL, params=params)
            if resp.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"METAR HTTP {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            return resp.json()

    try:
        data = await _weather_rate_limiter.call(noaa_metar_breaker.call, _fetch_metar)

        features = data.get("features", [])
        if not features:
            return None

        def _nearest_noon_hour(obs: dict) -> int:
            ts = obs.get("properties", {}).get("timestamp", "")
            try:
                return abs(datetime.fromisoformat(ts.replace("Z", "+00:00")).hour - 12)
            except Exception:
                logger.debug("weather metar timestamp parse failed")
                return 99

        chosen = min(features, key=_nearest_noon_hour)
        props = chosen.get("properties", {})
        return {
            "station_id": props.get("station"),
            "time": props.get("timestamp"),
            "temp_c": props.get("temp_c"),
            "wind_kt": props.get("wind_speed_kt"),
            "visibility_mi": props.get("visibility_statute_mi"),
            "weather": props.get("wx_string"),
        }
    except CircuitOpenError:
        logger.warning(
            "NOAA METAR circuit OPEN, skipping for %s on %s", station_id, date
        )
        return None
    except Exception as e:
        logger.warning("Exception in fetch_noaa_metar(%s, %s): %s", station_id, date, e)
        return None
