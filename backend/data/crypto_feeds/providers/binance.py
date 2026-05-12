import httpx
import logging
from backend.data.crypto_feeds.base import BaseExchangeFeed, ExchangeFeedManifest
from backend.data.crypto_feeds.registry import get_registry
from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker

_registry = get_registry()
logger = logging.getLogger(__name__)

_binance_breaker = CircuitBreaker("binance", failure_threshold=settings.CB_FAILURE_THRESHOLD, recovery_timeout=settings.CB_RECOVERY_TIMEOUT)


@_registry.plugin
class BinanceFeed(BaseExchangeFeed):
    @classmethod
    def manifest(cls) -> ExchangeFeedManifest:
        return ExchangeFeedManifest(
            name="binance",
            display_name="Binance",
            version="1.0.0",
            base_url=settings.BINANCE_API_URL,
            supported_pairs=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            rate_limit_per_minute=1200,
            required_env_vars=[],
            tags=["tier1", "high-volume"],
        )

    async def get_btc_price(self) -> float:
        async def _fetch():
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.manifest().base_url}/ticker/price", params={"symbol": "BTCUSDT"})
                resp.raise_for_status()
                return float(resp.json()["price"])
        return await _binance_breaker.call(_fetch)

    async def get_klines(self, symbol: str, interval: str, limit: int) -> list:
        async def _fetch():
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.manifest().base_url}/klines", params={"symbol": symbol, "interval": interval, "limit": limit})
                resp.raise_for_status()
                return resp.json()
        return await _binance_breaker.call(_fetch)
