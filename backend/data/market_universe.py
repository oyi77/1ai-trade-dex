"""MarketUniverseScanner — universal market discovery across all platforms.

Scans 5000+ markets per cycle using a DataProvider abstraction.
Caches results for MARKET_UNIVERSE_CACHE_TTL_SECONDS (default 300s).
"""

from __future__ import annotations
import json
import random
import time

from backend.data.shared_client import get_shared_client
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
        self._base_url = getattr(
            settings, "GAMMA_API_URL", "https://gamma-api.polymarket.com"
        )
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

        client = get_shared_client()
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
                        logger.warning(
                            "[PolymarketProvider] 429 Rate Limit hit at offset=%d. Retrying in %ss...",
                            page_offset,
                            retry_delay,
                        )
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
                logger.error(
                    "[PolymarketProvider] Max retries exceeded at offset=%d",
                    page_offset,
                )
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
                    "yes_price": (
                        float(json.loads(raw["outcomePrices"])[0])
                        if "outcomePrices" in raw
                        else 0.5
                    ),
                    "no_price": (
                        float(json.loads(raw["outcomePrices"])[1])
                        if "outcomePrices" in raw
                        else 0.5
                    ),
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
        self._base_url = getattr(
            settings, "KALSHI_API_URL", "https://api.elections.kalshi.com/trade-api/v2"
        )

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

        client = get_shared_client()
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
                        logger.warning(
                            "[KalshiProvider] 429 Rate Limit hit. Retrying in %ss...",
                            retry_delay,
                        )
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


class PMXTProvider(DataProvider):
    """PMXT multi-platform data provider — secondary provider via pmxt_client."""

    def __init__(self) -> None:
        # "limitless" removed — smart wallet not deployed on Base (2026-05-30)
        self._exchanges = ["polymarket", "kalshi", "hyperliquid"]

    async def fetch_markets(
        self,
        limit: int = 5000,
        offset: int = 0,
        active_only: bool = True,
    ) -> List[Dict[str, Any]]:
        from backend.data.pmxt_client import PmxtClient

        client = PmxtClient()
        results: Dict[str, list] = await client.fetch_multi_platform_markets(
            exchanges=self._exchanges, limit=min(limit, 200)
        )

        markets: List[Dict[str, Any]] = []
        for exchange, pmxt_markets in results.items():
            for m in pmxt_markets:
                market = {
                    "market_id": m.market_id,
                    "question": m.title,
                    "end_date": m.resolution_date or "",
                    "category": m.category or "",
                    "volume_24h": m.volume_24h,
                    "status": m.status or "unknown",
                    "yes_price": m.yes_price if m.yes_price is not None else 0.5,
                    "no_price": m.no_price if m.no_price is not None else 0.5,
                    "slug": m.slug or "",
                    "platform": exchange,
                }
                markets.append(market)

        logger.info(
            "[PMXTProvider] fetched %d markets across %d exchanges",
            len(markets),
            len(results),
        )
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
            logger.debug(
                "[MarketUniverseScanner] returning %d cached markets",
                len(_MARKET_CACHE),
            )
            return _MARKET_CACHE[:limit]

        from datetime import datetime, timezone

        markets = await self._provider.fetch_markets(limit=limit, active_only=True)

        # Merge PMXT secondary provider markets when enabled
        if getattr(settings, "PMXT_ENABLED", False) and not isinstance(
            self._provider, PMXTProvider
        ):
            try:
                pmxt = PMXTProvider()
                pmxt_markets = await pmxt.fetch_markets(limit=limit, active_only=True)
                seen_ids = {m["market_id"] for m in markets}
                for m in pmxt_markets:
                    if m["market_id"] not in seen_ids:
                        markets.append(m)
                        seen_ids.add(m["market_id"])
            except Exception as exc:
                logger.warning(
                    "[MarketUniverseScanner] PMXT secondary fetch failed: %s", exc
                )
        _now_dt = datetime.now(timezone.utc)
        filtered = [
            m
            for m in markets
            if m.get("volume_24h", 0) > 0 and m.get("status") != "closed"
        ]

        _MARKET_CACHE = filtered
        _CACHE_TIMESTAMP = now
        logger.info(
            "[MarketUniverseScanner] refreshed cache with %d markets", len(filtered)
        )
        return filtered[:limit]

    async def get_markets_by_category(
        self, category: str, limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Return markets filtered by category."""
        all_markets = await self.get_active_markets(limit=5000)
        return [
            m for m in all_markets if m.get("category", "").lower() == category.lower()
        ][:limit]

    def invalidate_cache(self) -> None:
        """Force cache refresh on next call."""
        global _CACHE_TIMESTAMP
        _CACHE_TIMESTAMP = 0.0

    async def detect_neg_risk_events(
        self,
        min_outcomes: int = 3,
        min_sum_deviation: float = 0.01,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        """
        Detect neg-risk events by grouping markets by slug.

        A neg-risk event has >= *min_outcomes* mutually exclusive outcomes
        whose YES prices sum deviates from 1.0 by at least *min_sum_deviation*.

        Returns a list of event dicts sorted by deviation descending:
            [{"slug", "question", "outcomes", "sum_of_prices", "deviation", "num_outcomes"}]
        """
        markets = await self.get_active_markets(limit=limit)

        # Group by slug -- Polymarket groups multi-outcome markets under one event
        events: Dict[str, List[Dict[str, Any]]] = {}
        for m in markets:
            slug = m.get("slug", "")
            if not slug:
                continue
            events.setdefault(slug, []).append(m)

        neg_risk: List[Dict[str, Any]] = []
        for slug, outcomes in events.items():
            if len(outcomes) < min_outcomes:
                continue

            prices: List[float] = []
            parsed: List[Dict[str, Any]] = []
            for o in outcomes:
                yes_p = float(o.get("yes_price", 0.5))
                no_p = float(o.get("no_price", 0.5))
                prices.append(yes_p)
                parsed.append(
                    {
                        "label": o.get("question", ""),
                        "token_id": str(o.get("market_id", "")),
                        "yes_price": yes_p,
                        "no_price": no_p,
                    }
                )

            price_sum = sum(prices)
            deviation = abs(price_sum - 1.0)

            if deviation < min_sum_deviation:
                continue

            neg_risk.append(
                {
                    "slug": slug,
                    "question": outcomes[0].get("question", ""),
                    "outcomes": parsed,
                    "sum_of_prices": price_sum,
                    "deviation": deviation,
                    "num_outcomes": len(parsed),
                }
            )

        neg_risk.sort(key=lambda e: e["deviation"], reverse=True)
        logger.info(
            "[MarketUniverseScanner] detected %d neg-risk events (min_outcomes=%d)",
            len(neg_risk),
            min_outcomes,
        )
        return neg_risk
