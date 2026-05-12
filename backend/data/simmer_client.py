"""Simmer API client for weather prediction markets.

Simmer is a weather-focused prediction market platform. This client provides
async access to its market discovery and portfolio endpoints.

Configuration (environment variables):
    SIMMER_API_URL: Base URL for the Simmer API (default: https://api.simmer.io)
    SIMMER_API_KEY: API key for authenticated requests (optional; required for
                    portfolio endpoints and may be required for market endpoints)

If SIMMER_API_KEY is missing, calls return empty data structures rather than
raising — keeping the system resilient when the integration is unconfigured.
"""
from __future__ import annotations
import os
from typing import Any, Dict, List, Optional

import httpx

from loguru import logger
# Default config — read at call time so env changes during runtime are honored
DEFAULT_SIMMER_API_URL = "https://api.simmer.io"
DEFAULT_TIMEOUT = 15.0


def _get_base_url() -> str:
    return os.getenv("SIMMER_API_URL", DEFAULT_SIMMER_API_URL).rstrip("/")


def _get_api_key() -> Optional[str]:
    key = os.getenv("SIMMER_API_KEY")
    return key.strip() if key else None


def _build_headers(api_key: Optional[str]) -> Dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "polyedge-simmer-client/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key
    return headers


async def fetch_weather_markets_via_simmer(
    tags: Optional[List[str]] = None,
) -> List[dict]:
    """Fetch weather prediction markets from Simmer.

    Args:
        tags: Optional list of tag strings to filter markets (e.g., ["temperature",
              "hurricane"]). Sent as repeated `tag` query parameters.

    Returns:
        A list of market dicts as returned by Simmer. Returns an empty list if
        the API key is missing, the request fails, or the response is malformed.
    """
    api_key = _get_api_key()
    if not api_key:
        logger.debug("SIMMER_API_KEY not set; skipping weather market fetch")
        return []

    base_url = _get_base_url()
    url = f"{base_url}/v1/markets/weather"

    params: List[tuple[str, str]] = []
    if tags:
        for tag in tags:
            if tag:
                params.append(("tag", str(tag)))

    headers = _build_headers(api_key)

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.get(url, params=params or None, headers=headers)
            response.raise_for_status()
            data: Any = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Simmer weather markets request failed: status=%s body=%s",
            exc.response.status_code,
            exc.response.text[:200],
        )
        return []
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Simmer weather markets request error: %s", exc)
        return []

    # Tolerate both `{"markets": [...]}` and bare list responses
    if isinstance(data, dict):
        markets = data.get("markets") or data.get("data") or data.get("results")
        if isinstance(markets, list):
            return markets
        logger.debug("Simmer markets response missing markets array: %r", list(data.keys()))
        return []
    if isinstance(data, list):
        return data
    logger.debug("Unexpected Simmer markets response type: %s", type(data).__name__)
    return []


async def fetch_weather_portfolio_simmer(address: str) -> dict:
    """Fetch the Simmer weather portfolio for a wallet address.

    Args:
        address: On-chain wallet address (checksummed or lowercase).

    Returns:
        A portfolio dict as returned by Simmer. Returns an empty dict if the
        API key is missing, the address is empty, or the request fails.
    """
    if not address:
        return {}

    api_key = _get_api_key()
    if not api_key:
        logger.debug("SIMMER_API_KEY not set; skipping portfolio fetch for %s", address)
        return {}

    base_url = _get_base_url()
    url = f"{base_url}/v1/portfolio/{address}"
    headers = _build_headers(api_key)

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data: Any = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Simmer portfolio request failed for %s: status=%s body=%s",
            address,
            exc.response.status_code,
            exc.response.text[:200],
        )
        return {}
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Simmer portfolio request error for %s: %s", address, exc)
        return {}

    if isinstance(data, dict):
        return data
    logger.debug("Unexpected Simmer portfolio response type: %s", type(data).__name__)
    return {}


__all__ = [
    "fetch_weather_markets_via_simmer",
    "fetch_weather_portfolio_simmer",
]
