"""Limitless Exchange client using official limitless-sdk."""

import os
from loguru import logger


class LimitlessClient:
    """Limitless Exchange API client using official SDK."""

    def __init__(self, base_url: str = None):
        self._api_key = os.getenv("LIMITLESS_API_KEY", "")
        self._private_key = os.getenv("LIMITLESS_PRIVATE_KEY", "")
        self._sdk = None

    def _get_sdk(self):
        """Lazy-init the Limitless SDK client."""
        if self._sdk is None:
            from limitless_sdk import LimitlessClient as SDKClient
            key = self._private_key
            if key and not key.startswith("0x"):
                key = "0x" + key
            self._sdk = SDKClient(
                private_key=key,
                api_key=self._api_key or None,
            )
        return self._sdk

    async def get_markets(self, limit: int = 100) -> list:
        """Get active markets from Limitless Exchange."""
        sdk = self._get_sdk()
        try:
            markets = await sdk.get_all_active_markets()
            return markets[:limit] if markets else []
        except Exception as e:
            logger.warning(f"[limitless] get_markets failed: {e}")
            return []

    async def get_orderbook(self, market_id: str) -> dict:
        """Get orderbook for a specific market."""
        sdk = self._get_sdk()
        try:
            return await sdk.get_orderbook(market_id)
        except Exception as e:
            logger.warning(f"[limitless] get_orderbook failed: {e}")
            return {}

    async def place_order(
        self, market_id: str, side: str, size: float, price: float, private_key: str
    ) -> dict:
        """Place an order using official SDK.

        Args:
            market_id: The market identifier (slug).
            side: "BUY" or "SELL".
            size: Order size (in outcome token units).
            price: Limit price (0.01 - 0.99).
            private_key: Hex private key for signing.

        Returns:
            API response dict with order details.
        """
        sdk = self._get_sdk()
        try:
            await sdk.create_session()
            outcome_index = 0  # YES
            side_int = 1 if side.upper() == "BUY" else 0
            dto = sdk.create_order(
                market_id=market_id,
                market_slug=market_id,
                outcome_index=outcome_index,
                side=side_int,
                amount=size,
                price=price,
            )
            result = await sdk.place_order(dto)
            logger.info(f"[limitless] Order placed: {result}")
            return result
        except Exception as e:
            logger.warning(f"[limitless] place_order failed: {e}")
            return {"error": str(e)}

    async def cancel_order(self, order_id: str, private_key: str) -> bool:
        """Cancel an open order using official SDK."""
        sdk = self._get_sdk()
        try:
            await sdk.cancel_order(order_id)
            return True
        except Exception as e:
            logger.warning(f"[limitless] cancel_order failed: {e}")
            return False

    async def get_fills(self, wallet_address: str, limit: int = 100) -> list:
        """Get recent fills/trades for a wallet address."""
        sdk = self._get_sdk()
        try:
            return await sdk.get_user_history()
        except Exception as e:
            logger.warning(f"[limitless] get_fills failed: {e}")
            return []

    async def health_check(self) -> bool:
        """Check if Limitless Exchange API is available."""
        try:
            sdk = self._get_sdk()
            markets = await sdk.get_all_active_markets()
            return bool(markets)
        except Exception:
            return False
