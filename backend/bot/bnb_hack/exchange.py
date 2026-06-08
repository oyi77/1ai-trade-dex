from typing import Any, Dict

import httpx

from backend.clients.twak_client import TWAKClient
from backend.config import settings


class LiveTWAKExchange:
    def __init__(self, client: TWAKClient):
        self._client = client

    async def balance(self) -> Dict[str, Any]:
        return await self._client.wallet_balance(chain="bsc")

    async def swap(self, amount: str, from_token: str, to_token: str,
                   quote_only: bool = False) -> Dict[str, Any]:
        return await self._client.swap(
            amount,
            from_token,
            to_token,
            chain="bsc",
            quote_only=quote_only,
            slippage="2",
        )


class PaperEngine:
    def __init__(self):
        self._balance_usdc = 34.0
        self._balance_bnb = 0.0

    async def balance(self) -> Dict[str, Any]:
        return {
            "address": settings.bnb_hack.wallet_address,
            "totalUsd": self._balance_usdc + self._balance_bnb * 600,
            "tokens": [
                {"symbol": "USDC", "balance": str(self._balance_usdc)},
            ],
        }

    async def swap(self, amount: str, from_token: str, to_token: str,
                   quote_only: bool = False) -> Dict[str, Any]:
        amt = float(amount)
        if to_token == "BNB":
            price = await self._get_price()
            received = amt / price * 0.997
            if not quote_only:
                self._balance_usdc -= amt
                self._balance_bnb += received
        else:
            received = amt * 600 * 0.997
            if not quote_only:
                self._balance_bnb -= amt
                self._balance_usdc += received
        return {
            "success": True,
            "toAmount": received,
            "input": f"{amt} {from_token}",
            "output": f"{round(received, 6)} {to_token}",
            "priceImpact": "0",
        }

    async def _get_price(self) -> float:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://api.binance.com/api/v3/ticker/price",
                            params={"symbol": "BNBUSDT"})
            return float(r.json()["price"])
