"""SX.bet REST + EIP-712 client."""
import os
import httpx
from loguru import logger


class SXBetClient:
    """SX.bet API client."""

    def __init__(self, base_url: str = None):
        self._base_url = (base_url or os.getenv("SXBET_API_URL", "https://api.sx.bet")).rstrip("/")

    async def get_sports(self) -> list:
        """Get available sports."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self._base_url}/sports")
            resp.raise_for_status()
            return resp.json()

    async def get_markets(self, sport_ids: list = None, limit: int = 200) -> list:
        """Get available markets, optionally filtered by sport."""
        params = {"limit": limit}
        if sport_ids:
            params["sportIds"] = ",".join(str(s) for s in sport_ids)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self._base_url}/markets/active", params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_orderbook(self, market_hash: str) -> dict:
        """Get orderbook for a specific market."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self._base_url}/orders", params={"marketHashes": market_hash})
            resp.raise_for_status()
            return resp.json()

    async def place_maker_order(self, market_hash: str, outcome_index: int, odds: float, stake_wei: int, private_key: str) -> dict:
        """Place a maker order. EIP-712 signing stub — real impl would sign the maker order struct."""
        logger.info("SXBetClient.place_maker_order called", market_hash=market_hash, outcome_index=outcome_index)
        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {"marketHash": market_hash, "outcomeIndex": outcome_index, "odds": odds, "stakeWei": stake_wei}
            resp = await client.post(f"{self._base_url}/orders/new", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def health_check(self) -> bool:
        """Check if SX.bet API is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/sports")
                return resp.status_code == 200
        except Exception:
            return False
