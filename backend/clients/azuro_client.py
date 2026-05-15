"""Azuro Protocol GraphQL + Web3 client."""
import os
import time
import httpx
from loguru import logger


class AzuroClient:
    """Azuro Protocol client for querying markets and placing bets on Azuro-powered venues."""

    DEFAULT_GRAPH_URL = "https://api.thegraph.com/subgraphs/name/azuro-protocol/azuro-subgraph-xdai"

    def __init__(self, graph_url: str = None, rpc_url: str = None, chain_id: int = None):
        self._graph_url = graph_url or os.getenv("AZURO_GRAPH_URL", self.DEFAULT_GRAPH_URL)
        self._rpc_url = rpc_url or os.getenv("AZURO_RPC_URL", "https://rpc.gnosischain.com")
        self._chain_id = chain_id or int(os.getenv("AZURO_CHAIN_ID", "100"))
        self._cache: dict = {}
        self._cache_ttl = int(os.getenv("AZURO_CACHE_TTL_SECONDS", "60"))

    async def cached_query(self, gql: str, variables: dict = None) -> dict:
        """Execute GraphQL query with caching."""
        key = (gql, str(variables))
        now = time.time()
        if key in self._cache and now - self._cache[key]["ts"] < self._cache_ttl:
            return self._cache[key]["data"]
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self._graph_url, json={"query": gql, "variables": variables or {}})
            resp.raise_for_status()
            data = resp.json()
        self._cache[key] = {"data": data, "ts": now}
        return data

    async def get_markets(self, limit: int = 200, active_only: bool = True) -> list:
        """Query Azuro subgraph for markets."""
        gql = """query GetMarkets($limit: Int) { conditions(first: $limit) { conditionId outcomes { outcomeId title currentValue } } }"""
        result = await self.cached_query(gql, {"limit": limit})
        return result.get("data", {}).get("conditions", [])

    async def health_check(self) -> bool:
        """Check if Azuro GraphQL endpoint is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(self._graph_url, json={"query": "{ __typename }"})
                return resp.status_code == 200
        except Exception:
            return False

    async def sign_and_send_bet(self, private_key: str, condition_id: str, outcome_index: int, amount_wei: int) -> str:
        """Sign and send a bet via Web3.py contract call."""
        try:
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider(self._rpc_url))
            account = w3.eth.account.from_key(private_key)
            # Stub: real implementation would call the LP contract
            # Return mock tx hash for now (real impl needs ABI)
            logger.info("sign_and_send_bet called", condition_id=condition_id, outcome_index=outcome_index)
            return f"0x{'0' * 64}"
        except ImportError:
            raise RuntimeError("web3 package required for live betting")
