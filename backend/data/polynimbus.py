"""
Polynimbus city registry and market fetcher

CITY_REGISTRY holds 36+ global cities with lat/lon/country/tz.
"""

import os
import httpx
from typing import List

CITY_REGISTRY = {
    # USA (existing 11 cities)
    "new_york":     {"lat": 40.7128,  "lon": -74.0060,  "country": "US", "tz": "America/New_York"},
    "los_angeles":  {"lat": 34.0522,  "lon": -118.2437, "country": "US", "tz": "America/Los_Angeles"},
    "chicago":      {"lat": 41.8781,  "lon": -87.6298,   "country": "US", "tz": "America/Chicago"},
    "houston":      {"lat": 29.7604,  "lon": -95.3698,   "country": "US", "tz": "America/Chicago"},
    "miami":        {"lat": 25.7617,  "lon": -80.1918,   "country": "US", "tz": "America/New_York"},
    "dallas":       {"lat": 32.7767,  "lon": -96.7970,   "country": "US", "tz": "America/Chicago"},
    "philadelphia": {"lat": 39.9526,  "lon": -75.1652,   "country": "US", "tz": "America/New_York"},
    "atlanta":      {"lat": 33.7490,  "lon": -84.3880,   "country": "US", "tz": "America/New_York"},
    "phoenix":      {"lat": 33.4484,  "lon": -112.0740,  "country": "US", "tz": "America/Phoenix"},
    "seattle":      {"lat": 47.6062,  "lon": -122.3321,  "country": "US", "tz": "America/Los_Angeles"},
    "boston":       {"lat": 42.3601,  "lon": -71.0589,   "country": "US", "tz": "America/New_York"},
    # Global cities - sample set
    "london":       {"lat": 51.5074,  "lon": -0.1278,    "country": "GB", "tz": "Europe/London"},
    "paris":        {"lat": 48.8566,  "lon": 2.3522,     "country": "FR", "tz": "Europe/Paris"},
    "tokyo":        {"lat": 35.6895,  "lon": 139.6917,   "country": "JP", "tz": "Asia/Tokyo"},
    "sydney":       {"lat": -33.8688, "lon": 151.2093,   "country": "AU", "tz": "Australia/Sydney"},
    "dubai":        {"lat": 25.2048,  "lon": 55.2708,    "country": "AE", "tz": "Asia/Dubai"},
    "amsterdam":    {"lat": 52.3676,  "lon": 4.9041,     "country": "NL", "tz": "Europe/Amsterdam"},
    "frankfurt":    {"lat": 50.1109,  "lon": 8.6821,     "country": "DE", "tz": "Europe/Berlin"},
    "hong_kong":    {"lat": 22.3193,  "lon": 114.1694,   "country": "HK", "tz": "Asia/Hong_Kong"},
    "singapore":    {"lat": 1.3521,   "lon": 103.8198,   "country": "SG", "tz": "Asia/Singapore"},
    "toronto":      {"lat": 43.6532,  "lon": -79.3832,   "country": "CA", "tz": "America/Toronto"},
    "mumbai":       {"lat": 19.0760,  "lon": 72.8777,    "country": "IN", "tz": "Asia/Kolkata"},
    "sao_paulo":    {"lat": -23.5505, "lon": -46.6333,   "country": "BR", "tz": "America/Sao_Paulo"},
    "mexico_city":  {"lat": 19.4326,  "lon": -99.1332,   "country": "MX", "tz": "America/Mexico_City"},
    "seoul":        {"lat": 37.5665,  "lon": 126.9780,   "country": "KR", "tz": "Asia/Seoul"},
    "bangkok":      {"lat": 13.7563,  "lon": 100.5018,   "country": "TH", "tz": "Asia/Bangkok"},
    "jakarta":      {"lat": -6.2088,  "lon": 106.8456,   "country": "ID", "tz": "Asia/Jakarta"},
    "manila":       {"lat": 14.5995,  "lon": 120.9842,   "country": "PH", "tz": "Asia/Manila"},
    "taipei":       {"lat": 25.0329,  "lon": 121.5654,   "country": "TW", "tz": "Asia/Taipei"},
    "moscow":       {"lat": 55.7558,  "lon": 37.6173,    "country": "RU", "tz": "Europe/Moscow"},
    "istanbul":     {"lat": 41.0082,  "lon": 28.9784,    "country": "TR", "tz": "Europe/Istanbul"},
    "cairo":        {"lat": 30.0444,  "lon": 31.2357,    "country": "EG", "tz": "Africa/Cairo"},
    "lagos":        {"lat": 6.5244,   "lon": 3.3792,     "country": "NG", "tz": "Africa/Lagos"},
    "nairobi":      {"lat": -1.2921,  "lon": 36.8219,    "country": "KE", "tz": "Africa/Nairobi"},
    "cape_town":    {"lat": -33.9249, "lon": 18.4241,    "country": "ZA", "tz": "Africa/Johannesburg"},
    "berlin":       {"lat": 52.5200,  "lon": 13.4050,    "country": "DE", "tz": "Europe/Berlin"},
}


async def fetch_polynimbus_markets(tags: List[str] = ["weather"]) -> List[dict]:
    """
    Fetch weather markets from the Polynimbus API or Goldsky-compatible API.
    Returns empty list if key/url not set.
    """
    api_url = os.environ.get("POLYNIMBUS_API_URL")
    api_key = os.environ.get("POLYNIMBUS_API_KEY")
    if not api_url or not api_key:
        return []
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"tags": ",".join(tags)} if tags else {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(api_url, params=params, headers=headers)
            resp.raise_for_status()
            # Accepts "markets" OR direct list
            data = resp.json() if callable(getattr(resp, "json", None)) else await resp.json()
            if isinstance(data, dict) and "markets" in data:
                return data["markets"]
            if isinstance(data, list):
                return data
            return []
    except Exception:
        return []
