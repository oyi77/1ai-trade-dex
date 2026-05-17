<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# data/crypto_feeds

## Purpose
Plugin-based crypto exchange price feed system. Provides abstract base classes and a registry for real-time BTC and crypto price data from multiple exchanges (Binance, Bybit, Coinbase, Kraken, CoinGecko). Used for lead-lag strategies and BTC settlement reconciliation.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Exports `ExchangeFeedManifest`, `BaseExchangeFeed`, `ExchangeFeedRegistry`, `get_registry`, `reset_registry` |
| `base.py` | `BaseExchangeFeed` ABC + `ExchangeFeedManifest` — feeds implement `get_btc_price()` and `get_klines()` |
| `registry.py` | `ExchangeFeedRegistry` — registers feeds, provides failover across exchanges |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `providers/` | Concrete exchange feed implementations (Binance, Bybit, Coinbase, Kraken, CoinGecko) |

## For AI Agents

### Working In This Directory
- All feeds are async — `get_btc_price() -> float` and `get_klines(symbol, interval, limit) -> list`
- Health check defaults to `get_btc_price() > 0` — override for exchange-specific logic
- Use `get_registry()` for the singleton; `reset_registry()` in tests
- Failover: try primary feed, fall back to secondary if health check fails

### Common Patterns
- Get BTC price: `registry = get_registry(); price = await registry.get_btc_price()`
- Get klines: `klines = await feed.get_klines("BTCUSDT", "1m", 100)`

## Dependencies

### Internal
- `backend.config` — `settings` for API keys and rate limits

### External
- `httpx` — async HTTP client for exchange REST APIs
