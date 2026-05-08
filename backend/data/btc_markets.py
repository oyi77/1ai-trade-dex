"""BTC 5-minute market fetcher for Polymarket."""

import httpx
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional, List
from dataclasses import dataclass

from backend.core.market_scanner import fetch_markets_by_keywords
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.data.market_types import UnifiedMarketView
from backend.config import settings

logger = logging.getLogger("trading_bot")

GAMMA_API = settings.GAMMA_API_URL

gamma_breaker = CircuitBreaker("gamma_api")

# Strict regex: only match real BTC 5-min window slugs (e.g. btc-updown-5m-1708531200)
_BTC_SLUG_RE = re.compile(r"^btc-updown-5m-\d{10}$")


def is_valid_btc_slug(slug: str) -> bool:
    """Return True only if slug matches the exact BTC 5-min pattern."""
    return bool(_BTC_SLUG_RE.match(slug))


@dataclass
class BtcMarket:
    """A single BTC 5-minute Up/Down market."""

    slug: str
    market_id: str
    up_price: float
    down_price: float
    window_start: datetime
    window_end: datetime
    volume: float
    closed: bool
    up_token_id: str = ""  # CLOB token ID for the UP (YES) outcome
    down_token_id: str = ""  # CLOB token ID for the DOWN (NO) outcome

    @property
    def event_slug(self) -> str:
        return self.slug

    @property
    def spread(self) -> float:
        return abs(1.0 - self.up_price - self.down_price)

    @property
    def time_until_end(self) -> float:
        """Seconds until this window ends."""
        now = datetime.now(timezone.utc)
        return (self.window_end - now).total_seconds()

    @property
    def is_active(self) -> bool:
        """Window is currently in progress."""
        now = datetime.now(timezone.utc)
        return self.window_start <= now <= self.window_end and not self.closed

    @property
    def is_upcoming(self) -> bool:
        """Window hasn't started yet."""
        now = datetime.now(timezone.utc)
        return now < self.window_start and not self.closed

    def to_unified(self) -> UnifiedMarketView:
        """
        Convert to UnifiedMarketView for API responses.

        This is a lightweight adapter, not a base class inheritance pattern.
        BtcMarket and WeatherMarket remain independent domain models.
        """
        return UnifiedMarketView(
            slug=self.slug,
            platform="polymarket",
            title=f"BTC {self.window_start.strftime('%H:%M')} - {self.window_end.strftime('%H:%M')} UTC",
            yes_price=self.up_price,
            no_price=self.down_price,
            volume=self.volume,
            closes_at=self.window_end,
            extra={
                "market_id": self.market_id,
                "window_start": self.window_start.isoformat(),
                "window_end": self.window_end.isoformat(),
                "up_token_id": self.up_token_id,
                "down_token_id": self.down_token_id,
                "type": "btc-5min",
            },
        )


def _round_to_5min(ts: float) -> int:
    """Round a unix timestamp down to the nearest 5-minute boundary."""
    return int(ts) // 300 * 300


def _compute_window_slugs(count: int = 5) -> List[str]:
    """
    Compute event slugs for the current and upcoming 5-min windows.

    Slug pattern: btc-updown-5m-{unix_timestamp}
    where timestamp is the END of the 5-min window.
    """
    now = time.time()
    current_boundary = _round_to_5min(now)

    # The current window ends at the next boundary
    next_boundary = current_boundary + 300

    slugs = []
    for i in range(count):
        end_ts = next_boundary + (i * 300)
        slugs.append(f"btc-updown-5m-{end_ts}")

    return slugs


def _parse_event_to_btc_market(event: dict) -> Optional[BtcMarket]:
    """Parse a Polymarket event into a BtcMarket."""
    markets = event.get("markets", [])
    if not markets:
        return None

    market = markets[0]

    # Parse outcome prices
    outcome_prices = market.get("outcomePrices", "")
    up_price = 0.5
    down_price = 0.5
    if outcome_prices:
        try:
            prices = (
                json.loads(outcome_prices)
                if isinstance(outcome_prices, str)
                else outcome_prices
            )
            if isinstance(prices, list) and len(prices) >= 2:
                up_price = float(prices[0])
                down_price = float(prices[1])
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Parse timestamps
    slug = event.get("slug", "")
    start_str = event.get("startDate") or market.get("startDate")
    end_str = event.get("endDate") or market.get("endDate")

    window_start = datetime.now(timezone.utc)
    window_end = datetime.now(timezone.utc)

    if start_str:
        try:
            window_start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

    if end_str:
        try:
            window_end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

    # Parse CLOB token IDs for order placement (testnet/live modes)
    up_token_id = ""
    down_token_id = ""
    raw_token_ids = market.get("clobTokenIds")
    if raw_token_ids:
        try:
            token_ids = (
                json.loads(raw_token_ids)
                if isinstance(raw_token_ids, str)
                else raw_token_ids
            )
            if isinstance(token_ids, list) and len(token_ids) >= 2:
                up_token_id = str(token_ids[0])
                down_token_id = str(token_ids[1])
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.debug(f"Failed to parse clobTokenIds: {e}")

    return BtcMarket(
        slug=slug,
        market_id=str(market.get("id", "")),
        up_price=up_price,
        down_price=down_price,
        window_start=window_start,
        window_end=window_end,
        volume=float(market.get("volume", 0) or 0),
        closed=bool(market.get("closed", False) or event.get("closed", False)),
        up_token_id=up_token_id,
        down_token_id=down_token_id,
    )


