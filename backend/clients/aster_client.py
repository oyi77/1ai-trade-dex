"""Aster DEX client using CCXT."""

import os

import ccxt
from loguru import logger


class AsterClient:
    """Aster perpetuals DEX client (Binance-compatible, ECDSA auth)."""

    def __init__(self, private_key: str = None):
        self._private_key = private_key or os.getenv("ASTER_PRIVATE_KEY") or os.getenv("WALLET_PRIVATE_KEY", "")

        self._exchange = ccxt.aster(
            {
                "privateKey": self._private_key,
                "options": {
                    "defaultType": "swap",
                },
            }
        )

    async def get_markets(self) -> list:
        """Get all available markets."""
        return self._exchange.load_markets()

    async def get_balance(self) -> dict:
        """Get account balance."""
        return self._exchange.fetch_balance()

    async def get_positions(self) -> list:
        """Get open positions."""
        return self._exchange.fetch_positions()

    async def place_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float = None,
        order_type: str = "limit",
    ) -> dict:
        """Place an order."""
        return self._exchange.create_order(symbol, order_type, side, amount, price)

    async def cancel_order(self, order_id: str, symbol: str) -> dict:
        """Cancel an order."""
        return self._exchange.cancel_order(order_id, symbol)

    async def get_ticker(self, symbol: str) -> dict:
        """Get ticker for a symbol."""
        return self._exchange.fetch_ticker(symbol)

    async def health_check(self) -> bool:
        """Check if Aster API is available."""
        try:
            self._exchange.fetch_time()
            return True
        except Exception:
            return False
