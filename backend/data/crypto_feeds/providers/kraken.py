import httpx
import logging
from backend.data.crypto_feeds.base import BaseExchangeFeed, ExchangeFeedManifest
from backend.data.crypto_feeds.registry import get_registry
from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker

_registry = get_registry()
logger = logging.getLogger(__name__)

_kraken_breaker = CircuitBreaker(
    "kraken",
    failure_threshold=settings.CB_FAILURE_THRESHOLD,
    recovery_timeout=settings.CB_RECOVERY_TIMEOUT,
)


@_registry.plugin
class KrakenFeed(BaseExchangeFeed):
    @classmethod
    def manifest(cls) -> ExchangeFeedManifest:
        return ExchangeFeedManifest(
            name="kraken",
            display_name="Kraken",
            version="1.0.0",
            base_url=settings.KRAKEN_API_URL,
            supported_pairs=["XBTUSD", "ETHUSD", "SOLUSD"],
            rate_limit_per_minute=60,
            required_env_vars=[],
            tags=["tier2", "us-friendly"],
        )

    async def get_btc_price(self) -> float:
        async def _fetch():
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.manifest().base_url}/Ticker", params={"pair": "XXBTZUSD"}
                )
                resp.raise_for_status()
                data = resp.json()
                return float(data["result"]["XXBTZUSD"]["c"][0])

        return await _kraken_breaker.call(_fetch)

    async def get_klines(self, symbol: str, interval: str, limit: int) -> list:
        import datetime as _dt

        async def _fetch():
            async with httpx.AsyncClient(timeout=10.0) as client:
                end = _dt.datetime.now(_dt.timezone.utc)
                start = end - _dt.timedelta(minutes=limit * 15)
                from_ts = int(start.timestamp())
                pair_map = {
                    "XBTUSD": "XXBTZUSD",
                    "ETHUSD": "XETHZUSD",
                    "SOLUSD": "XSOLZUSD",
                }
                kraken_symbol = pair_map.get(symbol, symbol)
                resp = await client.get(
                    f"{self.manifest().base_url}/OHLC",
                    params={"pair": kraken_symbol, "interval": 15, "since": from_ts},
                )
                resp.raise_for_status()
                data = resp.json()
                rows = data.get("result", {}).get(kraken_symbol, [])
                return [
                    [int(r[0]), r[1], r[2], r[3], r[4], r[6]] for r in rows[-limit:]
                ]

        return await _kraken_breaker.call(_fetch)
