<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# backtesting/metrics

## Purpose
Performance metrics for backtesting engine. Computes risk-adjusted returns and other performance indicators from backtest trade results.

## Key Files
| File | Description |
|------|-------------|
| `sharpe.py` | Sharpe ratio computation — risk-adjusted return metric for backtest evaluation |

## For AI Agents

### Working In This Directory
- Metrics subclass `BaseBacktestMetrics` from `backend.backtesting.base`
- Must implement `compute(trades, equity_curve) -> dict` and `health_check()`
- Return a dict of metric name to value pairs

## Dependencies

### Internal
- `backend.backtesting.base` — `BaseBacktestMetrics`, `BacktestMetricsManifest`
