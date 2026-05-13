<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/data

## Purpose
Market data providers, exchange clients, WebSocket feeds, and data aggregation. Provides the data layer that strategies and core modules consume — market discovery, order book data, price feeds, on-chain data, and weather data.

## Key Files

| File | Description |
|------|-------------|
| `provider.py` | `DataProvider` ABC — interface all platform providers must implement |
| `market_universe.py` | `MarketUniverseScanner` — discovers 5000+ markets across platforms with configurable TTL cache (default 300s) |
| `gamma.py` | Polymarket Gamma API client — market metadata, search, categories |
| `polymarket_clob.py` | Polymarket CLOB API client — order placement, position tracking, USDC balance |
| `kalshi_client.py` | Kalshi API client — market data and order execution |
| `kalshi_markets.py` | Kalshi market discovery and filtering |
| `btc_markets.py` | BTC-specific market helpers — active BTC binary market discovery |
| `markets.py` | General market utilities |
| `market_types.py` | Shared market data type definitions |
| `aggregator.py` | Multi-source data aggregation |
| `feed_aggregator.py` | Real-time feed aggregation |
| `crypto.py` | Crypto price feed (CEX prices for lead-lag strategies) |
| `orderbook_analyzer_hft.py` | HFT order book analysis |
| `orderbook_cache.py` | Order book caching layer |
| `orderbook_hft_ws.py` | HFT WebSocket order book feed |
| `orderbook_ws.py` | Standard WebSocket order book feed |
| `polymarket_websocket.py` | Polymarket WebSocket client — publishes `book`, `last_trade_price`, and `price_change` events to `EventBus` for strategy execution |
| `ws_aggregator.py` | WebSocket feed aggregator |
| `ws_client.py` | Generic WebSocket client base |
| `whale_monitor_ws.py` | On-chain whale wallet monitoring via WebSocket |
| `goldsky_client.py` | Goldsky GraphQL client for on-chain data |
| `polygon_listener.py` | Polygon.io market data listener |
| `weather.py` | Weather data fetching (Open-Meteo, NOAA NBM) |
| `weather_markets.py` | Weather market discovery on Polymarket |
| `polymeteo.py` | Polymarket weather market utilities |
| `polynimbus.py` | Weather probability calculation utilities |
| `auto_researcher.py` | Automated market research data collection |
| `clob_event_indexer.py` | CLOB event indexing for historical analysis |
| `parquet_archiver.py` | Market data archival to Parquet format |
| `simmer_client.py` | Simmer data source client |
| `shared_service.py` | Shared data service singleton |
| `validators.py` | Data validation for incoming market data |
| `providers/` | Platform-specific `DataProvider` implementations (see `providers/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- **All external API base URLs are configurable** — use `settings.GAMMA_API_URL`, `settings.DATA_API_URL`, `settings.CLOB_API_URL`, etc. Never hardcode URLs.
- **`MarketUniverseScanner` uses a TTL cache** — the cache TTL is `settings.MARKET_UNIVERSE_CACHE_TTL_SECONDS` (default 300s). Do not bypass the cache for high-frequency calls.
- **`polymarket_clob.py` handles real money** — all CLOB write operations (order placement, cancellation) must be guarded by `SHADOW_MODE` checks before calling.
- WebSocket clients implement reconnection with exponential backoff — do not add bare `asyncio.sleep` retry loops.
- `DataProvider` ABC requires: `platform_name`, `health_check()`, `get_markets()`, `get_positions()`, `get_balance()`.

### Testing Requirements
- Mock all external HTTP calls with `httpx.MockTransport` or `unittest.mock.patch`
- Test `health_check()` timeout and error handling for all providers
- Test market data transformation to common `MarketEntry` format
- Never make real API calls in tests

### Common Patterns
- Discover markets: `scanner = MarketUniverseScanner(); markets = await scanner.scan()`
- Subscribe near-expiry CLOB market events: `await fetch_short_duration_token_ids(...)` from `backend.core.market_scanner`; pass returned token IDs as Polymarket WS `asset_ids`
- Get CLOB balance: `clob = PolymarketCLOB(settings); balance = await clob.get_usdc_balance()`
- Fetch Gamma markets: `gamma = GammaClient(settings); markets = await gamma.get_markets(category="crypto")`

## Dependencies

### Internal
- `backend.config` — `settings` for all API URLs and credentials
- `backend.models.database` — for data persistence (clob events, market snapshots)

### External
- `httpx` — async HTTP client
- `websockets` — WebSocket connections
- `pandas` / `pyarrow` — data processing and Parquet archival
