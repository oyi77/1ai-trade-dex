<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# backtesting

## Purpose
Plugin-based backtesting engine for strategy validation. Provides abstract base classes for data sources, strategy runners, and metrics, with a central registry that composes them into a backtest pipeline. Used for historical strategy evaluation before promotion to paper/live trading.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Exports all base classes and registry: `BaseBacktestDataSource`, `BaseBacktestStrategyRunner`, `BaseBacktestMetrics`, `BacktestEngineRegistry` |
| `base.py` | ABC definitions + manifests: `BacktestDataSourceManifest`, `BacktestStrategyRunnerManifest`, `BacktestMetricsManifest` |
| `registry.py` | `BacktestEngineRegistry` — registers data sources, runners, and metrics; composes backtest pipelines |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `data_sources/` | Historical data source implementations (Polymarket) |
| `metrics/` | Backtest performance metrics (Sharpe ratio) |
| `strategy_runners/` | Strategy execution runners for backtesting |

## For AI Agents

### Working In This Directory
- Three plugin types: data sources (load historical data), runners (execute strategy on data), metrics (compute performance)
- All implement `health_check() -> bool` for liveness probing
- Use `get_registry()` to get the singleton; `reset_registry()` for tests
- Register components: `registry.register_data_source("polymarket", PolymarketDataSource())`

### Testing Requirements
- Run: `pytest backend/tests/ -k "backtest" -v`
- Use `reset_registry()` in test fixtures to avoid cross-test pollution

### Common Patterns
- Run a backtest: get registry, register components, compose pipeline
- Add a data source: subclass `BaseBacktestDataSource`, implement `load_data()` and `health_check()`

## Dependencies

### Internal
- `backend.strategies` — strategy classes passed to runners
- `backend.config` — settings for data source URLs
