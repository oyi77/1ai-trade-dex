"""Polymarket market scanner — fetches active markets from Gamma API."""

import asyncio
import math
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.config import settings

from loguru import logger
GAMMA_HOST = settings.GAMMA_API_URL
_SCAN_SEMAPHORE = asyncio.Semaphore(5)  # max 5 concurrent Gamma requests


@dataclass
class MarketInfo:
    ticker: str
    slug: str
    category: str
    end_date: str | None
    volume: float
    liquidity: float
    yes_price: float = 0.5
    no_price: float = 0.5
    question: str = ""
    metadata: dict = field(default_factory=dict)


async def fetch_all_active_markets(
    category: str | None = None,
    limit: int | None = None,
    timeout: float = 30.0,
) -> list[MarketInfo]:
    """Fetch all active markets from Gamma API with pagination and retry."""
    results: list[MarketInfo] = []
    offset = 0
    page_size = max(1, int(getattr(settings, "SCANNER_PAGE_SIZE", 500)))
    max_markets = int(limit if limit is not None else getattr(settings, "SCANNER_MAX_MARKETS", 10000))
    max_markets = max(1, max_markets)
    max_pages = max(1, math.ceil(max_markets / page_size))

    async with httpx.AsyncClient(timeout=timeout) as client:
        pages_fetched = 0
        while pages_fetched < max_pages:
            if len(results) >= max_markets:
                break

            params: dict[str, Any] = {
                "active": "true",
                "closed": "false",
                "limit": page_size,
                "offset": offset,
            }
            if category:
                params["category"] = category

            page = await _fetch_page(client, params)
            if not page:
                break

            for m in page:
                try:
                    # Use outcomePrices (string list) — Gamma API's canonical price field.
                    # tokens[] is often empty; outcomePrices is always populated.
                    outcome_prices_raw = m.get("outcomePrices") or []
                    if isinstance(outcome_prices_raw, str):
                        import json as _json

                        try:
                            outcome_prices_raw = _json.loads(outcome_prices_raw)
                        except Exception:
                            logger.exception("market_scanner: failed to parse outcomePrices JSON")
                            outcome_prices_raw = []

                    if outcome_prices_raw:
                        yes_price = float(outcome_prices_raw[0])
                        no_price = (
                            float(outcome_prices_raw[1])
                            if len(outcome_prices_raw) > 1
                            else 1.0 - yes_price
                        )
                    else:
                        # Fallback to tokens if outcomePrices missing
                        tokens = m.get("tokens", [])
                        yes_price = (
                            float(tokens[0].get("price", 0.5)) if tokens else 0.5
                        )
                        no_price = (
                            float(tokens[1].get("price", 0.5))
                            if len(tokens) > 1
                            else 1.0 - yes_price
                        )
                    # Clamp to valid prediction market range — API can return 0 or values >1
                    yes_price = max(0.01, min(0.99, yes_price))
                    no_price = max(0.01, min(0.99, no_price))
                    results.append(
                        MarketInfo(
                            ticker=m.get("conditionId") or m.get("id", ""),
                            slug=m.get("slug", ""),
                            category=m.get("category", ""),
                            end_date=m.get("endDate"),
                            volume=float(m.get("volume", 0) or 0),
                            liquidity=float(m.get("liquidity", 0) or 0),
                            yes_price=yes_price,
                            no_price=no_price,
                            question=m.get("question", ""),
                            metadata=m,
                        )
                    )
                except Exception as e:
                    logger.debug(f"market_scanner: skipping malformed market: {e}")

            if len(page) < page_size:
                break

            offset += page_size
            pages_fetched += 1

    logger.info(f"market_scanner: fetched {len(results)} active markets")
    return results[:max_markets]


async def fetch_markets_by_keywords(
    keywords: list[str],
    limit: int | None = None,
) -> list[MarketInfo]:
    """Filter active markets by keyword match on question or slug."""
    all_markets = await fetch_all_active_markets(limit=limit or 500)
    kw_lower = [k.lower() for k in keywords]
    return [
        m
        for m in all_markets
        if any(kw in m.question.lower() or kw in m.slug.lower() for kw in kw_lower)
    ]


async def fetch_short_duration_token_ids(
    limit: int | None = None,
    max_hours_to_resolution: float | None = None,
    min_volume: float | None = None,
) -> list[str]:
    """Return CLOB token IDs for active markets resolving soon.

    This feeds the public Polymarket market WebSocket subscription. The market
    channel requires outcome token IDs (`asset_ids`), not condition IDs.
    """

    max_hours = max_hours_to_resolution if max_hours_to_resolution is not None else getattr(
        settings, "SHORT_MARKET_MAX_HOURS_TO_RESOLUTION", 24.0
    )
    min_vol = min_volume if min_volume is not None else getattr(
        settings, "SHORT_MARKET_MIN_VOLUME", 100.0
    )
    subscription_limit = int(limit or getattr(settings, "POLYMARKET_WS_SUBSCRIPTION_LIMIT", 200))
    markets = await fetch_all_active_markets(limit=getattr(settings, "SCANNER_MAX_MARKETS", 10000))
    now = datetime.now(timezone.utc)
    scored: list[tuple[float, list[str]]] = []

    for market in markets:
        if market.volume < min_vol:
            continue
        if not market.end_date:
            continue
        try:
            end_dt = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        hours_remaining = (end_dt - now).total_seconds() / 3600.0
        if hours_remaining <= 0 or hours_remaining > max_hours:
            continue
        raw_token_ids = market.metadata.get("clobTokenIds") or []
        if isinstance(raw_token_ids, str):
            try:
                raw_token_ids = json.loads(raw_token_ids)
            except json.JSONDecodeError:
                raw_token_ids = []
        token_ids = [str(token_id) for token_id in raw_token_ids if token_id]
        if token_ids:
            scored.append((market.volume, token_ids))

    tokens: list[str] = []
    seen: set[str] = set()
    for _volume, token_ids in sorted(scored, key=lambda item: item[0], reverse=True):
        for token_id in token_ids:
            if token_id in seen:
                continue
            seen.add(token_id)
            tokens.append(token_id)
            if len(tokens) >= subscription_limit:
                logger.info(f"market_scanner: selected {len(tokens)} short-duration WS token IDs")
                return tokens
    logger.info(f"market_scanner: selected {len(tokens)} short-duration WS token IDs")
    return tokens


async def _fetch_page(client: httpx.AsyncClient, params: dict) -> list[dict]:
    """Fetch one page from Gamma /markets with retry."""
    url = f"{GAMMA_HOST}/markets"
    for attempt in range(3):
        try:
            async with _SCAN_SEMAPHORE:
                resp = await client.get(url, params=params)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code >= 500:
                logger.warning(
                    f"market_scanner: Gamma {resp.status_code} on attempt {attempt + 1}"
                )
                if attempt < 2:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
            return []
        except httpx.TimeoutException:
            logger.warning(f"market_scanner: timeout on attempt {attempt + 1}")
            if attempt < 2:
                await asyncio.sleep(1.0)
    return []
