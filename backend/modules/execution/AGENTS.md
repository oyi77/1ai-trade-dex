<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-07 | Updated: 2026-05-10 -->

# execution

## Purpose
Trade execution support modules. The `copy_trader` module mirrors top trader positions from the Polymarket leaderboard.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `copy_trader.py` | Mirrors top whale trader positions from Polymarket leaderboard; configurable trade sizing and threshold parameters |

## For AI Agents

### Working In This Directory
- This is an execution module, NOT an alpha strategy
- Imported by `backend.strategies.registry` as a functional strategy entry
- `copy_trader` follows the standard `Strategy` interface

### Testing Requirements
- `pytest tests/test_copy_trader.py tests/test_copy_trader_http.py -v`

### Common Patterns
- Implements `Strategy` interface from `backend.strategies.base`
- Uses `@register_strategy("copy_trader")` decorator
- Read wallet/config snapshots in a short-lived DB session before awaiting leaderboard or market HTTP calls; only use the cycle session for immediate writes that commit before the next await

## Dependencies

### Internal
- `backend.data.polymarket_scraper` — Leaderboard data source
- `backend.config` — Settings (COPY_TRADER_*, LEADERBOARD_* thresholds)
- `backend.models.database` — Trade and signal models
- `backend.core.risk_manager` — Position sizing and risk checks

### External
- `py_clob_client` — Polymarket CLOB for order execution
- `httpx` — Async HTTP client

<!-- MANUAL: -->
