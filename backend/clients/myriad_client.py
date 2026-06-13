"""Myriad Markets client — prediction market on Polygon."""

import os
from decimal import Decimal
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

_BASE_URL = os.getenv("MYRIAD_API_URL", "https://api.myriad.markets")


class MyriadClient:
    """HTTP client for Myriad Markets API."""

    def __init__(self):
        from backend.config import settings
        self._base_url = getattr(settings, "MYRIAD_API_URL", "https://api.myriad.markets").rstrip("/")
        self._wallet = getattr(settings, "MYRIAD_WALLET_ADDRESS", "") or ""
        self._private_key = getattr(settings, "MYRIAD_PRIVATE_KEY", "") or ""
        self._enabled = getattr(settings, "MYRIAD_ENABLED", True)

    async def get_markets(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch available prediction markets."""
        if not self._enabled:
            return []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self._base_url}/markets",
                    params={"limit": limit, "status": "active"},
                )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    return data
                return data.get("data", data.get("markets", []))
        except (httpx.HTTPError, ConnectionError, TimeoutError):
            logger.exception("[MyriadClient] Failed to fetch markets")
            return []

    async def get_market(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single market by ID."""
        if not self._enabled:
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}/markets/{market_id}")
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, ConnectionError, TimeoutError):
            logger.exception(f"[MyriadClient] Failed to fetch market {market_id}")
            return None

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch positions for the configured wallet."""
        if not self._wallet:
            return []
        if not self._enabled:
            return []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._base_url}/positions",
                    params={"wallet": self._wallet},
                )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    return data
                return data.get("data", data.get("positions", []))
        except (httpx.HTTPError, ConnectionError, TimeoutError):
            logger.exception("[MyriadClient] Failed to fetch positions")
            return []

    async def get_balance(self) -> Decimal:
        """Fetch USDC balance for the configured wallet."""
        if not self._wallet:
            return Decimal("0")
        if not self._enabled:
            return Decimal("0")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._base_url}/wallet/{self._wallet}/balance"
                )
                resp.raise_for_status()
                data = resp.json()
                return Decimal(str(data.get("balance", data.get("usdc", 0))))
        except (httpx.HTTPError, ConnectionError, TimeoutError):
            logger.exception("[MyriadClient] Failed to fetch balance")
            return Decimal("0")

    async def place_order(
        self,
        market_id: str,
        side: str,
        size: Decimal,
        price: Decimal,
    ) -> Dict[str, Any]:
        """Place a limit order on Myriad Markets."""
        if not self._enabled:
            return {"error": True}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self._base_url}/orders",
                    json={
                        "market_id": market_id,
                        "side": side,
                        "size": str(size),
                        "price": str(price),
                        "wallet": self._wallet,
                    },
                )
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, ConnectionError, TimeoutError):
            logger.exception("[MyriadClient] Failed to place order")
            return {"error": True}

    async def health_check(self) -> bool:
        """Check if Myriad API is available."""
        if not self._enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}/health")
                return resp.status_code == 200
        except (httpx.HTTPError, ConnectionError, TimeoutError):
            return False

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by ID."""
        if not self._enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.delete(f"{self._base_url}/orders/{order_id}")
                return resp.status_code == 200
        except (httpx.HTTPError, ConnectionError, TimeoutError) as e:
            logger.exception(f"[MyriadClient] Failed to cancel order {order_id}: {e}")
            return False

    async def get_fills(self, wallet_address: str = None, limit: int = 100) -> list:
        """Get recent trade fills for a wallet.

        Args:
            wallet_address: Wallet address (uses configured wallet if None).
            limit: Maximum number of fills to return.

        Returns:
            List of fill dicts with id, side, size, price, fee, status, etc.
        """
        if not self._enabled:
            return []
        addr = wallet_address or self._wallet
        if not addr:
            return []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._base_url}/fills",
                    params={"wallet": addr, "limit": limit},
                )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    return data
                return data.get("data", data.get("fills", []))
        except (httpx.HTTPError, ConnectionError, TimeoutError) as e:
            logger.warning(f"[myriad] get_fills error: {e}")
            return []