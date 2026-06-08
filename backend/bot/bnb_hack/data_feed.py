import asyncio
from typing import Any, List

import httpx
from loguru import logger


class BinanceFeed:
    BASE = "https://api.binance.com/api/v3"

    def __init__(self, retries: int = 3, timeout: float = 15.0):
        self._retries = retries
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self):
        await self._client.aclose()

    async def _request(self, endpoint: str, params: dict = None) -> Any:
        last_err = None
        for attempt in range(self._retries):
            try:
                resp = await self._client.get(f"{self.BASE}/{endpoint}", params=params)
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_err = e
                if attempt < self._retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        "Binance API error (attempt {}/{}): {}. Retrying in {}s",
                        attempt + 1, self._retries, e, wait,
                    )
                    await asyncio.sleep(wait)
        raise last_err

    async def get_price(self, symbol: str = "BNBUSDT") -> float:
        data = await self._request("ticker/price", {"symbol": symbol})
        return float(data["price"])

    async def get_klines(self, symbol: str, interval: str,
                         limit: int = 100) -> List[List]:
        return await self._request("klines", {
            "symbol": symbol, "interval": interval, "limit": limit,
        })