async def fetch_btc_market_by_slug(slug: str) -> Optional[BtcMarket]:
    """Fetch a single BTC 5-min market by its event slug."""
    if not is_valid_btc_slug(slug):
        logger.debug(f"Rejected invalid BTC slug: {slug}")
        return None

    url = f"{GAMMA_API}/events"
    params = {"slug": slug}

    try:

        async def _do_fetch():
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()

        events = await gamma_breaker.call(_do_fetch)

        if not events:
            return None

        event = events[0] if isinstance(events, list) else events
        return _parse_event_to_btc_market(event)

    except CircuitOpenError:
        logger.warning("Gamma API circuit open, skipping BTC market fetch")
        return None
    except Exception as e:
        logger.debug(f"Failed to fetch BTC market {slug}: {e}")
        return None


async def fetch_active_btc_markets(
    keywords: List[str] = None,
) -> List[BtcMarket]:
    """
    Fetch current and upcoming BTC 5-min markets from Polymarket.

    Uses fetch_markets_by_keywords() as the primary source, with direct
    slug-based fetching as a supplement for time-windowed markets.
    """
    if keywords is None:
        keywords = ["btc", "bitcoin", "btc-up"]

    markets: List[BtcMarket] = []
    seen_slugs: set = set()

    # Method 1: Keyword-based scanner (primary)
    try:
        scanner_results = await fetch_markets_by_keywords(keywords)
        for info in scanner_results:
            # Only accept slugs matching the BTC 5-min pattern
            if not is_valid_btc_slug(info.slug):
                continue
            if info.slug in seen_slugs:
                continue
            seen_slugs.add(info.slug)
            # Fetch the full event to get window timestamps
            market = await fetch_btc_market_by_slug(info.slug)
            if market and not market.closed:
                markets.append(market)
    except Exception as e:
        logger.debug(f"BTC keyword scanner failed: {e}")

    # Method 2: Compute expected slugs and fetch directly (supplement)
    expected_slugs = _compute_window_slugs(count=6)
    for slug in expected_slugs:
        if slug in seen_slugs:
            continue
        market = await fetch_btc_market_by_slug(slug)
        if market and market.slug not in seen_slugs:
            seen_slugs.add(market.slug)
            if not market.closed:
                markets.append(market)

    # Sort by window end time (soonest first)
    markets.sort(key=lambda m: m.window_end)

    logger.info(f"Fetched {len(markets)} active BTC 5-min markets")
    return markets


async def fetch_btc_market_for_settlement(slug: str) -> Optional[BtcMarket]:
    """
    Fetch a BTC market for settlement purposes (includes closed markets).
    """
    url = f"{GAMMA_API}/events"
    params = {"slug": slug}

    try:

        async def _do_fetch():
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()

        events = await gamma_breaker.call(_do_fetch)

        if not events:
            return None

        event = events[0] if isinstance(events, list) else events
        return _parse_event_to_btc_market(event)

    except CircuitOpenError:
        logger.warning("Gamma API circuit open, skipping settlement fetch for %s", slug)
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch BTC market for settlement {slug}: {e}")
        return None


if __name__ == "__main__":
    import asyncio

    async def test():
        print("Fetching active BTC 5-min markets...")
        markets = await fetch_active_btc_markets()
        print(f"Found {len(markets)} markets")

        for m in markets:
            print(f"\n  {m.slug}")
            print(f"  Up: {m.up_price:.2%} | Down: {m.down_price:.2%}")
            print(f"  Window: {m.window_start} -> {m.window_end}")
            print(f"  Volume: ${m.volume:,.0f}")
            print(f"  Active: {m.is_active} | Upcoming: {m.is_upcoming}")

    asyncio.run(test())
