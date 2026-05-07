"""
Gamma API client for Polymarket market data.

Provides fetch_markets() used by realtime_scanner and other strategies
to retrieve active markets from the Polymarket Gamma API.
"""

import logging
import asyncio
from datetime import datetime
from typing import Any, Optional

import httpx

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError

logger = logging.getLogger("trading_bot")

gamma_breaker = CircuitBreaker("gamma_api", failure_threshold=5, recovery_timeout=60.0)

GAMMA_API_URL = f"{settings.GAMMA_API_URL}/markets"
_RATE_LIMIT_RETRY_DELAY = 2.0
_RATE_LIMIT_MAX_RETRIES = 3


async def fetch_markets(
    limit: int = 100,
    active: bool = True,
    order: str = "volume",
    ascending: bool = False,
) -> list[dict[str, Any]]:
    """Fetch markets from the Polymarket Gamma API with pagination.

    Args:
        limit: Maximum number of markets to return.
        active: True for active markets, False for closed/resolved.
        order: Sort field (e.g. 'volume', 'liquidity', 'created').
        ascending: Sort direction.

    Returns:
        List of market dicts from the Gamma API, or empty list on failure.
    """
    async def _fetch_single_page() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                GAMMA_API_URL,
                params={
                    "active": str(active).lower(),
                    "closed": str(not active).lower(),
                    "limit": limit,
                    "order": order,
                    "ascending": str(ascending).lower(),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return []

    if limit <= 100:
        try:
            return await gamma_breaker.call(_fetch_single_page)
        except CircuitOpenError:
            logger.warning("[gamma] Gamma API circuit open, skipping")
            return []
        except httpx.TimeoutException:
            logger.warning("[gamma] Gamma API request timed out")
            return []
        except httpx.HTTPStatusError as e:
            logger.warning("[gamma] Gamma API HTTP error: %s", e.response.status_code)
            return []
        except Exception as e:
            logger.warning("[gamma] Gamma API fetch failed: %s", e)
            return []

    async def _fetch_page(client: httpx.AsyncClient, offset: int) -> Optional[list]:
        for attempt in range(_RATE_LIMIT_MAX_RETRIES):
            resp = await client.get(
                GAMMA_API_URL,
                params={
                    "active": str(active).lower(),
                    "closed": str(not active).lower(),
                    "limit": page_size,
                    "offset": offset,
                    "order": order,
                    "ascending": str(ascending).lower(),
                },
            )
            if resp.status_code == 429:
                delay = _RATE_LIMIT_RETRY_DELAY * (attempt + 1)
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.json()
        return None

    all_markets: list[dict[str, Any]] = []
    offset = 0
    page_size = 100
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            while len(all_markets) < limit:
                try:
                    page = await gamma_breaker.call(_fetch_page, client, offset)
                except CircuitOpenError:
                    logger.warning("[gamma] Gamma API circuit open during pagination at offset %d", offset)
                    break
                if page is None or not isinstance(page, list) or not page:
                    break
                all_markets.extend(page)
                if len(page) < page_size:
                    break
                offset += page_size
        return all_markets[:limit]
    except Exception as e:
        logger.warning("[gamma] Paginated fetch failed: %s", e)
        return all_markets


async def fetch_resolved_markets(
    limit: int = 500,
    tag: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Fetch resolved (settled) markets from Polymarket Gamma API.

    Returns markets with their final outcome prices, suitable for
    historical backtesting. Paginates through all available results.
    """
    async def _fetch_resolved_page(client: httpx.AsyncClient, params: dict) -> Optional[list]:
        for attempt in range(_RATE_LIMIT_MAX_RETRIES):
            resp = await client.get(GAMMA_API_URL, params=params)
            if resp.status_code == 429:
                delay = _RATE_LIMIT_RETRY_DELAY * (attempt + 1)
                logger.debug("[gamma] Rate limited, retrying in %.1fs (attempt %d)", delay, attempt + 1)
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.json()
        return None

    all_markets = []
    offset = 0
    page_size = min(limit, 100)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            while len(all_markets) < limit:
                params: dict[str, Any] = {
                    "active": "false",
                    "closed": "true",
                    "limit": page_size,
                    "offset": offset,
                    "order": "endDate",
                    "ascending": "false",
                }
                if tag:
                    params["tag"] = tag

                try:
                    page = await gamma_breaker.call(_fetch_resolved_page, client, params)
                except CircuitOpenError:
                    logger.warning("[gamma] Gamma API circuit open during resolved markets fetch at offset %d", offset)
                    break

                if page is None:
                    logger.warning("[gamma] Rate limited after %d retries at offset %d", _RATE_LIMIT_MAX_RETRIES, offset)
                    break

                if not isinstance(page, list) or not page:
                    break

                for m in page:
                    if not m.get("resolved"):
                        continue
                    all_markets.append(m)

                if len(page) < page_size:
                    break
                offset += page_size

        logger.info(
            "[gamma] Fetched %d resolved markets (limit=%d, tag=%s)",
            len(all_markets), limit, tag,
        )
        return all_markets[:limit]

    except Exception as e:
        logger.warning("[gamma] Resolved markets fetch failed: %s", e)
        return all_markets


async def fetch_settled_markets() -> list[dict[str, Any]]:
    """Fetch settled Polymarket markets formatted for historical data storage.

    Called by HistoricalDataCollector.collect_market_outcomes().
    """
    raw = await fetch_resolved_markets(limit=500)
    results = []
    for m in raw:
        tokens = m.get("tokens", [])
        if not tokens:
            continue

        winning_token = None
        for t in tokens:
            if t.get("winner"):
                winning_token = t
                break

        if winning_token is None:
            winning_outcome = m.get("outcome", "")
        else:
            winning_outcome = winning_token.get("outcome", "unknown")

        final_price = None
        if winning_token:
            final_price = float(winning_token.get("price", 0))
        elif m.get("outcomePrices"):
            try:
                prices = m["outcomePrices"]
                if isinstance(prices, str):
                    import json
                    prices = json.loads(prices)
                if isinstance(prices, list) and prices:
                    final_price = float(prices[0])
            except (ValueError, TypeError):
                pass

        end_date_str = m.get("endDate") or m.get("end_date_iso")
        resolution_time = None
        if end_date_str:
            try:
                resolution_time = datetime.fromisoformat(
                    end_date_str.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        results.append({
            "ticker": m.get("conditionId", m.get("id", "")),
            "platform": "polymarket",
            "outcome": winning_outcome,
            "final_price": final_price,
            "resolution_time": resolution_time,
            "volume": float(m.get("volume", 0) or 0),
            "category": m.get("category", m.get("groupItemTitle")),
            "raw_data": {
                "question": m.get("question", ""),
                "slug": m.get("slug", ""),
                "outcomes": m.get("outcomes", ""),
                "outcomePrices": m.get("outcomePrices"),
            },
        })

    return results
