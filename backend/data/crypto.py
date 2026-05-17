"""Crypto price data fetcher using CoinGecko + Binance APIs."""
import httpx
import math
import time
from loguru import logger
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from backend.core.circuit_breaker import CircuitBreaker
from backend.core.external_rate_limiter import ExternalRateLimiter
from backend.core.retry import retry
from backend.config import settings

# Per-exchange circuit breakers for the BTC kline fallback chain
# Increased tolerance: settings.CB_FAILURE_THRESHOLD failures before opening, settings.CB_RECOVERY_TIMEOUT recovery window
coinbase_breaker = CircuitBreaker("coinbase", failure_threshold=settings.CB_FAILURE_THRESHOLD, recovery_timeout=settings.CB_RECOVERY_TIMEOUT)
kraken_breaker = CircuitBreaker("kraken", failure_threshold=settings.CB_FAILURE_THRESHOLD, recovery_timeout=settings.CB_RECOVERY_TIMEOUT)
binance_breaker = CircuitBreaker("binance", failure_threshold=settings.CB_FAILURE_THRESHOLD, recovery_timeout=settings.CB_RECOVERY_TIMEOUT)

# Rate limiter for crypto exchange API calls (configurable requests per minute)
_crypto_rate_limiter = ExternalRateLimiter(
    name="crypto",
    max_calls_per_minute=settings.RATE_LIMIT_CRYPTO,
)

# ---------------------------------------------------------------------------
# Binance 1-min kline fetcher + technical indicators for BTC 5-min trading
# ---------------------------------------------------------------------------

BINANCE_API = settings.BINANCE_API_URL
BYBIT_API = settings.BYBIT_API_URL
COINBASE_API = settings.COINBASE_API_URL
KRAKEN_API = settings.KRAKEN_API_URL

# Module-level persistent HTTP client to avoid creating a new one per call
_crypto_client: httpx.AsyncClient | None = None


