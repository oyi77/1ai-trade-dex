"""AzuroProvider — DataProvider implementation for Azuro Protocol-based platforms.

Azuro Protocol is an on-chain prediction/betting protocol deployed on Gnosis Chain
and Polygon. Both predict.fun and bookmaker.xyz use Azuro as their backend.

Data is fetched via The Graph GraphQL subgraph (read-only public endpoint).
Order placement requires EVM wallet + Web3 smart contract call.

ENV VARS:
    AZURO_GRAPH_URL  — The Graph subgraph endpoint (default: Gnosis xDai)
    AZURO_RPC_URL    — EVM JSON-RPC endpoint for transaction broadcast
    AZURO_CHAIN_ID   — Chain ID: 100 (Gnosis) or 137 (Polygon)
    AZURO_CACHE_TTL_SECONDS — GraphQL response cache TTL (default: 60)
"""

from __future__ import annotations

import os
import time
from typing import Optional

import httpx
from loguru import logger

from backend.data.provider import DataProvider, MarketEntry, PositionEntry, BalanceInfo

_AZURO_GRAPH_URL_DEFAULT = (
    "https://api.thegraph.com/subgraphs/name/azuro-protocol/azuro-subgraph-xdai"
)

_GQL_ACTIVE_MARKETS = """
{
  games(first: %d, where: {startsAt_gt: "%s", hasActiveConditions: true}) {
    gameId
    title
    startsAt
    sport { name }
    league { name country { name } }
    conditions(where: {isExpressForbidden: false, status: Created}) {
      conditionId
      outcomes { id currentOdds }
    }
  }
}
"""


class AzuroProvider(DataProvider):
    """DataProvider wrapping Azuro Protocol GraphQL subgraph.

    Read operations use public GraphQL endpoint.
    Write operations (order placement) require web3.py + EVM private key.

    NOTE: This is a shared base class. PredictFunProvider and BookmakerXyzProvider
    both delegate to this class — they differ only in platform_name and platform_url.
    """

    def __init__(
        self,
        platform: str = "azuro",
        graph_url: Optional[str] = None,
        cache_ttl: int = 60,
    ) -> None:
        self._platform = platform
        self._graph_url = graph_url or os.getenv(
            "AZURO_GRAPH_URL", _AZURO_GRAPH_URL_DEFAULT
        )
        self._rpc_url = os.getenv("AZURO_RPC_URL", "")
        self._chain_id = int(os.getenv("AZURO_CHAIN_ID", "100"))
        self._cache_ttl = int(os.getenv("AZURO_CACHE_TTL_SECONDS", str(cache_ttl)))
        self._cache: dict = {}
        self._cache_ts: float = 0.0

    @property
    def platform_name(self) -> str:
        return self._platform

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self._graph_url,
                    json={"query": "{ __typename }"},
                )
                return resp.status_code == 200
        except Exception:
            logger.debug("Azuro health check failed for platform={}", self._platform)
            return False

    async def _graphql(self, query: str) -> dict:
        """Send a GraphQL query with TTL cache."""
        cache_key = hash(query)
        now = time.monotonic()
        if cache_key in self._cache and (now - self._cache_ts) < self._cache_ttl:
            return self._cache[cache_key]

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self._graph_url, json={"query": query})
            resp.raise_for_status()
            result = resp.json()

        self._cache[cache_key] = result
        self._cache_ts = now
        return result

    async def get_markets(
        self, category: Optional[str] = None, limit: int = 100
    ) -> list[MarketEntry]:
        now_ts = int(time.time())
        gql = _GQL_ACTIVE_MARKETS % (limit, now_ts)
        try:
            data = await self._graphql(gql)
        except Exception as exc:
            logger.warning("Azuro get_markets failed: {}", exc)
            return []

        games = (data.get("data") or {}).get("games", [])
        entries: list[MarketEntry] = []
        for game in games:
            for cond in game.get("conditions", []):
                outcomes = cond.get("outcomes", [])
                yes_odds = float(outcomes[0].get("currentOdds", 2.0)) if outcomes else 2.0
                entries.append(
                    MarketEntry(
                        ticker=cond.get("conditionId", ""),
                        question=game.get("title", ""),
                        market_id=cond.get("conditionId", ""),
                        platform=self._platform,
                        current_price=round(1.0 / yes_odds, 4) if yes_odds else 0.5,
                        volume_24h=0.0,
                        liquidity=0.0,
                        created_at=str(game.get("startsAt", "")),
                    )
                )
        return entries

    async def get_orderbook(self, market_id: str) -> dict:
        # Azuro uses on-chain orderbook — no REST orderbook endpoint
        return {"bids": [], "asks": [], "market_id": market_id, "platform": self._platform}

    async def get_positions(self) -> list[PositionEntry]:
        # Requires on-chain query — not implemented in this stub
        logger.debug("AzuroProvider.get_positions() not implemented — requires on-chain query")
        return []

    async def get_balance(self) -> BalanceInfo:
        # Requires on-chain query — not implemented in this stub
        logger.debug("AzuroProvider.get_balance() not implemented — requires on-chain query")
        return BalanceInfo(available=0.0, locked=0.0, total=0.0)

    async def place_order(
        self, market_id: str, side: str, size: float, price: float, **kwargs
    ) -> dict:
        """Place a bet on Azuro via smart contract call.

        Requires AZURO_RPC_URL and private_key in kwargs or env.
        Returns {"tx_hash": "0x...", "status": "submitted"} on success.
        """
        private_key: str = kwargs.get("private_key", "") or os.getenv(
            "WEB3_PRIVATE_KEY_AZURO", ""
        )

        if not private_key or not self._rpc_url:
            logger.warning(
                "AzuroProvider.place_order: missing AZURO_RPC_URL or private key — "
                "returning dry-run result"
            )
            return {"tx_hash": "", "status": "dry_run", "platform": self._platform}

        # NOTE: Full Web3 smart contract integration is planned in the plugin-system task 26a.
        # This stub returns a dry-run result until the AzuroClient is implemented.
        logger.info(
            "AzuroProvider.place_order dry-run: market_id={} side={} size={} price={}",
            market_id,
            side,
            size,
            price,
        )
        return {"tx_hash": "", "status": "dry_run", "platform": self._platform}

    async def cancel_order(self, order_id: str) -> bool:
        # Azuro bets are non-cancellable once submitted on-chain
        logger.warning(
            "AzuroProvider.cancel_order: Azuro bets are non-cancellable (order_id={})",
            order_id,
        )
        return False


class PredictFunProvider(AzuroProvider):
    """DataProvider for predict.fun — thin Azuro wrapper."""

    def __init__(self) -> None:
        super().__init__(platform="predict_fun")

    @property
    def platform_name(self) -> str:
        return "predict_fun"


class BookmakerXyzProvider(AzuroProvider):
    """DataProvider for bookmaker.xyz — thin Azuro wrapper (sports focus)."""

    def __init__(self) -> None:
        super().__init__(platform="bookmaker_xyz")

    @property
    def platform_name(self) -> str:
        return "bookmaker_xyz"
