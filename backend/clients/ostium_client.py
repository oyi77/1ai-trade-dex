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

    async def get_balance(self, address: str = None) -> dict:
        """Get account balance."""
        addr = address or self._sdk.ostium.get_public_address()
        try:
            ether, usdc = self._sdk.balance.get_balance(addr)
            usdc_val = float(usdc) if usdc is not None else 0.0
            ether_val = float(ether) if ether is not None else 0.0
        except Exception as e:
            logger.warning(f"[ostium] get_balance error: {e}")
            usdc_val, ether_val = 0.0, 0.0
        return {
            "usdc": usdc_val,
            "total": usdc_val,
            "balance": usdc_val,
            "value": usdc_val,
            "ether": ether_val,
        }

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
            orders = await self._sdk.subgraph.get_recent_history(addr, last_n_orders=limit)
            fills = []
            for order in (orders or []):
                if not order:
                    continue
                side = "buy" if order.get("isBuy") else "sell"
                pair_data = order.get("pair", {}) or {}
                market_name = ""
                if pair_data:
                    market_name = f"{pair_data.get('from', '')}-{pair_data.get('to', '')}"

                fill = {
                    "id": order.get("id"),
                    "tradeId": order.get("id"),
                    "direction": side,
                    "side": side,
                    "collateral": order.get("collateral"),
                    "size": order.get("tradeNotional"),
                    "entryPrice": order.get("price"),
                    "price": order.get("price"),
                    "fee": float(order.get("fundingFee", 0) or 0) + float(order.get("rolloverFee", 0) or 0),
                    "pnl": order.get("amountSentToTrader"),
                    "pair": market_name,
                    "market": market_name,
                    "status": "closed" if order.get("orderAction") == "CLOSE" or order.get("isCancelled") else "open",
                    "txnHash": order.get("executedTx"),
                    "tx_hash": order.get("executedTx"),
                }
                fills.append(fill)
            return fills
        except Exception as e:
            logger.warning(f"[ostium] get_fills error: {e}")
            return []

    async def health_check(self) -> bool:
        """Check if Ostium API is available."""
        try:
            await self._sdk.subgraph.get_pairs()
            return True
        except (ConnectionError, TimeoutError):
            return False
