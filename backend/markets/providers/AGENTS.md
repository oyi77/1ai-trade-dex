<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-25 -->

# markets/providers

## Purpose
Concrete market provider implementations for prediction market and decentralized perpetual/orderbook venues. Each provider implements the unified `BaseMarketProvider` interface and is auto-discovered at startup via `market_registry.auto_discover()`.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Package initialization (triggers `market_registry.auto_discover()`) |
| `aster_provider.py` | `AsterProvider` — Aster perpetuals DEX swap & perps provider via CCXT |
| `bookmaker_xyz_provider.py` | `BookmakerXyzProvider` — Bookmaker.xyz betting and prediction market provider via Azuro Protocol |
| `hyperliquid_provider.py` | `HyperliquidProvider` — Hyperliquid exchange perps and predictions provider |
| `kalshi_provider.py` | `KalshiProvider` — Kalshi event contracts: order placement, positions, and balances |
| `lighter_provider.py` | `LighterProvider` — Lighter orderbook swap/perps DEX provider via CCXT |
| `limitless_provider.py` | `LimitlessProvider` — Limitless Base L2 USDC prediction market provider |
| `myriad_provider.py` | `MyriadProvider` — Myriad prediction market REST API provider |
| `ostium_provider.py` | `OstiumProvider` — Ostium perps & predictions DEX provider |
| `paper_provider.py` | `PaperProvider` — Universal in-memory simulated trading engine for all platforms |
| `polymarket_provider.py` | `PolymarketProvider` — Polymarket Polygon CLOB order placement, positions, and balances |
| `predict_fun_provider.py` | `PredictFunProvider` — Predict.fun betting and prediction market provider via Azuro Protocol |
| `sxbet_provider.py` | `SxbetProvider` — SX.bet sports betting & predictions provider |

## For AI Agents

### Working In This Directory
- Each provider subclasses `BaseMarketProvider` and implements `manifest()`, `place_order()`, `cancel_order()`, `get_balance()`, `get_positions()`.
- `PaperProvider` is the universal fallback in shadow/paper/testing modes, simulating order fills and holding an in-memory balance.
- Live providers declare their capabilities and `required_env_vars` inside their manifest.
- Startup validation auto-disables any provider whose required environment variables are not set in the environment.
- All write operations (placing orders) in live providers must check `self._paper_mode` (or `SHADOW_MODE` gates) to prevent live capital losses.

## Dependencies

### Internal
- `backend.markets.base_provider` — `BaseMarketProvider` and `MarketProviderManifest`
- `backend.markets.order_types` — Normalized domain schemas (orders, positions, balances)
- `backend.config` — Centralized settings for API endpoints and RPCs
- `backend.core.eip712_signer` — Shared EVM cryptographic signing routines

### External
- `ccxt` — Swap/perpetual client integrations (Aster, Lighter)
- `hyperliquid-python-sdk` — Hyperliquid exchange client
- `ostium-python-sdk` — Ostium client
- `web3.py` — Polygon, Base, Arbitrum, and Gnosis smart contract integrations
- `httpx` — Async HTTP communications with REST/GraphQL endpoints
