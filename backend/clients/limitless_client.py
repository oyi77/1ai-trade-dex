"""Limitless Exchange REST + EIP-712 client."""
import os
import httpx
from loguru import logger


class LimitlessClient:
    """Limitless Exchange API client."""

    def __init__(self, base_url: str = None):
        self._base_url = (base_url or os.getenv("LIMITLESS_API_URL", "https://api.limitless.exchange")).rstrip("/")

    async def get_markets(self, limit: int = 100) -> list:
        """Get available markets from Limitless Exchange."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self._base_url}/markets", params={"limit": limit})
            resp.raise_for_status()
            return resp.json()

    async def get_orderbook(self, market_id: str) -> dict:
        """Get orderbook for a specific market."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self._base_url}/orderbook", params={"marketId": market_id})
            resp.raise_for_status()
            return resp.json()

    async def place_order(self, market_id: str, side: str, size: float, price: float, private_key: str) -> dict:
        """Place an order. EIP-712 signing stub — real impl would sign the order struct."""
        logger.info("LimitlessClient.place_order called", market_id=market_id, side=side)
        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {"marketId": market_id, "side": side, "size": size, "price": price}
            resp = await client.post(f"{self._base_url}/orders", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def cancel_order(self, order_id: str, private_key: str) -> bool:
        """Cancel an open order."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(f"{self._base_url}/orders/{order_id}")
            return resp.status_code == 200

    async def health_check(self) -> bool:
        """Check if Limitless Exchange API is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/markets", params={"limit": 1})
                return resp.status_code == 200
        except Exception:
            return False
