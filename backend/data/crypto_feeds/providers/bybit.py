import httpx
import logging
from backend.data.crypto_feeds.base import BaseExchangeFeed, ExchangeFeedManifest
from backend.data.crypto_feeds.registry import get_registry
from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker

_registry = get_registry()
logger = logging.getLogger(__name__)

_bybit_breaker = CircuitBreaker(
    "bybit",
    failure_threshold=settings.CB_FAILURE_THRESHOLD,
    recovery_timeout=settings.CB_RECOVERY_TIMEOUT,
)


@_registry.plugin
class BybitFeed(BaseExchangeFeed):
    @classmethod
    def manifest(cls) -> ExchangeFeedManifest:
        return ExchangeFeedManifest(
            name="bybit",
            display_name="Bybit",
            version="1.0.0",
            base_url=settings.BYBIT_API_URL,
            supported_pairs=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            rate_limit_per_minute=60,
            required_env_vars=[],
            tags=["tier2", "futures"],
        )

    async def get_btc_price(self) -> float:
        async def _fetch():
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.manifest().base_url}/tickers",
                    params={"category": "spot", "symbol": "BTCUSDT"},
                )
                resp.raise_for_status()
                data = resp.json()
                return float(data["result"]["list"][0]["lastPrice"])

        return await _bybit_breaker.call(_fetch)

    async def get_klines(self, symbol: str, interval: str, limit: int) -> list:
        async def _fetch():
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.manifest().base_url}/kline",
                    params={
                        "category": "spot",
                        "symbol": symbol,
                        "interval": interval.replace("m", ""),
                        "limit": limit,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                rows = data.get("result", {}).get("list", [])
                rows = list(reversed(rows))
                return [[int(r[0]), r[1], r[2], r[3], r[4], r[5]] for r in rows]

        return await _bybit_breaker.call(_fetch)
