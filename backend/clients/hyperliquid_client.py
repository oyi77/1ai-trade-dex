"""Hyperliquid DEX client using official SDK."""

import os

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants


class HyperliquidClient:
    """Hyperliquid perpetuals DEX client."""

    def __init__(self, private_key: str = None, wallet_address: str = None):
        self._private_key = (
            private_key
            or os.getenv("HYPERLIQUID_PRIVATE_KEY")
            or os.getenv("WALLET_PRIVATE_KEY", "")
        )
        self._wallet_address = (
            wallet_address
            or os.getenv("HYPERLIQUID_WALLET_ADDRESS")
            or os.getenv("WALLET_ADDRESS", "")
        )

        if self._private_key:
            self._account = Account.from_key(self._private_key)
            self._exchange = Exchange(self._account, constants.MAINNET_API_URL)
        else:
            self._account = None
            self._exchange = None

        self._info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self._subscriptions = {}

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
            raise RuntimeError(
                "HyperliquidClient: no private key configured for trading"
            )

        if order_type == "market":
            order_type_dict = {"limit": {"tif": "Ioc"}}
        else:
            order_type_dict = {"limit": {"tif": "Gtc"}}

        order = self._exchange.order(asset, is_buy, size, price, order_type_dict)
        return order

    async def cancel_order(self, asset: str, order_id: int) -> dict:
        """Cancel an order."""
        if not self._exchange:
            raise RuntimeError(
                "HyperliquidClient: no private key configured for trading"
            )

        return self._exchange.cancel(asset, order_id)

    async def get_open_orders(self) -> list:
        """Get all open orders."""
        return self._info.open_orders(self._wallet_address)

    async def health_check(self) -> bool:
        """Check if Hyperliquid API is available."""
        try:
            self._info.meta()
            return True
        except (ConnectionError, TimeoutError):
            return False

    def subscribe_user_fills(self, callback):
        """Subscribe to real-time fill notifications.

        callback receives ws_msg with data.fills array containing:
        - coin, px, sz, side, closedPnl, fee, oid
        """
        subscription = {"type": "userFills", "user": self._wallet_address}
        sub_id = self._info.subscribe(subscription, callback)
        self._subscriptions[("userFills", sub_id)] = subscription
        return sub_id

    def subscribe_order_updates(self, callback):
        """Subscribe to real-time order status changes."""
        subscription = {"type": "orderUpdates", "user": self._wallet_address}
        sub_id = self._info.subscribe(subscription, callback)
        self._subscriptions[("orderUpdates", sub_id)] = subscription
        return sub_id

    def subscribe_user_events(self, callback):
        """Subscribe to aggregated user events (fills + more).
        Only 1 per connection."""
        subscription = {"type": "userEvents", "user": self._wallet_address}
        sub_id = self._info.subscribe(subscription, callback)
        self._subscriptions[("userEvents", sub_id)] = subscription
        return sub_id

    def unsubscribe(self, subscription, sub_id):
        """Unsubscribe from a channel."""
        self._info.unsubscribe(subscription, sub_id)
        # Clean up tracked subscription
        keys_to_remove = [
            k for k, v in self._subscriptions.items() if v == subscription
        ]
        for k in keys_to_remove:
            del self._subscriptions[k]

    def disconnect_ws(self):
        """Disconnect WebSocket."""
        self._subscriptions.clear()
        self._info.disconnect_websocket()
