"""Kalshi API client with RSA-PSS signature authentication."""

import base64
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker
from backend.core.external_rate_limiter import ExternalRateLimiter

BASE_URL = settings.KALSHI_API_URL

# Circuit breaker for Kalshi API
kalshi_breaker = CircuitBreaker(
    "kalshi_api", failure_threshold=5, recovery_timeout=60.0
)

# Rate limiter for Kalshi API (configurable requests per minute)
_kalshi_rate_limiter = ExternalRateLimiter(
    name="kalshi",
    max_calls_per_minute=settings.RATE_LIMIT_KALSHI,
    circuit_breaker=kalshi_breaker,
)


class KalshiClient:
    """Async Kalshi API client using RSA-PSS signature auth."""

    def __init__(self):
        self._private_key = None

    def _load_private_key(self):
        """Load RSA private key from file (lazy, cached)."""
        if self._private_key is not None:
            return self._private_key

        key_path = settings.KALSHI_PRIVATE_KEY_PATH
        if not key_path:
            raise ValueError("KALSHI_PRIVATE_KEY_PATH not configured")

        pem_data = Path(key_path).expanduser().read_bytes()
        self._private_key = serialization.load_pem_private_key(pem_data, password=None)
        return self._private_key

    def _sign_request(self, method: str, path: str) -> Dict[str, str]:
        """
        Generate auth headers for a Kalshi API request.

        Signature = RSA-PSS-sign(timestamp_ms + METHOD + path)
        where path = /trade-api/v2/... (no query params).
        """
        timestamp_ms = str(int(time.time() * 1000))
        message = f"{timestamp_ms}{method.upper()}{path}"

        private_key = self._load_private_key()
        signature = private_key.sign(
            message.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

        return {
            "KALSHI-ACCESS-KEY": settings.KALSHI_API_KEY_ID,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "Content-Type": "application/json",
        }

    async def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> dict:
        """Authenticated GET request to Kalshi API through rate limiter."""
        return await _kalshi_rate_limiter.call(self._execute_get, path, params)

    async def _execute_get(
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> dict:
        """Execute the actual GET request (called through rate limiter)."""
        full_path = f"/trade-api/v2{path}"
        url = f"{BASE_URL}{path}"
        headers = self._sign_request("GET", full_path)

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()

    async def get_markets(self, params: Optional[Dict[str, Any]] = None) -> dict:
        """Fetch markets with optional filters."""
        return await self.get("/markets", params=params)

    async def get_market(self, ticker: str) -> dict:
        """Fetch a single market by ticker."""
        return await self.get(f"/markets/{ticker}")

    async def get_orderbook(self, ticker: str) -> dict:
        """Fetch the order book for a market ticker."""
        return await self.get(f"/markets/{ticker}/orderbook")

    async def get_balance(self) -> dict:
        """Get portfolio balance (useful for auth test)."""
        return await self.get("/portfolio/balance")

    async def get_positions(self) -> list[dict]:
        """Fetch open portfolio positions."""
        response = await self.get("/portfolio/positions")
        positions = response.get("positions", response.get("market_positions", []))
        return positions if isinstance(positions, list) else []

    async def _request(
        self, method: str, path: str, json: Optional[Dict[str, Any]] = None
    ) -> dict:
        """Authenticated request to Kalshi API through rate limiter + circuit breaker."""
        full_path = f"/trade-api/v2{path}"
        url = f"{BASE_URL}{path}"
        headers = self._sign_request(method.upper(), full_path)

        async def _fetch():
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.request(method, url, headers=headers, json=json)
                response.raise_for_status()
                return response.json()

        return await _kalshi_rate_limiter.call(_fetch)

    async def batch_create_orders(self, orders: list[dict]) -> dict:
        return await self._request(
            "POST", "/portfolio/orders/batched", json={"orders": orders}
        )

    async def batch_cancel_orders(self, order_ids: list[str]) -> dict:
        return await self._request(
            "DELETE", "/portfolio/orders/batched", json={"ids": order_ids}
        )

    async def place_order(
        self, market_id: str, side: str, size: int, price: float
    ) -> dict:
        """Place a single limit order using Kalshi's standard v2 order schema."""
        side_value = side.lower()
        action = "sell" if side_value == "sell" else "buy"
        outcome_side = "no" if side_value == "no" else "yes"
        payload: Dict[str, Any] = {
            "ticker": market_id,
            "action": action,
            "side": outcome_side,
            "count_fp": f"{size:.2f}",
            "type": "limit",
            "client_order_id": f"polyedge-{int(time.time() * 1000)}",
        }
        if outcome_side == "yes":
            payload["yes_price_dollars"] = price
        else:
            payload["no_price_dollars"] = price
        return await self._request("POST", "/portfolio/orders", json=payload)

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a single order by delegating to the batched cancel endpoint."""
        response = await self.batch_cancel_orders([order_id])
        return bool(response)

    async def amend_order(
        self, order_id: str, new_price: float = None, new_size: int = None
    ) -> dict:
        payload: Dict[str, Any] = {"order_id": order_id}
        if new_price is not None:
            payload["new_price"] = new_price
        if new_size is not None:
            payload["new_size"] = new_size
        return await self._request("POST", "/portfolio/amend_order", json=payload)


def kalshi_credentials_present() -> bool:
    """Check if Kalshi API credentials are configured."""
    return bool(settings.KALSHI_API_KEY_ID and settings.KALSHI_PRIVATE_KEY_PATH)
