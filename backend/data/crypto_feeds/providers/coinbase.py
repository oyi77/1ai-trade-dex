import logging
from backend.data.shared_client import get_shared_client
from backend.data.crypto_feeds.base import BaseExchangeFeed, ExchangeFeedManifest
from backend.data.crypto_feeds.registry import get_registry
from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker

_registry = get_registry()
logger = logging.getLogger(__name__)

_coinbase_breaker = CircuitBreaker(
    "coinbase",
    failure_threshold=settings.CB_FAILURE_THRESHOLD,
    recovery_timeout=settings.CB_RECOVERY_TIMEOUT,
)


@_registry.plugin
class CoinbaseFeed(BaseExchangeFeed):
    @classmethod
    def manifest(cls) -> ExchangeFeedManifest:
        return ExchangeFeedManifest(
            name="coinbase",
            display_name="Coinbase",
            version="1.0.0",
            base_url=settings.COINBASE_API_URL,
            supported_pairs=["BTC-USD", "ETH-USD", "SOL-USD"],
            rate_limit_per_minute=100,
            required_env_vars=[],
            tags=["tier1", "us-accessible"],
        )

    async def get_btc_price(self) -> float:
        async def _fetch():
            # timeout=10.0 (handled by shared_client)
            client = get_shared_client()
            resp = await client.get(
                f"{self.manifest().base_url}/products/BTC-USD/ticker"
            )
            resp.raise_for_status()
            return float(resp.json()["price"])

        return await _coinbase_breaker.call(_fetch)

    async def get_klines(self, symbol: str, interval: str, limit: int) -> list:
        import datetime as _dt

        async def _fetch():
            # timeout=10.0 (handled by shared_client)
            client = get_shared_client()
            end = _dt.datetime.now(_dt.timezone.utc)
            start = end - _dt.timedelta(minutes=limit)
            resp = await client.get(
                f"{self.manifest().base_url}/products/{symbol}/candles",
                params={
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "granularity": 60 if interval == "1m" else 300,
                },
            )
            resp.raise_for_status()
            rows = resp.json()
            rows = list(reversed(rows))
            return [
                [
                    int(r[0]) * 1000,
                    str(r[3]),
                    str(r[2]),
                    str(r[1]),
                    str(r[4]),
                    str(r[5]),
                ]
                for r in rows
            ]

        return await _coinbase_breaker.call(_fetch)
