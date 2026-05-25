"""Ostium DEX client using official Python SDK."""

import os

from loguru import logger
from ostium_python_sdk import OstiumSDK
from ostium_python_sdk import NetworkConfig


class OstiumClient:
    """Ostium perpetuals DEX client."""

    def __init__(self, private_key: str = None, rpc_url: str = None):
        self._private_key = private_key or os.getenv("OSTIUM_PRIVATE_KEY") or os.getenv("WALLET_PRIVATE_KEY", "")
        self._rpc_url = rpc_url or os.getenv(
            "OSTIUM_RPC_URL", "https://arb1.arbitrum.io/rpc"
        )

        config = NetworkConfig.mainnet()
        self._sdk = OstiumSDK(
            network=config,
            private_key=self._private_key if self._private_key else None,
            rpc_url=self._rpc_url,
        )

    async def get_markets(self) -> list:
        """Get all available trading pairs."""
        return await self._sdk.subgraph.get_pairs()

    async def get_balance(self) -> dict:
        """Get account balance."""
        return self._sdk.balance.get_balance()

    async def get_positions(self, address: str = None) -> list:
        """Get open positions."""
        addr = address or self._sdk.ostium.get_public_address()
        return await self._sdk.subgraph.get_open_trades(addr)

    async def place_order(
        self,
        pair_id: int,
        direction: bool,
        collateral: float,
        leverage: int,
        order_type: str = "MARKET",
        price: float = None,
        tp: float = None,
        sl: float = None,
    ) -> dict:
        """Place an order (MARKET, LIMIT, or STOP)."""
        params = {
            "collateral": collateral,
            "leverage": leverage,
            "asset_type": pair_id,
            "direction": direction,
            "order_type": order_type,
        }
        if tp:
            params["tp"] = tp
        if sl:
            params["sl"] = sl

        at_price = price or 0  # SDK handles price fetching for market orders
        return self._sdk.ostium.perform_trade(params, at_price)

    async def close_trade(self, pair_id: int, trade_index: int) -> dict:
        """Close a position."""
        return self._sdk.ostium.close_trade(pair_id, trade_index)

    async def cancel_order(self, pair_id: int, index: int) -> dict:
        """Cancel a pending limit order."""
        return self._sdk.ostium.cancel_limit_order(pair_id, index)

    async def get_price(self, base: str, quote: str = "USD") -> dict:
        """Get latest price for a pair."""
        return self._sdk.price.get_price(base, quote)

    async def get_fills(self, wallet_address: str = None, limit: int = 100) -> list:
        """Get recent trade fills/settlements.

        Args:
            wallet_address: Wallet address (uses SDK default if None).
            limit: Maximum number of fills to return.

        Returns:
            List of fill dicts with trade info.
        """
        try:
            addr = wallet_address or self._sdk.ostium.get_public_address()
            trades = await self._sdk.subgraph.get_trades_by_account(addr, limit=limit)
            return trades if isinstance(trades, list) else []
        except Exception as e:
            logger.warning(f"[ostium] get_fills error: {e}")
            return []

    async def health_check(self) -> bool:
        """Check if Ostium API is available."""
        try:
            await self._sdk.subgraph.get_pairs()
            return True
        except Exception:
            return False
