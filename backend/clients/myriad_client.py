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
        self._base_url = _BASE_URL.rstrip("/")
        self._wallet = os.getenv("MYRIAD_WALLET_ADDRESS", "")
        self._private_key = os.getenv("MYRIAD_PRIVATE_KEY", "")

    async def get_markets(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch available prediction markets."""
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
        except Exception:
            logger.exception("[MyriadClient] Failed to fetch markets")
            return []

    async def get_market(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single market by ID."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}/markets/{market_id}")
                resp.raise_for_status()
                return resp.json()
        except Exception:
            logger.exception(f"[MyriadClient] Failed to fetch market {market_id}")
            return None

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch positions for the configured wallet."""
        if not self._wallet:
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
        except Exception:
            logger.exception("[MyriadClient] Failed to fetch positions")
            return []

    async def get_balance(self) -> Decimal:
        """Fetch USDC balance for the configured wallet."""
        if not self._wallet:
            return Decimal("0")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._base_url}/wallet/{self._wallet}/balance"
                )
                resp.raise_for_status()
                data = resp.json()
                return Decimal(str(data.get("balance", data.get("usdc", 0))))
        except Exception:
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
        except Exception:
            logger.exception("[MyriadClient] Failed to place order")
            return {"error": True}

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by ID."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.delete(f"{self._base_url}/orders/{order_id}")
                return resp.status_code == 200
        except Exception:
            logger.exception(f"[MyriadClient] Failed to cancel order {order_id}")
            return False
