<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# backtesting/data_sources

## Purpose
Historical data source implementations for the backtesting engine. Provides market data loaders that fetch historical price/volume data for strategy replay.

## Key Files
| File | Description |
|------|-------------|
| `polymarket.py` | Polymarket historical data source — loads CLOB data for backtesting |

## For AI Agents

### Working In This Directory
- Data sources subclass `BaseBacktestDataSource` from `backend.backtesting.base`
- Must implement `load_data(market_ticker, start_date, end_date)` and `health_check()`
- Return data in the format expected by the strategy runner

## Dependencies

### Internal
- `backend.backtesting.base` — `BaseBacktestDataSource`, `BacktestDataSourceManifest`
