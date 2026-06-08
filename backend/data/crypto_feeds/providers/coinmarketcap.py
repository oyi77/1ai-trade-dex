"""CoinMarketCap data feed provider for BNB HACK hackathon.

Integrates CMC Data API as a BaseExchangeFeed plugin, following the same pattern
as Binance/CoinGecko feeds. Uses X-CMC_PRO_API_KEY for authentication.

CMC API v2 endpoints used:
  - /v2/cryptocurrency/quotes/latest — live prices, market cap, volume
  - /v2/cryptocurrency/ohlcv/latest — historical OHLCV
  - /v1/global-metrics/quotes/latest — Fear & Greed, dominance, total market cap
  - /v1/cryptocurrency/trending/latest — trending tokens
  - /v1/cryptocurrency/categories — sector categories
"""

import logging
from typing import Optional, List, Dict, Any

from backend.data.shared_client import get_shared_client
from backend.data.crypto_feeds.base import BaseExchangeFeed, ExchangeFeedManifest
from backend.data.crypto_feeds.registry import get_registry
from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker

_registry = get_registry()
logger = logging.getLogger(__name__)

_cmc_breaker = CircuitBreaker(
    "coinmarketcap",
    failure_threshold=settings.CB_FAILURE_THRESHOLD,
    recovery_timeout=settings.CB_RECOVERY_TIMEOUT,
)

# CMC symbol → CoinGecko ID mapping for compatibility
_CMC_SYMBOL_TO_ID = {
    "BTC": 1,
    "ETH": 1027,
    "SOL": 5426,
    "BNB": 1839,
    "XRP": 52,
    "DOGE": 74,
    "ADA": 2010,
    "AVAX": 5805,
    "DOT": 6636,
    "MATIC": 3890,  # POL
    "LINK": 1975,
    "UNI": 7083,
    "ATOM": 3794,
    "LTC": 2,
    "ARB": 11841,
    "OP": 11840,
    "SUI": 20947,
    "APT": 21794,
    "NEAR": 6535,
    "FIL": 2280,
    "INJ": 7222,
    "TIA": 22861,
    "SEI": 23149,
}


