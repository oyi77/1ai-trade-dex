"""Hyperliquid prediction market client.

Supports fetching markets, orderbook, and trades from Hyperliquid prediction
markets via their API. Can also integrate with PMXT aggregator.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from backend.config import settings
from backend.data.shared_client import get_shared_client
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError

from loguru import logger

hl_breaker = CircuitBreaker(
    "hyperliquid_api", failure_threshold=3, recovery_timeout=120.0
)

# Hyperliquid API endpoints
DEFAULT_HL_API_URL = "https://api.hyperliquid.xyz"
DEFAULT_HL_WS_URL = "wss://api.hyperliquid.xyz/ws"

# Cache TTLs
CACHE_TTL_MARKETS = 60  # 1 minute for market list
CACHE_TTL_ORDERBOOK = 5  # 5 seconds for orderbook
CACHE_TTL_TRADES = 30  # 30 seconds for trades


@dataclass
class HLOrderBookLevel:
    """Single price level in the Hyperliquid orderbook."""

    price: float
    size: float


@dataclass
class HLMarket:
    """A Hyperliquid prediction market."""

    market_id: str
    question: str
    outcomes: list[str]
    outcome_prices: list[float]
    volume_24h: float
    liquidity: float
    end_time: Optional[str] = None
    status: str = "active"
    raw: dict = field(default_factory=dict)


@dataclass
class HLTrade:
    """A Hyperliquid trade event."""

    trade_id: str
    market_id: str
    side: str
    price: float
    size: float
    timestamp: float
    tx_hash: str = ""


@dataclass
class HyperliquidClient:
    """Client for Hyperliquid prediction markets.

    Args:
        api_url: Base API URL. Falls back to settings.HYPERLIQUID_API_URL.
    """

    api_url: str = ""
    _cache: dict[str, tuple[float, Any]] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if not self.api_url:
            self.api_url = getattr(settings, "HYPERLIQUID_API_URL", DEFAULT_HL_API_URL)

    def _get_cached(self, key: str, ttl: float) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry is not None and (time.time() - entry[0]) < ttl:
            return entry[1]
        return None

    def _set_cached(self, key: str, data: Any) -> None:
        self._cache[key] = (time.time(), data)

    async def _post(self, endpoint: str, payload: dict) -> Optional[dict]:
        """Make a POST request to the Hyperliquid API."""

        async def _do_post() -> dict:
            client = get_shared_client()
            resp = await client.post(f"{self.api_url}{endpoint}", json=payload)
            resp.raise_for_status()
            return resp.json()

        try:
            return await hl_breaker.call(_do_post)
        except CircuitOpenError:
            logger.warning("[hyperliquid] API circuit open, skipping")
            return None
        except Exception as e:
            logger.error("[hyperliquid] POST %s failed: %s", endpoint, e)
            return None

    async def _get(self, endpoint: str, params: Optional[dict] = None) -> Optional[Any]:
        """Make a GET request to the Hyperliquid API."""

        async def _do_get() -> Any:
            client = get_shared_client()
            resp = await client.get(f"{self.api_url}{endpoint}", params=params)
            resp.raise_for_status()
            return resp.json()

        try:
            return await hl_breaker.call(_do_get)
        except CircuitOpenError:
            logger.warning("[hyperliquid] API circuit open, skipping")
            return None
        except Exception as e:
            logger.error("[hyperliquid] GET %s failed: %s", endpoint, e)
            return None

    async def get_markets(self, category: Optional[str] = None) -> list[HLMarket]:
        """Fetch available prediction markets from Hyperliquid.

        Args:
            category: Optional category filter (e.g., 'crypto', 'politics').

        Returns:
            List of HLMarket objects.
        """
        cache_key = f"hl_markets_{category or 'all'}"
        cached = self._get_cached(cache_key, CACHE_TTL_MARKETS)
        if cached is not None:
            return cached

        data = await self._post("/info", {"type": "meta"})
        if data is None:
            return []

        markets = []
        # Hyperliquid returns prediction markets in the "predictionMarkets" key
        raw_markets = data.get("predictionMarkets", data.get("markets", []))
        for m in raw_markets:
            try:
                outcomes = m.get("outcomes", ["Yes", "No"])
                prices_raw = m.get("outcomePrices", m.get("prices", [0.5, 0.5]))
                prices = [float(p) for p in prices_raw]

                market = HLMarket(
                    market_id=str(m.get("id", m.get("marketId", ""))),
                    question=m.get("question", m.get("name", "")),
                    outcomes=outcomes,
                    outcome_prices=prices,
                    volume_24h=float(m.get("volume24h", m.get("volume", 0))),
                    liquidity=float(m.get("liquidity", 0)),
                    end_time=m.get("endTime", m.get("end_time")),
                    status=m.get("status", "active"),
                    raw=m,
                )
                if category:
                    market_category = m.get("category", "").lower()
                    if category.lower() not in market_category:
                        continue
                markets.append(market)
            except (TypeError, ValueError, KeyError) as e:
                logger.debug("[hyperliquid] Skipping malformed market: %s", e)
                continue

        self._set_cached(cache_key, markets)
        logger.info("[hyperliquid] Fetched %d prediction markets", len(markets))
        return markets

    async def get_orderbook(self, market_id: str) -> dict[str, list[HLOrderBookLevel]]:
        """Fetch orderbook for a Hyperliquid prediction market.

        Args:
            market_id: The market identifier.

        Returns:
            Dict with 'bids' and 'asks' lists of HLOrderBookLevel.
        """
        cache_key = f"hl_book_{market_id}"
        cached = self._get_cached(cache_key, CACHE_TTL_ORDERBOOK)
        if cached is not None:
            return cached

        data = await self._post(
            "/info",
            {
                "type": "l2Book",
                "coin": market_id,
            },
        )
        if data is None:
            return {"bids": [], "asks": []}

        bids = []
        asks = []

        # Parse raw book format: {coin, time, levels: [[bids], [asks]]}
        levels = data if isinstance(data, list) else data.get("levels", [[], []])
        if isinstance(levels, list) and len(levels) >= 2:
            for entry in levels[0][:50]:  # bids
                try:
                    bids.append(
                        HLOrderBookLevel(
                            price=float(entry.get("px", entry.get("price", 0))),
                            size=float(entry.get("sz", entry.get("size", 0))),
                        )
                    )
                except (TypeError, ValueError):
                    continue
            for entry in levels[1][:50]:  # asks
                try:
                    asks.append(
                        HLOrderBookLevel(
                            price=float(entry.get("px", entry.get("price", 0))),
                            size=float(entry.get("sz", entry.get("size", 0))),
                        )
                    )
                except (TypeError, ValueError):
                    continue

        book = {"bids": bids, "asks": asks}
        self._set_cached(cache_key, book)
        return book

    async def get_recent_trades(
        self, market_id: str, limit: int = 100
    ) -> list[HLTrade]:
        """Fetch recent trades for a Hyperliquid prediction market.

        Args:
            market_id: The market identifier.
            limit: Max number of trades to return.

        Returns:
            List of HLTrade objects.
        """
        cache_key = f"hl_trades_{market_id}_{limit}"
        cached = self._get_cached(cache_key, CACHE_TTL_TRADES)
        if cached is not None:
            return cached

        data = await self._post(
            "/info",
            {
                "type": "recentTrades",
                "coin": market_id,
            },
        )
        if data is None or not isinstance(data, list):
            return []

        trades = []
        for t in data[:limit]:
            try:
                trade = HLTrade(
                    trade_id=str(t.get("tid", t.get("id", ""))),
                    market_id=market_id,
                    side="BUY" if t.get("side") == "B" else "SELL",
                    price=float(t.get("px", t.get("price", 0))),
                    size=float(t.get("sz", t.get("size", 0))),
                    timestamp=float(t.get("time", t.get("timestamp", 0))) / 1000.0,
                    tx_hash=t.get("hash", ""),
                )
                trades.append(trade)
            except (TypeError, ValueError) as e:
                logger.debug("[hyperliquid] Skipping malformed trade: %s", e)
                continue

        self._set_cached(cache_key, trades)
        return trades

    def clear_cache(self) -> int:
        """Clear all cached results."""
        count = len(self._cache)
        self._cache.clear()
        return count

    async def health_check(self) -> bool:
        """Lightweight liveness check."""
        try:
            data = await self._post("/info", {"type": "meta"})
            return data is not None
        except Exception as e:
            logger.debug("[hyperliquid] Health check failed: %s", e)
            return False