def _get_crypto_client() -> httpx.AsyncClient:
    """Lazily create and reuse a single httpx.AsyncClient for all crypto feed calls."""
    global _crypto_client
    if _crypto_client is None or _crypto_client.is_closed:
        _crypto_client = httpx.AsyncClient(
            timeout=10.0,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _crypto_client


async def close_crypto_client() -> None:
    """Close the persistent crypto HTTP client (call on shutdown)."""
    global _crypto_client
    if _crypto_client is not None and not _crypto_client.is_closed:
        await _crypto_client.aclose()
    _crypto_client = None


# 30-second cache to avoid hammering Binance during a single scan cycle
_kline_cache: Dict[str, Any] = {"data": None, "ts": 0.0}
_CACHE_TTL = 30.0

# Feed health tracking: source_name -> last_successful_fetch_timestamp
_feed_health: dict[str, float] = {}


@dataclass
class CryptoMicrostructure:
    """Real-time crypto technical indicators computed from 1-min candles."""
    # RSI (14-period Wilder smoothing)
    rsi: float = 50.0
    # Momentum: % change over various lookbacks
    momentum_1m: float = 0.0
    momentum_5m: float = 0.0
    momentum_15m: float = 0.0
    # VWAP deviation (positive = price above VWAP)
    vwap: float = 0.0
    vwap_deviation: float = 0.0
    # SMA crossover: sma5 - sma15 as fraction of price
    sma_crossover: float = 0.0
    # Volatility: stdev of 1-min returns
    volatility: float = 0.0
    # Current price
    price: float = 0.0
    # Source exchange
    source: str = "binance"
    # Asset name (CoinGecko ID)
    asset: str = "bitcoin"


# Backward-compatible alias
BtcMicrostructure = CryptoMicrostructure


# Mapping from CoinGecko ID to Binance trading pair
_COINGECKO_TO_BINANCE_PAIR = {
    "bitcoin": "BTCUSDT",
    "ethereum": "ETHUSDT",
    "solana": "SOLUSDT",
}

# Mapping from CoinGecko ID to Coinbase product ID
_COINGECKO_TO_COINBASE_PRODUCT = {
    "bitcoin": "BTC-USD",
    "ethereum": "ETH-USD",
    "solana": "SOL-USD",
}

# Mapping from CoinGecko ID to Kraken pair name
_COINGECKO_TO_KRAKEN_PAIR = {
    "bitcoin": "XBTUSD",
    "ethereum": "ETHUSD",
    "solana": "SOLUSD",
}

# Per-asset kline caches so multiple assets don't stomp each other
_kline_caches: Dict[str, Dict[str, Any]] = {}


def _get_kline_cache(asset: str) -> Dict[str, Any]:
    """Get or create a kline cache dict for the given asset."""
    if asset not in _kline_caches:
        _kline_caches[asset] = {"data": None, "ts": 0.0}
    return _kline_caches[asset]


async def fetch_crypto_klines(pair: str = "BTCUSDT", limit: int = 60) -> Optional[List[list]]:
    """
    Fetch recent 1-minute candles for a given Binance pair from exchanges.
    Tries Coinbase first, then Kraken, Binance, and Bybit as fallbacks.

    Args:
        pair: Binance trading pair symbol (e.g. "BTCUSDT", "ETHUSDT", "SOLUSDT").
        limit: Number of candles to fetch.

    Returns list of [open_time, open, high, low, close, volume, ...] or None.
    """
    # Derive asset key from pair for caching (e.g. "BTCUSDT" -> "bitcoin")
    pair_to_asset = {v: k for k, v in _COINGECKO_TO_BINANCE_PAIR.items()}
    asset_key = pair_to_asset.get(pair, pair.lower())

    now = time.time()
    cache = _get_kline_cache(asset_key)
    if cache["data"] is not None and (now - cache["ts"]) < _CACHE_TTL:
        return cache["data"]

    client = _get_crypto_client()

    # Resolve Coinbase product and Kraken pair from pair
    coinbase_product = "BTC-USD"  # default
    kraken_pair = "XBTUSD"  # default
    for cg_id, bn_pair in _COINGECKO_TO_BINANCE_PAIR.items():
        if bn_pair == pair:
            coinbase_product = _COINGECKO_TO_COINBASE_PRODUCT.get(cg_id, "BTC-USD")
            kraken_pair = _COINGECKO_TO_KRAKEN_PAIR.get(cg_id, "XBTUSD")
            break

    # Try Coinbase first (US-accessible, reliable)
    if coinbase_breaker.state != "OPEN":
        try:
            import datetime as _dt
            end = _dt.datetime.now(_dt.timezone.utc)
            start = end - _dt.timedelta(minutes=limit)
            resp = await client.get(
                f"{COINBASE_API}/products/{coinbase_product}/candles",
                params={
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "granularity": 60,
                },
            )
            resp.raise_for_status()
            rows = resp.json()
            rows = list(reversed(rows))
            candles = [
                [int(r[0]) * 1000, str(r[3]), str(r[2]), str(r[1]), str(r[4]), str(r[5])]
                for r in rows
            ]
            cache["data"] = candles
            cache["ts"] = now
            cache["_source"] = "coinbase"
            _feed_health["coinbase"] = time.time()
            await coinbase_breaker._on_success()
            return candles
        except Exception as e:
            logger.warning(f"Coinbase kline fetch failed for {pair}, trying Kraken: {repr(e)}")
            await coinbase_breaker._on_failure()
    else:
        logger.warning("Coinbase circuit OPEN, skipping to Kraken")

    # Fallback 1: Kraken (US-accessible, free)
    if kraken_breaker.state != "OPEN":
        try:
            resp = await client.get(
                f"{KRAKEN_API}/OHLC",
                params={"pair": kraken_pair, "interval": 1},
            )
            resp.raise_for_status()
            data = resp.json()
            result = data.get("result", {})
            ohlc_key = [k for k in result if k != "last"]
            if ohlc_key:
                rows = result[ohlc_key[0]]
                rows = rows[-limit:]
                candles = [
                    [int(r[0]) * 1000, str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[6])]
                    for r in rows
                ]
                cache["data"] = candles
                cache["ts"] = now
                cache["_source"] = "kraken"
                _feed_health["kraken"] = time.time()
                await kraken_breaker._on_success()
                return candles
        except Exception as e:
            logger.warning(f"Kraken kline fetch failed for {pair}, trying Binance: {repr(e)}")
            await kraken_breaker._on_failure()
    else:
        logger.warning("Kraken circuit OPEN, skipping to Binance")

    # Fallback 2: Binance (geo-blocked in US)
    if binance_breaker.state != "OPEN":
        try:
            resp = await client.get(
                f"{BINANCE_API}/klines",
                params={"symbol": pair, "interval": "1m", "limit": limit},
            )
            resp.raise_for_status()
            candles = resp.json()
            cache["data"] = candles
            cache["ts"] = now
            cache["_source"] = "binance"
            _feed_health["binance"] = time.time()
            await binance_breaker._on_success()
            return candles
        except Exception as e:
            logger.warning(f"Binance kline fetch failed for {pair}, trying Bybit: {repr(e)}")
            await binance_breaker._on_failure()
    else:
        logger.warning("Binance circuit OPEN, skipping to Bybit")

    # Fallback 3: Bybit (last resort, no dedicated breaker)
    try:
        resp = await client.get(
            f"{BYBIT_API}/kline",
            params={
                "category": "spot",
                "symbol": pair,
                "interval": "1",
                "limit": limit,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("result", {}).get("list", [])
        rows = list(reversed(rows))
        candles = [
            [int(r[0]), r[1], r[2], r[3], r[4], r[5]]
            for r in rows
        ]
        cache["data"] = candles
        cache["ts"] = now
        cache["_source"] = "bybit"
        _feed_health["bybit"] = time.time()
        return candles
    except Exception as e:
        logger.error(f"All kline sources failed for {pair}: {repr(e)}")

    return None


async def fetch_btc_klines(limit: int = 60) -> Optional[List[list]]:
    """Backward-compatible wrapper: fetch BTC 1-min candles."""
    return await fetch_crypto_klines(pair="BTCUSDT", limit=limit)


# Backward-compatible alias
fetch_binance_klines = fetch_btc_klines


def _compute_rsi(closes: List[float], period: int = 14) -> float:
    """Compute RSI using Wilder smoothing."""
    if len(closes) < period + 1:
        return 50.0

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    gains = [d if d > 0 else 0.0 for d in deltas[:period]]
    losses = [-d if d < 0 else 0.0 for d in deltas[:period]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for d in deltas[period:]:
        gain = d if d > 0 else 0.0
        loss = -d if d < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def get_feed_health() -> dict:
    """Return health status per price feed source."""
    now = time.time()
    result = {}
    for source in ["coinbase", "kraken", "binance", "bybit"]:
        last_fetch = _feed_health.get(source)
        if last_fetch is None:
            result[source] = {"last_fetch": None, "age_seconds": None, "status": "unknown"}
        else:
            age = now - last_fetch
            if age <= 60:
                status = "ok"
            elif age <= 300:
                status = "stale"
            else:
                status = "dead"
            result[source] = {"last_fetch": last_fetch, "age_seconds": round(age, 1), "status": status}
    return result


def _build_fallback_microstructure(asset: str = "bitcoin", source: str = "fallback") -> CryptoMicrostructure:
    """Return a CryptoMicrostructure with neutral fallback values."""
    return CryptoMicrostructure(
        rsi=50.0,
        momentum_1m=0.0,
        momentum_5m=0.0,
        momentum_15m=0.0,
        vwap=0.0,
        vwap_deviation=0.0,
        sma_crossover=0.0,
        volatility=0.02,
        price=0.0,
        source=source,
        asset=asset,
    )


@retry(max_attempts=2, retryable_exceptions=(Exception,))
async def compute_crypto_microstructure(asset: str = "bitcoin") -> Optional[CryptoMicrostructure]:
    """
    Fetch 60 one-minute candles and compute all technical indicators for a given asset.

    Args:
        asset: CoinGecko ID ("bitcoin", "ethereum", "solana").

    Returns CryptoMicrostructure or None on failure.
    """
    binance_pair = _COINGECKO_TO_BINANCE_PAIR.get(asset, "BTCUSDT")

    try:
        candles = await fetch_crypto_klines(pair=binance_pair, limit=60)
    except Exception as e:
        logger.error(f"Failed to fetch klines for {asset}: {e}")
        return _build_fallback_microstructure(asset, "fallback")

    if not candles or len(candles) < 20:
        logger.warning(f"Not enough candle data for {asset} microstructure")
        return _build_fallback_microstructure(asset, "fallback")

    try:
        closes = [float(c[4]) for c in candles]
        volumes = [float(c[5]) for c in candles]
        highs = [float(c[2]) for c in candles]
        lows = [float(c[3]) for c in candles]

        current_price = closes[-1]

        # RSI (14-period)
        rsi = _compute_rsi(closes, 14)

        # Momentum: % change over lookback periods
        def pct_change(lookback: int) -> float:
            if len(closes) > lookback and closes[-1 - lookback] > 0:
                return (closes[-1] - closes[-1 - lookback]) / closes[-1 - lookback] * 100
            return 0.0

        momentum_1m = pct_change(1)
        momentum_5m = pct_change(5)
        momentum_15m = pct_change(15)

        # VWAP (30-candle window)
        vwap_window = min(30, len(closes))
        typical_prices = [(highs[-i] + lows[-i] + closes[-i]) / 3 for i in range(1, vwap_window + 1)]
        vwap_volumes = [volumes[-i] for i in range(1, vwap_window + 1)]
        total_vol = sum(vwap_volumes)
        if total_vol > 0:
            vwap = sum(tp * v for tp, v in zip(typical_prices, vwap_volumes)) / total_vol
        else:
            vwap = current_price
        vwap_deviation = (current_price - vwap) / vwap * 100 if vwap > 0 else 0.0

        # SMA crossover: 5-period vs 15-period
        sma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else current_price
        sma15 = sum(closes[-15:]) / 15 if len(closes) >= 15 else current_price
        sma_crossover = (sma5 - sma15) / current_price * 100 if current_price > 0 else 0.0

        # Volatility: stdev of 1-min returns (last 30 candles)
        vol_window = min(30, len(closes) - 1)
        returns = [
            (closes[-i] - closes[-i - 1]) / closes[-i - 1]
            for i in range(1, vol_window + 1)
            if closes[-i - 1] > 0
        ]
        if returns:
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
            volatility = math.sqrt(variance) * 100  # as percentage
        else:
            volatility = 0.0

        cache = _get_kline_cache(asset)
        source = cache.get("_source", "unknown")

        return CryptoMicrostructure(
            rsi=rsi,
            momentum_1m=momentum_1m,
            momentum_5m=momentum_5m,
            momentum_15m=momentum_15m,
            vwap=vwap,
            vwap_deviation=vwap_deviation,
            sma_crossover=sma_crossover,
            volatility=volatility,
            price=current_price,
            source=source,
            asset=asset,
        )
    except Exception as e:
        logger.error(f"Error computing microstructure indicators for {asset}: {e}")
        return _build_fallback_microstructure(asset, "fallback_error")


@retry(max_attempts=2, retryable_exceptions=(Exception,))
async def compute_btc_microstructure() -> Optional[CryptoMicrostructure]:
    """Backward-compatible wrapper: compute BTC microstructure."""
    return await compute_crypto_microstructure("bitcoin")

# CoinGecko API (free tier, no key needed)
COINGECKO_API = settings.COINGECKO_API_URL


@dataclass
class CryptoPrice:
    """Current crypto price data."""
    symbol: str  # BTC, ETH, etc.
    name: str
    current_price: float
    price_24h_ago: float
    change_24h: float  # Percentage
    change_7d: float
    market_cap: float
    volume_24h: float
    last_updated: datetime


# Map common symbols to CoinGecko IDs
SYMBOL_TO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "MATIC": "matic-network",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
}


async def fetch_crypto_price(symbol: str) -> Optional[CryptoPrice]:
    """
    Fetch current price data for a cryptocurrency.

    Args:
        symbol: Crypto symbol (BTC, ETH, etc.)

    Returns:
        CryptoPrice or None if not found
    """
    symbol_upper = symbol.upper()
    coin_id = SYMBOL_TO_ID.get(symbol_upper, symbol.lower())

    url = f"{COINGECKO_API}/coins/{coin_id}"
    params = {
        "localization": "false",
        "tickers": "false",
        "market_data": "true",
        "community_data": "false",
        "developer_data": "false"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            market_data = data.get("market_data", {})
            current_price = market_data.get("current_price", {}).get("usd", 0)
            change_24h = market_data.get("price_change_percentage_24h", 0)
            change_7d = market_data.get("price_change_percentage_7d", 0)

            # Calculate price 24h ago
            price_24h_ago = current_price / (1 + change_24h / 100) if change_24h else current_price

            return CryptoPrice(
                symbol=symbol_upper,
                name=data.get("name", symbol_upper),
                current_price=current_price,
                price_24h_ago=price_24h_ago,
                change_24h=change_24h or 0,
                change_7d=change_7d or 0,
                market_cap=market_data.get("market_cap", {}).get("usd", 0),
                volume_24h=market_data.get("total_volume", {}).get("usd", 0),
                last_updated=datetime.now(timezone.utc)
            )

        except httpx.HTTPStatusError as e:
            logger.warning(f"CoinGecko API error for {symbol}: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Error fetching crypto price for {symbol}: {e}")
            return None


async def fetch_multiple_prices(symbols: List[str]) -> Dict[str, CryptoPrice]:
    """
    Fetch prices for multiple cryptocurrencies efficiently.

    Uses CoinGecko's markets endpoint for batch fetching.
    """
    # Map symbols to CoinGecko IDs
    coin_ids = [SYMBOL_TO_ID.get(s.upper(), s.lower()) for s in symbols]

    url = f"{COINGECKO_API}/coins/markets"
    params = {
        "vs_currency": "usd",
        "ids": ",".join(coin_ids),
        "order": "market_cap_desc",
        "sparkline": "false",
        "price_change_percentage": "24h,7d"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=15.0)
            response.raise_for_status()
            data = response.json()

            results = {}
            for coin in data:
                symbol = coin.get("symbol", "").upper()
                current_price = coin.get("current_price", 0)
                change_24h = coin.get("price_change_percentage_24h", 0) or 0
                change_7d = coin.get("price_change_percentage_7d_in_currency", 0) or 0

                price_24h_ago = current_price / (1 + change_24h / 100) if change_24h else current_price

                results[symbol] = CryptoPrice(
                    symbol=symbol,
                    name=coin.get("name", symbol),
                    current_price=current_price,
                    price_24h_ago=price_24h_ago,
                    change_24h=change_24h,
                    change_7d=change_7d,
                    market_cap=coin.get("market_cap", 0) or 0,
                    volume_24h=coin.get("total_volume", 0) or 0,
                    last_updated=datetime.now(timezone.utc)
                )

            return results

        except Exception as e:
            logger.error(f"Error fetching multiple crypto prices: {e}")
            return {}


def estimate_price_probability(
    current_price: float,
    threshold: float,
    direction: str,
    volatility_24h: float = 0.05
) -> float:
    """
    Estimate probability of price hitting threshold.

    Simple model based on current distance and volatility.
    In production, you'd use options pricing or ML models.

    Args:
        current_price: Current asset price
        threshold: Target price threshold
        direction: "above" or "below"
        volatility_24h: Estimated daily volatility (default 5%)

    Returns:
        Probability estimate 0-1
    """
    if current_price <= 0:
        return 0.5

    # Calculate distance as percentage
    distance = (threshold - current_price) / current_price

    # Simple probability based on normal distribution
    # This is a rough approximation - real models are more complex
    import math

    # Standard deviations away
    std_devs = abs(distance) / volatility_24h

    if direction == "above":
        if current_price >= threshold:
            return 0.95  # Already above
        # Probability of going up by distance
        prob = 0.5 * (1 - math.erf(std_devs / math.sqrt(2)))
    else:  # below
        if current_price <= threshold:
            return 0.95  # Already below
        # Probability of going down by distance
        prob = 0.5 * (1 - math.erf(std_devs / math.sqrt(2)))

    return max(0.05, min(0.95, prob))


# Quick test
if __name__ == "__main__":
    import asyncio

    async def test():
        print("Fetching BTC price...")
        btc = await fetch_crypto_price("BTC")
        if btc:
            print(f"  {btc.name}: ${btc.current_price:,.2f}")
            print(f"  24h change: {btc.change_24h:+.2f}%")
            print(f"  Market cap: ${btc.market_cap:,.0f}")

        print("\nFetching multiple prices...")
        prices = await fetch_multiple_prices(["BTC", "ETH", "SOL"])
        for symbol, price in prices.items():
            print(f"  {symbol}: ${price.current_price:,.2f} ({price.change_24h:+.2f}%)")

    asyncio.run(test())
