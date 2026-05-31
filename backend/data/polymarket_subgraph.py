"""The Graph subgraph client for querying Polymarket on-chain data.

Queries the Polymarket subgraph via The Graph's GraphQL API for market data,
trade history, and settlement events. Used for on-chain validation and backtesting.
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

subgraph_breaker = CircuitBreaker(
    "subgraph_api", failure_threshold=3, recovery_timeout=120.0
)

# Default Polymarket subgraph endpoint (The Graph hosted service)
DEFAULT_SUBGRAPH_URL = (
    "https://gateway.thegraph.com/api/"
    "{api_key}/subgraphs/id/CitCUH6JGPVnR5PNFCHTVz1v1qJBFq3HHqfFGBTM1fF"
)

# Cache TTLs
CACHE_TTL_SHORT = 300  # 5 minutes for live data
CACHE_TTL_LONG = 3600  # 1 hour for historical data

# GraphQL queries
QUERY_MARKETS = """
query Markets($first: Int!, $skip: Int!) {
  markets(first: $first, skip: $skip, orderBy: volume, orderDirection: desc) {
    id
    question
    outcomes
    outcomePrices
    volume
    liquidity
    createdAt
    resolvedAt
    resolutionSource
  }
}
"""

QUERY_TRADES = """
query Trades($first: Int!, $skip: Int!, $market: String) {
  trades(
    first: $first
    skip: $skip
    orderBy: timestamp
    orderDirection: desc
    where: { market: $market }
  ) {
    id
    market { id question }
    maker
    taker
    side
    amount
    price
    timestamp
    transactionHash
  }
}
"""

QUERY_SETTLEMENTS = """
query Settlements($first: Int!, $skip: Int!) {
  redemptions(
    first: $first
    skip: $skip
    orderBy: timestamp
    orderDirection: desc
  ) {
    id
    market { id question }
    redeemer
    outcomeIndex
    amount
    timestamp
    transactionHash
  }
}
"""


@dataclass
class SubgraphCacheEntry:
    """Cached subgraph query result."""

    data: Any
    fetched_at: float
    ttl: float

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.fetched_at) > self.ttl


@dataclass
class PolymarketSubgraphClient:
    """Client for querying the Polymarket subgraph via The Graph GraphQL API.

    Args:
        api_key: The Graph API key. Falls back to settings.THEGRAPH_API_KEY.
        subgraph_url: Override subgraph URL. Falls back to default hosted endpoint.
    """

    api_key: str = ""
    subgraph_url: str = ""
    _cache: dict[str, SubgraphCacheEntry] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if not self.api_key:
            self.api_key = getattr(settings, "THEGRAPH_API_KEY", "")
        if not self.subgraph_url:
            configured_url = getattr(settings, "POLYMARKET_SUBGRAPH_URL", "")
            if configured_url:
                self.subgraph_url = configured_url
            else:
                self.subgraph_url = DEFAULT_SUBGRAPH_URL.format(api_key=self.api_key)

    def _get_cached(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry is not None and not entry.is_expired:
            return entry.data
        return None

    def _set_cached(self, key: str, data: Any, ttl: float) -> None:
        self._cache[key] = SubgraphCacheEntry(
            data=data, fetched_at=time.time(), ttl=ttl
        )

    async def _query_graphql(
        self, query: str, variables: dict, ttl: float, cache_key: str
    ) -> Any:
        """Execute a GraphQL query against the subgraph with caching."""
        cached = self._get_cached(cache_key)
        if cached is not None:
            logger.debug("Subgraph cache hit: %s", cache_key)
            return cached

        async def _execute() -> Any:
            payload = {"query": query, "variables": variables}
            client = get_shared_client()
            resp = await client.post(self.subgraph_url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if "errors" in data:
                logger.error("Subgraph GraphQL errors: %s", data["errors"])
                return None

            result = data.get("data", {})
            self._set_cached(cache_key, result, ttl)
            return result

        try:
            return await subgraph_breaker.call(_execute)
        except CircuitOpenError:
            logger.warning("[subgraph] Subgraph API circuit open, skipping")
            return None
        except Exception as e:
            logger.error("[subgraph] GraphQL query failed: %s", e)
            return None

    async def get_markets(self, first: int = 100, skip: int = 0) -> list[dict]:
        """Fetch Polymarket markets from the subgraph.

        Returns:
            List of market dicts with id, question, volume, liquidity, etc.
        """
        result = await self._query_graphql(
            QUERY_MARKETS,
            {"first": first, "skip": skip},
            ttl=CACHE_TTL_SHORT,
            cache_key=f"markets_{first}_{skip}",
        )
        if result is None:
            return []
        return result.get("markets", [])

    async def get_trades(
        self,
        market_id: Optional[str] = None,
        first: int = 100,
        skip: int = 0,
    ) -> list[dict]:
        """Fetch trade history from the subgraph.

        Args:
            market_id: Optional filter by market ID.
            first: Number of trades to fetch.
            skip: Pagination offset.

        Returns:
            List of trade dicts with id, market, maker, taker, amount, price, etc.
        """
        variables: dict[str, Any] = {"first": first, "skip": skip, "market": market_id}
        result = await self._query_graphql(
            QUERY_TRADES,
            variables,
            ttl=CACHE_TTL_SHORT,
            cache_key=f"trades_{market_id}_{first}_{skip}",
        )
        if result is None:
            return []
        return result.get("trades", [])

    async def get_settlements(self, first: int = 100, skip: int = 0) -> list[dict]:
        """Fetch settlement/redemption events from the subgraph.

        Returns:
            List of redemption dicts with id, market, redeemer, outcomeIndex, etc.
        """
        result = await self._query_graphql(
            QUERY_SETTLEMENTS,
            {"first": first, "skip": skip},
            ttl=CACHE_TTL_LONG,
            cache_key=f"settlements_{first}_{skip}",
        )
        if result is None:
            return []
        return result.get("redemptions", [])

    async def get_market_by_id(self, market_id: str) -> Optional[dict]:
        """Fetch a single market by its subgraph ID.

        Returns:
            Market dict or None if not found.
        """
        query = """
        query Market($id: String!) {
            market(id: $id) {
                id
                question
                outcomes
                outcomePrices
                volume
                liquidity
                createdAt
                resolvedAt
            }
        }
        """
        result = await self._query_graphql(
            query,
            {"id": market_id},
            ttl=CACHE_TTL_SHORT,
            cache_key=f"market_{market_id}",
        )
        if result is None:
            return None
        return result.get("market")

    def clear_cache(self) -> int:
        """Clear all cached results. Returns number of entries cleared."""
        count = len(self._cache)
        self._cache.clear()
        return count

    async def health_check(self) -> bool:
        """Lightweight liveness check — query a single market."""
        try:
            markets = await self.get_markets(first=1)
            return isinstance(markets, list)
        except Exception as e:
            logger.debug("[subgraph] Health check failed: %s", e)
            return False
