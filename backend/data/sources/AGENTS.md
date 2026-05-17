<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# data/sources

## Purpose
Data source plugin implementations. Each source provides market data from a specific platform (Polymarket, Kalshi) or a mock for testing. Auto-discovered and registered by the source registry on import.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Triggers auto-discovery via `source_registry.auto_discover("backend.data.sources")` |
| `polymarket_source.py` | Polymarket data source — market discovery, price feeds, order book data |
| `kalshi_source.py` | Kalshi data source — event contract markets, pricing data |
| `mock_source.py` | Mock data source for testing — returns synthetic market data without external calls |

## For AI Agents

### Working In This Directory
- Sources are auto-discovered — adding a new file with a valid `DataProvider` subclass is sufficient
- Each source implements `platform_name`, `health_check()`, `get_markets()`, `get_positions()`, `get_balance()`
- Use `mock_source.py` for testing — it generates realistic synthetic data
- All URLs come from `settings` — never hardcode API endpoints

### Testing Requirements
- Use `MockSource` in tests to avoid external API calls
- Test health check failure handling

## Dependencies

### Internal
- `backend.data.source_registry` — `source_registry` singleton
- `backend.data.provider` — `DataProvider` ABC
- `backend.config` — `settings` for API URLs and keys
