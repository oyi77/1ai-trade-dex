"""Limitless Exchange REST + EIP-712 client."""

import os
import time
import httpx
from eth_account import Account
from loguru import logger

from backend.core.eip712_signer import sign_typed_data

# Limitless Exchange EIP-712 domain for Base (chain_id=8453).
_LIMITLESS_DOMAIN = {
    "name": "Limitless Exchange",
    "version": "1",
    "chainId": 8453,
    "verifyingContract": os.getenv("LIMITLESS_CONTRACT_ADDRESS", "0x0000000000000000000000000000000000000000"),
}

_LIMITLESS_ORDER_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "Order": [
        {"name": "marketId", "type": "string"},
        {"name": "side", "type": "string"},
        {"name": "size", "type": "uint256"},
        {"name": "price", "type": "uint256"},
        {"name": "maker", "type": "address"},
        {"name": "expiration", "type": "uint256"},
        {"name": "nonce", "type": "uint256"},
    ],
}

_LIMITLESS_CANCEL_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "Cancel": [
        {"name": "orderId", "type": "string"},
        {"name": "maker", "type": "address"},
        {"name": "nonce", "type": "uint256"},
    ],
}


class LimitlessClient:
    """Limitless Exchange API client."""

    def __init__(self, base_url: str = None):
        self._base_url = (
            base_url or os.getenv("LIMITLESS_API_URL", "https://api.limitless.exchange")
        ).rstrip("/")

    async def get_markets(self, limit: int = 100) -> list:
        """Get active markets from Limitless Exchange with pagination (max 25/page)."""
        all_markets = []
        page = 1
        per_page = min(limit, 25)
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            while len(all_markets) < limit:
                resp = await client.get(
                    f"{self._base_url}/markets/active",
                    params={"limit": per_page, "page": page},
                )
                resp.raise_for_status()
                data = resp.json()
                markets = data.get("data", []) if isinstance(data, dict) else data
                if not isinstance(markets, list) or not markets:
                    break
                all_markets.extend(markets)
                if len(markets) < per_page:
                    break
                page += 1
        return all_markets[:limit]

    async def get_orderbook(self, market_id: str) -> dict:
        """Get orderbook for a specific market."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._base_url}/orderbook", params={"marketId": market_id}
            )
            resp.raise_for_status()
            return resp.json()

    async def place_order(
        self, market_id: str, side: str, size: float, price: float, private_key: str
    ) -> dict:
        """Place an order with EIP-712 signature.

        Args:
            market_id: The market identifier.
            side: "BUY" or "SELL".
            size: Order size (in outcome token units).
            price: Limit price (0.01 - 0.99).
            private_key: Hex private key for signing.

        Returns:
            API response dict with order details.
        """
        account = Account.from_key(private_key)

        if (
            "TODO" in _LIMITLESS_DOMAIN["verifyingContract"]
            or _LIMITLESS_DOMAIN["verifyingContract"] == "0x0000000000000000000000000000000000000000"
            or not _LIMITLESS_DOMAIN["verifyingContract"]
        ):
            raise RuntimeError(
                "Limitless contract address not configured. "
                "Set the LIMITLESS_CONTRACT_ADDRESS env var or verifyingContract in _LIMITLESS_DOMAIN."
            )

        # Scale price to integer (basis points: 0.50 -> 5000)
        price_scaled = int(price * 10000)
        # Scale size to integer (USDC 6 decimals)
        size_scaled = int(size * 1e6)

        expiration = int(time.time()) + 24 * 60 * 60  # 24h default TTL
        nonce = int(time.time() * 1000)  # millisecond timestamp as nonce

        message = {
            "marketId": market_id,
            "side": side.upper(),
            "size": size_scaled,
            "price": price_scaled,
            "maker": account.address,
            "expiration": expiration,
            "nonce": nonce,
        }

        signature = sign_typed_data(
            private_key=private_key,
            domain=_LIMITLESS_DOMAIN,
            types=_LIMITLESS_ORDER_TYPES,
            primary_type="Order",
            message=message,
        )

        payload = {
            "marketId": market_id,
            "side": side.upper(),
            "size": str(size_scaled),
            "price": str(price_scaled),
            "maker": account.address,
            "expiration": expiration,
            "nonce": nonce,
            "signature": signature,
        }

        logger.info(
            "Limitless placing order",
            market_id=market_id,
            side=side.upper(),
            maker=account.address,
        )

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self._base_url}/orders",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()

    async def cancel_order(self, order_id: str, private_key: str) -> bool:
        """Cancel an open order with EIP-712 signature.

        Args:
            order_id: The order identifier to cancel.
            private_key: Hex private key for signing.

        Returns:
            True if cancellation succeeded, False otherwise.
        """
        account = Account.from_key(private_key)

        if (
            "TODO" in _LIMITLESS_DOMAIN["verifyingContract"]
            or _LIMITLESS_DOMAIN["verifyingContract"] == "0x0000000000000000000000000000000000000000"
            or not _LIMITLESS_DOMAIN["verifyingContract"]
        ):
            raise RuntimeError(
                "Limitless contract address not configured. "
                "Set the LIMITLESS_CONTRACT_ADDRESS env var or verifyingContract in _LIMITLESS_DOMAIN."
            )

        nonce = int(time.time() * 1000)

        message = {
            "orderId": order_id,
            "maker": account.address,
            "nonce": nonce,
        }

        signature = sign_typed_data(
            private_key=private_key,
            domain=_LIMITLESS_DOMAIN,
            types=_LIMITLESS_CANCEL_TYPES,
            primary_type="Cancel",
            message=message,
        )

        logger.info(
            "Limitless cancelling order",
            order_id=order_id,
            maker=account.address,
        )

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(
                "DELETE",
                f"{self._base_url}/orders/{order_id}",
                json={
                    "orderId": order_id,
                    "maker": account.address,
                    "nonce": nonce,
                    "signature": signature,
                },
                headers={"Content-Type": "application/json"},
            )
            return resp.status_code == 200

    async def get_fills(self, wallet_address: str, limit: int = 100) -> list:
        """Get recent fills/trades for a wallet address.

        Args:
            wallet_address: The wallet address to query fills for.
            limit: Maximum number of fills to return.

        Returns:
            List of fill dicts with id, orderId, side, size, price, fee, pnl, status, etc.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._base_url}/fills",
                    params={"address": wallet_address, "limit": limit},
                )
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, list) else data.get("fills", data.get("data", []))
        except Exception as e:
            logger.warning(f"[limitless] get_fills error: {e}")
            return []

    async def health_check(self) -> bool:
        """Check if Limitless Exchange API is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._base_url}/markets", params={"limit": 1}
                )
                return resp.status_code == 200
        except Exception:
            return False
