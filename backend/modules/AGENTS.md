<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/modules

## Purpose
Infrastructure modules that support strategy execution — data feeds, execution helpers, market scanners, and arbitrage utilities. These modules implement `BaseStrategy` and are registered in the strategy registry, but they are **infrastructure**, not alpha strategies. Alpha strategies belong in `backend/strategies/`.

The distinction: modules here provide data sourcing, signal mirroring, or market-making infrastructure. They do not generate independent alpha signals from market analysis.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `data_feeds/` | Market data and on-chain signal feeds |
| `execution/` | Execution helpers — order mirroring, copy trading |
| `scanners/` | Market scanning and signal detection |
| `arbitrage/` | Arbitrage detection and validation utilities |

## Key Files

| File | Description |
|------|-------------|
| `data_feeds/whale_frontrun.py` | Detects large whale orders and front-runs them (<100ms target latency) |
| `data_feeds/whale_pnl_tracker.py` | Tracks whale wallet P&L to identify informed traders |
| `execution/copy_trader.py` | Mirrors top Polymarket leaderboard traders proportionally |
| `scanners/weather_emos.py` | EMOS-calibrated weather probability forecasts vs Polymarket prices |
| `arbitrage/arb_validation.py` | Arbitrage opportunity validation utilities |
| `arbitrage/kalshi_arb.py` | Kalshi arbitrage scaffold — **not production-ready, not registered** |

## For AI Agents

### Working In This Directory
- **Do not add alpha strategies here** — if a module generates independent market signals from analysis, it belongs in `backend/strategies/`, not here.
- `kalshi_arb.py` is intentionally excluded from the strategy registry until its `run_cycle` is production-ready. Do not re-register it without a working implementation.
- All modules here implement `BaseStrategy` from `backend/strategies/base.py` — follow the same contract (implement `run_cycle`, return `CycleResult`).
- Modules in `data_feeds/` and `execution/` are registered via `backend/strategies/registry.py` using their full module path (e.g. `backend.modules.execution.copy_trader`).

### Testing Requirements
- Test with mocked exchange API responses — never hit live APIs in tests
- Whale detection tests should mock on-chain data sources
- Copy trader tests should mock the Polymarket leaderboard API

### Common Patterns
- Register a module: add its full module path to the `_MODULE_PATHS` list in `backend/strategies/registry.py`
- All modules receive `StrategyContext` in `run_cycle(ctx)` — use `ctx.db`, `ctx.settings`, `ctx.bankroll`

## Dependencies

### Internal
- `backend.strategies.base` — `BaseStrategy`, `CycleResult`, `StrategyContext`
- `backend.config` — `settings` for configuration
- `backend.data` — market data clients

### External
- `httpx` — async HTTP for external data sources
- `asyncio` — async execution