@_registry.plugin
class CoinMarketCapFeed(BaseExchangeFeed):
    """CMC Data API feed — live prices, OHLCV, trends, categories, global metrics."""

    @classmethod
    def manifest(cls) -> ExchangeFeedManifest:
        return ExchangeFeedManifest(
            name="coinmarketcap",
            display_name="CoinMarketCap",
            version="1.0.0",
            base_url=settings.COINMARKETCAP_API_URL,
            supported_pairs=[
                "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
                "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
            ],
            rate_limit_per_minute=300,  # CMC Basic: 300/min, Hobbyist: 500/min
            required_env_vars=["CMC_PRO_API_KEY"],
            tags=["tier1", "high-volume", "market-data", "hackathon-bnb"],
        )

    # ------------------------------------------------------------------
    # Core price feeds (BaseExchangeFeed interface)
    # ------------------------------------------------------------------

    async def get_btc_price(self) -> float:
        """Get live BTC price in USD via CMC quotes endpoint."""
        async def _fetch():
            client = get_shared_client()
            resp = await client.get(
                f"{self.manifest().base_url}/v2/cryptocurrency/quotes/latest",
                params={"id": "1", "convert": "USD"},
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return float(data["data"]["1"]["quote"]["USD"]["price"])

        return await _cmc_breaker.call(_fetch)

    async def get_klines(
        self, symbol: str, interval: str, limit: int
    ) -> Optional[List]:
        """Get historical OHLCV candles for a symbol.

        Maps interval strings to CMC time_period values.
        """
        async def _fetch():
            cmc_id = _CMC_SYMBOL_TO_ID.get(symbol.replace("USDT", ""))
            if cmc_id is None:
                logger.warning(f"CMC: unknown symbol {symbol}, using BTC as fallback")
                cmc_id = 1

            # Map interval to CMC time_period
            interval_map = {
                "1m": "5m",   # CMC minimum is 5m
                "5m": "5m",
                "15m": "15m",
                "30m": "30m",
                "1h": "1h",
                "4h": "4h",
                "1d": "1d",
            }
            time_period = interval_map.get(interval, "1h")
            count = min(limit, 100)  # CMC max is 100 per request

            client = get_shared_client()
            resp = await client.get(
                f"{self.manifest().base_url}/v2/cryptocurrency/ohlcv/latest",
                params={
                    "id": str(cmc_id),
                    "convert": "USD",
                    "time_period": time_period,
                    "count": count,
                },
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            quotes = data.get("data", {}).get(str(cmc_id), {}).get("quotes", [])
            # Convert CMC format → [timestamp_ms, open, high, low, close, volume]
            return [
                [
                    int(q["time_close"].timestamp() * 1000)
                    if hasattr(q["time_close"], "timestamp") else 0,
                    float(q["quote"]["USD"]["open"]),
                    float(q["quote"]["USD"]["high"]),
                    float(q["quote"]["USD"]["low"]),
                    float(q["quote"]["USD"]["close"]),
                    float(q["quote"]["USD"]["volume"]),
                ]
                for q in quotes
            ]

        return await _cmc_breaker.call(_fetch)

    # ------------------------------------------------------------------
    # CMC-specific: Multi-asset quotes
    # ------------------------------------------------------------------

    async def get_quotes(
        self, symbols: Optional[List[str]] = None, ids: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """Get live quotes for multiple cryptocurrencies.

        Args:
            symbols: List of ticker symbols (e.g. ["BTC", "ETH", "SOL"])
            ids: List of CMC coin IDs (e.g. [1, 1027, 5426])

        Returns:
            Dict with "data" key containing coin_id → quote mapping
        """
        async def _fetch():
            client = get_shared_client()
            params: Dict[str, Any] = {"convert": "USD"}
            if ids:
                params["id"] = ",".join(str(i) for i in ids)
            elif symbols:
                params["symbol"] = ",".join(symbols)
            else:
                params["id"] = "1,1027,5426,1839"  # default: BTC, ETH, SOL, BNB

            resp = await client.get(
                f"{self.manifest().base_url}/v2/cryptocurrency/quotes/latest",
                params=params,
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            return resp.json()

        return await _cmc_breaker.call(_fetch)

    async def get_global_metrics(self) -> Dict[str, Any]:
        """Get global market metrics: total market cap, dominance, Fear & Greed."""
        async def _fetch():
            client = get_shared_client()
            resp = await client.get(
                f"{self.manifest().base_url}/v1/global-metrics/quotes/latest",
                params={"convert": "USD"},
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            return resp.json()

        return await _cmc_breaker.call(_fetch)

    async def get_trending(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get trending cryptocurrencies."""
        async def _fetch():
            client = get_shared_client()
            resp = await client.get(
                f"{self.manifest().base_url}/v1/cryptocurrency/trending/latest",
                params={"limit": limit},
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", [])

        return await _cmc_breaker.call(_fetch)

    async def get_categories(self) -> List[Dict[str, Any]]:
        """Get all cryptocurrency categories/sectors."""
        async def _fetch():
            client = get_shared_client()
            resp = await client.get(
                f"{self.manifest().base_url}/v1/cryptocurrency/categories",
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", [])

        return await _cmc_breaker.call(_fetch)

    async def get_fear_and_greed(self) -> Optional[Dict[str, Any]]:
        """Extract Fear & Greed index from global metrics."""
        try:
            metrics = await self.get_global_metrics()
            fg = metrics.get("data", {}).get("quote", {}).get("USD", {})
            return {
                "value": fg.get("dominance", 50),
                "classification": self._classify_fear_greed(fg.get("dominance", 50)),
                "total_market_cap": fg.get("total_market_cap", 0),
                "btc_dominance": fg.get("btc_dominance", 0),
                "eth_dominance": fg.get("eth_dominance", 0),
                "active_cryptocurrencies": fg.get("active_cryptocurrencies", 0),
                "total_volume_24h": fg.get("total_volume_24h", 0),
            }
        except Exception as e:
            logger.warning(f"CMC: Failed to get Fear & Greed: {e}")
            return None

    # ------------------------------------------------------------------
    # MCP Bridge — agent-ready structured outputs
    # ------------------------------------------------------------------

    async def mcp_get_market_snapshot(self) -> Dict[str, Any]:
        """CMC MCP-style market snapshot — compact, LLM-friendly format.

        Returns structured data mimicking the CMC Data MCP tool output:
        quotes + technicals + sentiment in one call.
        """
        try:
            quotes = await self.get_quotes(ids=[1, 1027, 5426, 1839])
            global_data = await self.get_global_metrics()
            trending = await self.get_trending(limit=5)

            # Build compact snapshot
            top_assets = {}
            for cid, data in quotes.get("data", {}).items():
                usd = data.get("quote", {}).get("USD", {})
                top_assets[data.get("symbol", cid)] = {
                    "price": usd.get("price"),
                    "change_1h": usd.get("percent_change_1h"),
                    "change_24h": usd.get("percent_change_24h"),
                    "change_7d": usd.get("percent_change_7d"),
                    "market_cap": usd.get("market_cap"),
                    "volume_24h": usd.get("volume_24h"),
                }

            return {
                "timestamp": quotes.get("status", {}).get("timestamp"),
                "top_assets": top_assets,
                "global": {
                    "total_market_cap": global_data.get("data", {}).get("quote", {}).get("USD", {}).get("total_market_cap"),
                    "btc_dominance": global_data.get("data", {}).get("btc_dominance"),
                    "eth_dominance": global_data.get("data", {}).get("eth_dominance"),
                },
                "trending": [
                    {"name": t.get("name"), "symbol": t.get("symbol"), "market_cap_rank": t.get("cmc_rank")}
                    for t in trending[:10]
                ],
            }
        except Exception as e:
            logger.error(f"CMC MCP snapshot failed: {e}")
            return {"error": str(e)}

    async def mcp_get_technicals(self, symbol: str = "BTC") -> Dict[str, Any]:
        """CMC MCP-style technical signals — pre-computed indicators.

        Fetches OHLCV and computes basic signals client-side.
        """
        try:
            pair = f"{symbol}USDT"
            klines = await self.get_klines(pair, "1h", 50)
            if not klines:
                return {"error": f"No data for {symbol}"}

            closes = [k[4] for k in klines]
            if len(closes) < 2:
                return {"error": "Insufficient data"}

            # Simple technical signals
            current = closes[-1]
            prev = closes[-2]
            sma_20 = sum(closes[-20:]) / min(len(closes), 20)
            sma_50 = sum(closes[-50:]) / min(len(closes), 50)

            high_24h = max(k[2] for k in klines[-24:]) if len(klines) >= 24 else max(k[2] for k in klines)
            low_24h = min(k[3] for k in klines[-24:]) if len(klines) >= 24 else min(k[3] for k in klines)
            volume_24h = sum(k[5] for k in klines[-24:]) if len(klines) >= 24 else sum(k[5] for k in klines)

            # RSI (14-period simple implementation)
            gains = sum(max(0, closes[i] - closes[i-1]) for i in range(-14, 0) if abs(i) <= len(closes))
            losses = sum(max(0, closes[i-1] - closes[i]) for i in range(-14, 0) if abs(i) <= len(closes))
            avg_gain = gains / 14
            avg_loss = losses / 14
            rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100

            return {
                "symbol": symbol,
                "price": current,
                "change": ((current - prev) / prev * 100) if prev else 0,
                "sma_20": round(sma_20, 2),
                "sma_50": round(sma_50, 2),
                "sma_signal": "bullish" if sma_20 > sma_50 else "bearish",
                "rsi_14": round(rsi, 1),
                "rsi_signal": "oversold" if rsi < 30 else ("overbought" if rsi > 70 else "neutral"),
                "high_24h": high_24h,
                "low_24h": low_24h,
                "volume_24h": volume_24h,
                "support": round(low_24h, 2),
                "resistance": round(high_24h, 2),
            }
        except Exception as e:
            logger.error(f"CMC technicals failed for {symbol}: {e}")
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> Dict[str, str]:
        """Build CMC API authentication headers."""
        import os
        api_key = os.getenv("CMC_PRO_API_KEY", "")
        return {
            "X-CMC_PRO_API_KEY": api_key,
            "Accept": "application/json",
        }

    @staticmethod
    def _classify_fear_greed(value: int) -> str:
        if value <= 25:
            return "extreme_fear"
        elif value <= 45:
            return "fear"
        elif value <= 55:
            return "neutral"
        elif value <= 75:
            return "greed"
        else:
            return "extreme_greed"

    async def health_check(self) -> bool:
        try:
            price = await self.get_btc_price()
            return price > 0
        except Exception:
            return False
