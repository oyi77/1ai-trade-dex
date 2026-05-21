"""Limitless Exchange REST + EIP-712 client."""

import os
import time
import httpx
from eth_account import Account
from loguru import logger

from backend.core.eip712_signer import sign_typed_data

# Limitless Exchange EIP-712 domain for Base (chain_id=8453).
# verifyingContract: TODO — replace with the deployed Limitless exchange contract address
# once confirmed from https://docs.limitless.exchange or on-chain.
_LIMITLESS_DOMAIN = {
    "name": "Limitless Exchange",
    "version": "1",
    "chainId": 8453,
    "verifyingContract": "0xTODO_LIMITLESS_CONTRACT_ADDRESS",  # TODO: fill from Limitless docs
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
        """Get available markets from Limitless Exchange."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._base_url}/markets", params={"limit": limit}
            )
            resp.raise_for_status()
            return resp.json()

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

        if "TODO" in _LIMITLESS_DOMAIN["verifyingContract"]:
            raise RuntimeError(
                "Limitless contract address not configured. "
                "Set the verifyingContract in _LIMITLESS_DOMAIN after obtaining the "
                "deployed exchange contract from https://docs.limitless.exchange."
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

        if "TODO" in _LIMITLESS_DOMAIN["verifyingContract"]:
            raise RuntimeError(
                "Limitless contract address not configured. "
                "Set the verifyingContract in _LIMITLESS_DOMAIN after obtaining the "
                "deployed exchange contract from https://docs.limitless.exchange."
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
