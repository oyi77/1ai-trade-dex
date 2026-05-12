"""CoinGecko data feed provider."""
import httpx
import logging
from backend.data.crypto_feeds.base import BaseExchangeFeed, ExchangeFeedManifest
from backend.data.crypto_feeds.registry import get_registry
from backend.config import settings

_registry = get_registry()
logger = logging.getLogger(__name__)


@_registry.plugin
class CoinGeckoFeed(BaseExchangeFeed):
    @classmethod
    def manifest(cls) -> ExchangeFeedManifest:
        return ExchangeFeedManifest(
            name="coingecko",
            display_name="CoinGecko",
            version="1.0.0",
            base_url=settings.COINGECKO_API_URL,
            supported_pairs=["bitcoin", "ethereum", "solana"],
            rate_limit_per_minute=30,
            required_env_vars=[],
            tags=["aggregator", "free-tier"],
        )

    async def get_btc_price(self) -> float:
        async def _fetch():
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.manifest().base_url}/simple/price", params={"ids": "bitcoin", "vs_currencies": "usd"})
                resp.raise_for_status()
                return float(resp.json()["bitcoin"]["usd"])
        return await _fetch()

    async def get_klines(self, symbol: str, interval: str, limit: int) -> list:
        async def _fetch():
            interval_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "1440"}
            granularity = interval_map.get(interval, "60")
            async with httpx.AsyncClient(timeout=10.0) as client:
                from datetime import datetime, timezone
                end = int(datetime.now(timezone.utc).timestamp())
                start = end - (limit * int(granularity) * 60)
                resp = await client.get(
                    f"{self.manifest().base_url}/coins/{symbol}/market_chart/range",
                    params={"vs_currency": "usd", "from": start, "to": end},
                )
                resp.raise_for_status()
                data = resp.json()
                prices = data.get("prices", [])
                return [
                    [int(p[0]) // 1000, p[1], p[1], p[1], p[1], 0]
                    for p in prices[-limit:]
                ]
        return await _fetch()
