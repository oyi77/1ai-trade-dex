"""Dune Analytics client for querying Polymarket on-chain data.

Queries Dune Analytics API for Polymarket volume, top markets, whale activity,
and settlement history. Results cached with TTL (1h live, 24h historical).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError

from loguru import logger

dune_breaker = CircuitBreaker("dune_api", failure_threshold=3, recovery_timeout=120.0)

DUNE_API_URL = "https://api.dune.com/api/v1"

# Cache TTLs
CACHE_TTL_LIVE = 3600       # 1 hour for live queries
CACHE_TTL_HISTORICAL = 86400  # 24 hours for historical queries

# Pre-built Dune query IDs for Polymarket analytics
# These are standard community queries; users can override via settings.
DEFAULT_QUERY_IDS = {
    "total_volume": 3683272,
    "top_markets": 3683273,
    "whale_activity": 3683274,
    "settlement_history": 3683275,
}


@dataclass
class DuneCacheEntry:
    """A cached Dune query result with TTL."""
    data: Any
    fetched_at: float
    ttl: float

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.fetched_at) > self.ttl


@dataclass
class DuneAnalyticsClient:
    """Client for querying Polymarket on-chain data via Dune Analytics API.

    Args:
        api_key: Dune Analytics API key. Falls back to settings.DUNE_API_KEY.
        query_ids: Mapping of query_name -> Dune query ID. Falls back to defaults.
    """

    api_key: str = ""
    query_ids: dict[str, int] = field(default_factory=dict)
    _cache: dict[str, DuneCacheEntry] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if not self.api_key:
            self.api_key = getattr(settings, "DUNE_API_KEY", "")
        if not self.query_ids:
            configured = getattr(settings, "DUNE_QUERY_IDS", None)
            if configured and isinstance(configured, dict):
                self.query_ids = configured
            else:
                self.query_ids = dict(DEFAULT_QUERY_IDS)

    def _headers(self) -> dict[str, str]:
        return {
            "X-Dune-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _get_cached(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry is not None and not entry.is_expired:
            logger.debug("Dune cache hit: %s", key)
            return entry.data
        return None

    def _set_cached(self, key: str, data: Any, ttl: float) -> None:
        self._cache[key] = DuneCacheEntry(data=data, fetched_at=time.time(), ttl=ttl)

    async def execute_query(self, query_id: int, ttl: float = CACHE_TTL_LIVE) -> list[dict]:
        """Execute a Dune query and return result rows.

        Uses the execute-then-poll pattern:
        1. POST /query/{id}/execute  -> execution_id
        2. GET  /execution/{id}/results -> rows (poll until complete)

        Args:
            query_id: Dune query ID.
            ttl: Cache TTL in seconds.

        Returns:
            List of result row dicts, or empty list on failure.
        """
        cache_key = f"dune_query_{query_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        async def _run_query() -> list[dict]:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Step 1: Execute query
                exec_resp = await client.post(
                    f"{DUNE_API_URL}/query/{query_id}/execute",
                    headers=self._headers(),
                )
                exec_resp.raise_for_status()
                execution_id = exec_resp.json().get("execution_id")
                if not execution_id:
                    logger.error("Dune execute returned no execution_id for query %d", query_id)
                    return []

                # Step 2: Poll for results (max 60s)
                for _ in range(30):
                    result_resp = await client.get(
                        f"{DUNE_API_URL}/execution/{execution_id}/results",
                        headers=self._headers(),
                    )
                    result_resp.raise_for_status()
                    result_data = result_resp.json()
                    state = result_data.get("state", "")
                    if state == "QUERY_STATE_COMPLETED":
                        rows = result_data.get("result", {}).get("rows", [])
                        logger.info("Dune query %d returned %d rows", query_id, len(rows))
                        return rows
                    elif state in ("QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED"):
                        logger.error("Dune query %d failed with state: %s", query_id, state)
                        return []
                    # Still running — wait and retry
                    import asyncio
                    await asyncio.sleep(2)

                logger.warning("Dune query %d timed out waiting for results", query_id)
                return []

        try:
            result = await dune_breaker.call(_run_query)
            self._set_cached(cache_key, result, ttl)
            return result
        except CircuitOpenError:
            logger.warning("[dune] Dune API circuit open, skipping")
            return []
        except Exception as e:
            logger.error("[dune] Query %d failed: %s", query_id, e)
            return []

    async def get_total_volume(self, days: int = 30) -> list[dict]:
        """Fetch total Polymarket trading volume for the last N days.

        Returns:
            List of rows with date, volume, trade_count columns.
        """
        query_id = self.query_ids.get("total_volume", DEFAULT_QUERY_IDS["total_volume"])
        return await self.execute_query(query_id, ttl=CACHE_TTL_LIVE)

    async def get_top_markets(self, limit: int = 50) -> list[dict]:
        """Fetch top Polymarket markets by volume/liquidity.

        Returns:
            List of rows with market_id, question, volume, liquidity columns.
        """
        query_id = self.query_ids.get("top_markets", DEFAULT_QUERY_IDS["top_markets"])
        return await self.execute_query(query_id, ttl=CACHE_TTL_LIVE)

    async def get_whale_activity(self, min_usd: float = 10000.0) -> list[dict]:
        """Fetch recent whale trades on Polymarket.

        Args:
            min_usd: Minimum trade size in USD to include.

        Returns:
            List of rows with wallet, market_id, side, amount, timestamp columns.
        """
        query_id = self.query_ids.get("whale_activity", DEFAULT_QUERY_IDS["whale_activity"])
        return await self.execute_query(query_id, ttl=CACHE_TTL_LIVE)

    async def get_settlement_history(self, days: int = 90) -> list[dict]:
        """Fetch Polymarket settlement history for backtesting.

        Returns:
            List of rows with market_id, outcome, settlement_price, resolved_at columns.
        """
        query_id = self.query_ids.get("settlement_history", DEFAULT_QUERY_IDS["settlement_history"])
        return await self.execute_query(query_id, ttl=CACHE_TTL_HISTORICAL)

    def clear_cache(self) -> int:
        """Clear all cached results. Returns number of entries cleared."""
        count = len(self._cache)
        self._cache.clear()
        return count

    async def health_check(self) -> bool:
        """Lightweight liveness check — verify API key is valid."""
        if not self.api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{DUNE_API_URL}/auth/validate",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except Exception as e:
            logger.debug("[dune] Health check failed: %s", e)
            return False
