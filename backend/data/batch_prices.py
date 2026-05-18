"""Batch prices history fetcher for Polymarket markets.

Polymarket has a /batch-prices-history endpoint that fetches price history
for multiple markets in a single request, instead of N individual calls.
"""
import asyncio
from typing import Any, Optional

import httpx

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.core.external_rate_limiter import ExternalRateLimiter
from loguru import logger

_batch_breaker = CircuitBreaker("gamma_batch_prices", failure_threshold=5, recovery_timeout=60.0)
_batch_rate_limiter = ExternalRateLimiter(
    name="gamma_batch",
    max_calls_per_minute=30,
    circuit_breaker=_batch_breaker,
)

GAMMA_API_URL = settings.GAMMA_API_URL


async def fetch_batch_prices_history(
    market_ids: list[str],
    interval: str = "1h",
    fidelity: int = 60,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch price history for multiple markets in one request.

    Args:
        market_ids: List of condition_ids or token_ids to fetch.
        interval: Time interval (e.g. '1h', '1d', '1w').
        fidelity: Data point fidelity in seconds.

    Returns:
        Dict mapping market_id -> list of {t, p} price points.
        Markets that fail are omitted (not included in result).
    """
    if not market_ids:
        return {}

    # Polymarket batch endpoint accepts comma-separated IDs
    async def _fetch():
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{GAMMA_API_URL}/batch-prices-history",
                params={
                    "market_ids": ",".join(market_ids),
                    "interval": interval,
                    "fidelity": fidelity,
                },
            )
            resp.raise_for_status()
            return resp.json()

    try:
        data = await _batch_rate_limiter.call(_fetch)
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            # Some endpoints return [{market_id, prices}] format
            result = {}
            for item in data:
                mid = item.get("market_id") or item.get("condition_id", "")
                prices = item.get("prices", item.get("history", []))
                if mid and prices:
                    result[mid] = prices
            return result
        return {}
    except CircuitOpenError:
        logger.warning("[batch_prices] Circuit open, skipping batch fetch")
        return {}
    except httpx.HTTPStatusError as e:
        logger.warning("[batch_prices] HTTP %s from batch-prices-history", e.response.status_code)
        # Fallback: try individual fetches
        return await _fallback_individual(market_ids, interval, fidelity)
    except Exception as e:
        logger.warning("[batch_prices] Batch fetch failed: %s — falling back to individual", e)
        return await _fallback_individual(market_ids, interval, fidelity)


async def _fallback_individual(
    market_ids: list[str],
    interval: str,
    fidelity: int,
) -> dict[str, list[dict[str, Any]]]:
    """Fallback: fetch price history individually for each market."""
    results = {}

    async def _fetch_one(mid: str):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{GAMMA_API_URL}/prices-history",
                    params={"market_id": mid, "interval": interval, "fidelity": fidelity},
                )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    results[mid] = data
                elif isinstance(data, dict) and "prices" in data:
                    results[mid] = data["prices"]
        except Exception as e:
            logger.debug("[batch_prices] Individual fetch failed for %s: %s", mid, e)

    # Run up to 5 concurrently to avoid hammering
    sem = asyncio.Semaphore(5)

    async def _guarded(mid: str):
        async with sem:
            await _fetch_one(mid)

    await asyncio.gather(*[_guarded(mid) for mid in market_ids])
    return results
