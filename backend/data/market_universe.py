"""MarketUniverseScanner — universal market discovery across all platforms.

Scans 5000+ markets per cycle using a DataProvider abstraction.
Caches results for MARKET_UNIVERSE_CACHE_TTL_SECONDS (default 300s).
"""

from __future__ import annotations
import json
import random
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from backend.config import settings

from loguru import logger
_MARKET_CACHE: List[Dict[str, Any]] = []
_CACHE_TIMESTAMP: float = 0.0


class DataProvider(ABC):
    """Abstract data provider — platform-agnostic market fetching."""

    @abstractmethod
    async def fetch_markets(
        self,
        limit: int = 5000,
        offset: int = 0,
        active_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return a list of market dicts with at least market_id, question, end_date, category, volume_24h."""


class PolymarketProvider(DataProvider):
    """Polymarket Gamma API data provider."""

    def __init__(self) -> None:
        self._base_url = getattr(settings, "GAMMA_API_URL", "https://gamma-api.polymarket.com")
        self._page_size = getattr(settings, "SCANNER_PAGE_SIZE", 500)

    async def fetch_markets(
        self,
        limit: int = 5000,
        offset: int = 0,
        active_only: bool = True,
    ) -> List[Dict[str, Any]]:
        import httpx
        import asyncio

        markets: List[Dict[str, Any]] = []
        page_offset = offset
        remaining = limit

        async with httpx.AsyncClient(timeout=30.0) as client:
            while remaining > 0:
                page_limit = min(self._page_size, remaining)
                params: Dict[str, Any] = {
                    "limit": page_limit,
                    "offset": page_offset,
                    "active": "true" if active_only else "false",
                    "closed": "false",
                }
                max_retries = 3
                retry_delay = 1.0
                batch = []
                for attempt in range(max_retries):
                    try:
                        resp = await client.get(
                            f"{self._base_url}/markets",
                            params=params,
                        )
                        if resp.status_code == 429:
                            logger.warning("[PolymarketProvider] 429 Rate Limit hit at offset=%d. Retrying in %ss...", page_offset, retry_delay)
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2
                            continue
                        resp.raise_for_status()
                        batch = resp.json()
                        break
                    except Exception as e:
                        logger.warning(
                            "[PolymarketProvider] fetch error at offset=%d: %s",
                            page_offset,
                            e,
                        )
                        break
                else:
                    logger.error("[PolymarketProvider] Max retries exceeded at offset=%d", page_offset)
                    break

                if not batch:
                    break

                for raw in batch:
                    market = {
                        "market_id": raw.get("id", raw.get("condition_id", "")),
                        "question": raw.get("question", ""),
                        "end_date": raw.get("end_date_iso", raw.get("endDate", "")),
                        "category": raw.get("category", ""),
                        "volume_24h": float(raw.get("volume24hr", 0) or 0),
                        "status": raw.get("active", "unknown"),
                        "yes_price": float(json.loads(raw["outcomePrices"])[0]) if "outcomePrices" in raw else 0.5,
                        "no_price": float(json.loads(raw["outcomePrices"])[1]) if "outcomePrices" in raw else 0.5,
                        "slug": raw.get("slug", ""),
                        "platform": "polymarket",
                    }
                    markets.append(market)

                page_offset += len(batch)
                remaining -= len(batch)

                if len(batch) < page_limit:
                    break
                await asyncio.sleep(0.5)  # respect rate limits


        logger.info("[PolymarketProvider] fetched %d markets", len(markets))
        return markets


class KalshiProvider(DataProvider):
    """Kalshi API data provider."""

    def __init__(self) -> None:
        self._base_url = getattr(settings, "KALSHI_API_URL", "https://api.elections.kalshi.com/trade-api/v2")

    async def fetch_markets(
        self,
        limit: int = 5000,
        offset: int = 0,
        active_only: bool = True,
    ) -> List[Dict[str, Any]]:
        if not getattr(settings, "KALSHI_ENABLED", False):
            return []

        import httpx
        import asyncio

        markets: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            cursor = None
            remaining = limit
            while remaining > 0:
                params: Dict[str, Any] = {
                    "limit": min(500, remaining),
                    "status": "open" if active_only else "all",
                }
                if cursor:
                    params["cursor"] = cursor
                max_retries = 3
                retry_delay = 1.0
                data = {}
                batch = []
                for attempt in range(max_retries):
                    try:
                        resp = await client.get(
                            f"{self._base_url}/markets",
                            params=params,
                        )
                        if resp.status_code == 429:
                            logger.warning("[KalshiProvider] 429 Rate Limit hit. Retrying in %ss...", retry_delay)
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2
                            continue
                        resp.raise_for_status()
                        data = resp.json()
                        batch = data.get("markets", [])
                        break
                    except Exception as e:
                        logger.warning("[KalshiProvider] fetch error: %s", e)
                        break
                else:
                    logger.error("[KalshiProvider] Max retries exceeded")
                    break

                for raw in batch:
                    market = {
                        "market_id": raw.get("ticker", ""),
                        "question": raw.get("title", ""),
                        "end_date": raw.get("close_time", ""),
                        "category": raw.get("category", ""),
                        "volume_24h": float(raw.get("volume_24h", 0) or 0),
                        "status": "active" if raw.get("active") else "closed",
                        "yes_price": float(raw.get("yes_price", 0.5)),
                        "no_price": float(raw.get("no_price", 0.5)),
                        "slug": raw.get("slug", raw.get("ticker", "")),
                        "platform": "kalshi",
                    }
                    markets.append(market)

                remaining -= len(batch)
                cursor = data.get("cursor_next")
                if not cursor or len(batch) < 500:
                    break
                await asyncio.sleep(0.5)

        logger.info("[KalshiProvider] fetched %d markets", len(markets))
        return markets


class MarketUniverseScanner:
    """Universal market scanner across 5000+ markets using DataProvider abstraction."""

    def __init__(self, provider: Optional[DataProvider] = None) -> None:
        self._provider = provider or PolymarketProvider()
        self._cache_ttl = getattr(settings, "MARKET_UNIVERSE_CACHE_TTL_SECONDS", 300)

    async def get_active_markets(self, limit: int = 5000) -> List[Dict[str, Any]]:
        """Return active markets, using cache if fresh."""
        global _MARKET_CACHE, _CACHE_TIMESTAMP

        now = time.time()
        # Add ±30s jitter to prevent cache-stampede when 14+ strategies refresh simultaneously
        ttl_with_jitter = self._cache_ttl + random.randint(-30, 30)
        if _MARKET_CACHE and (now - _CACHE_TIMESTAMP) < ttl_with_jitter:
            logger.debug("[MarketUniverseScanner] returning %d cached markets", len(_MARKET_CACHE))
            return _MARKET_CACHE[:limit]

        from datetime import datetime, timezone

        markets = await self._provider.fetch_markets(limit=limit, active_only=True)
        _now_dt = datetime.now(timezone.utc)
        filtered = [
            m for m in markets
            if m.get("volume_24h", 0) > 0
            and m.get("status") != "closed"
        ]

        _MARKET_CACHE = filtered
        _CACHE_TIMESTAMP = now
        logger.info("[MarketUniverseScanner] refreshed cache with %d markets", len(filtered))
        return filtered[:limit]

    async def get_markets_by_category(
        self, category: str, limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Return markets filtered by category."""
        all_markets = await self.get_active_markets(limit=5000)
        return [m for m in all_markets if m.get("category", "").lower() == category.lower()][:limit]

    def invalidate_cache(self) -> None:
        """Force cache refresh on next call."""
        global _CACHE_TIMESTAMP
        _CACHE_TIMESTAMP = 0.0
