<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# backtesting/strategy_runners

## Purpose
Strategy execution runners for the backtesting engine. Execute strategy classes against historical data and produce trade result lists.

## Key Files
| File | Description |
|------|-------------|
| `default.py` | Default strategy runner — executes a strategy class on loaded data with given parameters |

## For AI Agents

### Working In This Directory
- Runners subclass `BaseBacktestStrategyRunner` from `backend.backtesting.base`
- Must implement `run_strategy(strategy_cls, data, params) -> list[dict]` and `health_check()`
- Return a list of trade result dicts with at minimum: market_ticker, direction, entry_price, exit_price, pnl

## Dependencies

### Internal
- `backend.backtesting.base` — `BaseBacktestStrategyRunner`, `BacktestStrategyRunnerManifest`
- `backend.strategies` — strategy classes being run
