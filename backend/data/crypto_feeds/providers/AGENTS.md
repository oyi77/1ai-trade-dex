<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# data/crypto_feeds/providers

## Purpose
Concrete crypto exchange feed implementations. Each provider wraps a specific exchange API behind the `BaseExchangeFeed` interface for BTC price and kline data.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Imports all providers to trigger registration: `BinanceFeed`, `BybitFeed`, `CoinbaseFeed`, `KrakenFeed`, `CoinGeckoFeed` |
| `binance.py` | `BinanceFeed` — Binance REST API for BTC price and klines |
| `bybit.py` | `BybitFeed` — Bybit REST API |
| `coinbase.py` | `CoinbaseFeed` — Coinbase REST API |
| `coingecko.py` | `CoinGeckoFeed` — CoinGecko REST API (aggregated prices) |
| `kraken.py` | `KrakenFeed` — Kraken REST API |

## For AI Agents

### Working In This Directory
- Each provider subclasses `BaseExchangeFeed` and implements `manifest()`, `get_btc_price()`, `get_klines()`
- Providers are imported explicitly in `__init__.py` (not auto-discovered) — add new providers there
- All API base URLs come from `settings` — never hardcode
- Respect rate limits declared in `manifest.rate_limit_per_minute`

## Dependencies

### Internal
- `backend.data.crypto_feeds.base` — `BaseExchangeFeed`, `ExchangeFeedManifest`
- `backend.config` — `settings` for API keys

### External
- `httpx` — async HTTP client
