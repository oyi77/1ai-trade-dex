"""Aster DEX client using CCXT."""

import os

import ccxt.async_support as ccxt_async
import ccxt.pro as ccxtpro

# Global registry for cleanup on shutdown
_all_instances: list = []
from loguru import logger


class AsterClient:
    """Aster perpetuals DEX client (Binance-compatible, ECDSA auth)."""

    def __init__(self, private_key: str = None, wallet_address: str = None):
        self._private_key = (
            private_key
            or os.getenv("ASTER_PRIVATE_KEY")
            or os.getenv("WALLET_PRIVATE_KEY", "")
        )
        self._wallet_address = (
            wallet_address
            or os.getenv("ASTER_WALLET_ADDRESS")
            or os.getenv("WALLET_ADDRESS", "")
        )

        from eth_account import Account as EthAccount

        _account = EthAccount.from_key(self._private_key) if self._private_key else None
        _derived = _account.address if _account else ""

        _address = self._wallet_address or _derived

        _opts = {
            "defaultType": "swap",
            "signerAddress": _address,
        }

        self._exchange = ccxt_async.aster(
            {
                "privateKey": self._private_key,
                "walletAddress": _address,
                "options": _opts,
            }
        )

        self._ws_exchange = ccxtpro.aster(
            {
                "privateKey": self._private_key,
                "walletAddress": _address,
                "options": _opts,
            }
        )
        _all_instances.append(self)

    async def get_markets(self) -> list:
        """Get all available markets."""
        return await self._exchange.load_markets()

    async def get_balance(self) -> dict:
        """Get account balance."""
        return await self._exchange.fetch_balance()

    async def get_positions(self) -> list:
        """Get open positions."""
        return await self._exchange.fetch_positions()

    async def place_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float = None,
        order_type: str = "limit",
    ) -> dict:
        """Place an order."""
        return await self._exchange.create_order(
            symbol, order_type, side, amount, price
        )

    async def cancel_order(self, order_id: str, symbol: str) -> dict:
        """Cancel an order."""
        return await self._exchange.cancel_order(order_id, symbol)

    async def get_ticker(self, symbol: str) -> dict:
        """Get ticker for a symbol."""
        return await self._exchange.fetch_ticker(symbol)

    async def get_tickers(self) -> dict:
        """Get tickers for all symbols."""
        return await self._exchange.fetch_tickers()

    async def health_check(self) -> bool:
        """Check if Aster API is available."""
        try:
            await self._exchange.fetch_time()
            return True
        except Exception:
            return False

    async def watch_balance(self) -> dict:
        """Real-time balance updates via WebSocket."""
        return await self._ws_exchange.watch_balance({"type": "swap"})

    async def watch_positions(self, symbols=None) -> list:
        """Real-time position updates via WebSocket."""
        return await self._ws_exchange.watch_positions(symbols)

    async def watch_orders(self, symbol=None) -> list:
        """Real-time order updates via WebSocket."""
        return await self._ws_exchange.watch_orders(symbol)

    async def close_ws(self):
        """Close WebSocket connection."""
        await self._ws_exchange.close()

    async def close(self):
        """Close REST and WS connections."""
        try:
            await self._ws_exchange.close()
        except Exception:
            logger.debug("aster_client: failed to close WS exchange on shutdown")
        if hasattr(self._exchange, "close"):
            await self._exchange.close()
        if self in _all_instances:
            _all_instances.remove(self)


async def close_all_aster_clients():
    """Close all AsterClient instances. Call on shutdown."""
    for client in list(_all_instances):
        try:
            await client.close()
        except Exception:
            logger.debug("aster_client: failed to close client instance during bulk shutdown")
    _all_instances.clear()
