<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-07 | Updated: 2026-05-10 -->

# arbitrage

## Purpose
Cross-platform arbitrage modules. The `kalshi_arb` module detects price gaps between Polymarket and Kalshi for the same event.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `kalshi_arb.py` | Detects price gaps between Polymarket and Kalshi for the same event; configurable fee thresholds and minimum edge requirements |

## For AI Agents

### Working In This Directory
- This is an arbitrage module, NOT an alpha strategy
- Imported by `backend.strategies.registry` as a functional strategy entry
- `kalshi_arb` follows the standard `Strategy` interface

### Testing Requirements
- Integration tests in `tests/` at project root

### Common Patterns
- Implements `Strategy` interface from `backend.strategies.base`
- Uses `@register_strategy("kalshi_arb")` decorator

## Dependencies

### Internal
- `backend.data.polymarket_clob` — Polymarket order data
- `backend.data.kalshi_client` — Kalshi market data
- `backend.config` — Settings (KALSHI_*, ARB_* thresholds)

### External
- `httpx` — Async HTTP for API calls

<!-- MANUAL: -->