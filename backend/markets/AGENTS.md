<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# markets

## Purpose
Normalized market provider plugin system. Provides a venue-agnostic abstraction layer over prediction market platforms (Polymarket, Kalshi, SX.bet, Limitless, Predict.fun, Bookmaker.xyz). Strategies create `NormalizedOrder` objects; the registry routes them to the correct venue provider.

## Key Files
| File | Description |
|------|-------------|
| `base_provider.py` | `BaseMarketProvider` ABC + `MarketProviderManifest` — all venue providers subclass this |
| `order_types.py` | Normalized types: `NormalizedOrder`, `NormalizedOrderResult`, `NormalizedPosition`, `NormalizedBalance`, `NormalizedFillEvent`, `MarketInfo`, enums (`OrderSide`, `OrderType`, `OrderStatus`, `PositionSide`, `VenueCapability`) |
| `provider_registry.py` | `MarketProviderRegistry` singleton — auto-discovers providers, manages paper/live mode switching |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `providers/` | Concrete venue provider implementations (7 providers) |

## For AI Agents

### Working In This Directory
- **All orders are venue-agnostic** — strategies create `NormalizedOrder`, the provider translates to venue-specific API calls
- **Paper mode** — providers with `supports_paper_mode=True` can simulate fills without hitting real venues
- **`OrderStatus.REJECTED`** is returned for invalid live orders instead of raising raw `NotImplementedError`
- Providers declare `capabilities` (LIMIT_ORDERS, MARKET_ORDERS, SHORT_SELLING, etc.) — check before using a feature
- The registry is a singleton — use `from backend.markets.provider_registry import MarketProviderRegistry`

### Common Patterns
- Place an order: `provider = registry.get("polymarket"); result = await provider.place_order(normalized_order)`
- Check capabilities: `VenueCapability.LIMIT_ORDERS in provider.manifest().capabilities`
- Get balance: `balance = await provider.get_balance()`

## Dependencies

### Internal
- `backend.core.plugin_registry` — `PluginRegistry` base class
- `backend.core.plugin_errors` — error types
- `backend.config` — `settings` for API keys and mode flags

### External
- Venue-specific SDKs per provider (polymarket CLOB, kalshi API, etc.)
