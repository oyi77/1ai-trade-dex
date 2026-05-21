"""Hyperliquid DEX client using official SDK."""

import os

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from loguru import logger


class HyperliquidClient:
    """Hyperliquid perpetuals DEX client."""

    def __init__(self, private_key: str = None, wallet_address: str = None):
        self._private_key = private_key or os.getenv("HYPERLIQUID_PRIVATE_KEY") or os.getenv("WALLET_PRIVATE_KEY", "")
        self._wallet_address = wallet_address or os.getenv("HYPERLIQUID_WALLET_ADDRESS") or os.getenv("WALLET_ADDRESS", "")

        if self._private_key:
            self._account = Account.from_key(self._private_key)
            self._exchange = Exchange(self._account, constants.MAINNET_API_URL)
        else:
            self._account = None
            self._exchange = None

        self._info = Info(constants.MAINNET_API_URL, skip_ws=True)

    async def get_markets(self) -> list:
        """Get all available markets."""
        meta = self._info.meta()
        return meta["universe"]

    async def get_balance(self) -> dict:
        """Get user state (balance, positions)."""
        return self._info.user_state(self._wallet_address)

    async def get_positions(self) -> list:
        """Get open positions."""
        state = self._info.user_state(self._wallet_address)
        return state.get("assetPositions", [])

    async def place_order(
        self,
        asset: str,
        is_buy: bool,
        size: float,
        price: float,
        order_type: str = "limit",
    ) -> dict:
        """Place an order."""
        if not self._exchange:
            raise RuntimeError("HyperliquidClient: no private key configured for trading")

        if order_type == "market":
            order_type_dict = {"limit": {"tif": "Ioc"}}
        else:
            order_type_dict = {"limit": {"tif": "Gtc"}}

        order = self._exchange.order(asset, is_buy, size, price, order_type_dict)
        return order

    async def cancel_order(self, asset: str, order_id: int) -> dict:
        """Cancel an order."""
        if not self._exchange:
            raise RuntimeError("HyperliquidClient: no private key configured for trading")

        return self._exchange.cancel(asset, order_id)

    async def get_open_orders(self) -> list:
        """Get all open orders."""
        return self._info.open_orders(self._wallet_address)

    async def health_check(self) -> bool:
        """Check if Hyperliquid API is available."""
        try:
            self._info.meta()
            return True
        except Exception:
            return False
