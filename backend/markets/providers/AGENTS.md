<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# markets/providers

## Purpose
Concrete market provider implementations for prediction market trading venues. Each provider wraps a specific venue API behind the `BaseMarketProvider` interface.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Empty (providers are auto-discovered by registry) |
| `polymarket_provider.py` | `PolymarketProvider` — Polymarket CLOB API: order placement, positions, USDC balance (10K LOC) |
| `kalshi_provider.py` | `KalshiProvider` — Kalshi event contract API: market orders, positions, balance (10K) |
| `paper_provider.py` | `PaperProvider` — paper trading simulation: simulated fills, in-memory positions, no real money |
| `bookmaker_xyz_provider.py` | `BookmakerXyzProvider` — Bookmaker.xyz prediction market API |
| `limitless_provider.py` | `LimitlessProvider` — Limitless prediction market API |
| `predict_fun_provider.py` | `PredictFunProvider` — Predict.fun prediction market API |
| `sxbet_provider.py` | `SxbetProvider` — SX.bet prediction market API |

## For AI Agents

### Working In This Directory
- Each provider subclasses `BaseMarketProvider` and implements `manifest()`, `place_order()`, `cancel_order()`, `get_balance()`, `get_positions()`
- `PaperProvider` is the default in paper/shadow mode — it simulates fills without external calls
- `PolymarketProvider` handles real USDC — all write operations must be guarded by `SHADOW_MODE` checks
- Providers declare `capabilities` and `required_env_vars` in their manifest
- Check `supports_paper_mode` before routing to a provider in paper mode

## Dependencies

### Internal
- `backend.markets.base_provider` — `BaseMarketProvider`, `MarketProviderManifest`
- `backend.markets.order_types` — normalized types
- `backend.config` — `settings` for API keys

### External
- `httpx` — async HTTP client for venue REST APIs
- `websockets` — for fill streaming where supported
