# Backtesting Data Sources & Metrics (G-40)

## Available Data Sources

| Source | Format | Access Method | Location |
|--------|--------|---------------|----------|
| **Kalshi trades** | SQLAlchemy `Trade` model | `BacktestEngine.run()` | `backend/core/backtester.py` |
| **Polymarket historical** | `MarketOutcome` model | `BacktestEngine.run_from_historical_markets()` | `backend/core/backtester.py` |
| **Polymarket prices** | JSON via Data API | `fetch_batch_prices_history()` | `backend/data/polymarket_clob.py` |
| **Crypto oracle tracker** | SQLite `crypto_oracle_performance` | `CryptoOracleTracker` | `backend/core/crypto_oracle_tracker.py` |
| **Signal logs** | SQLAlchemy `SignalLog` | Direct DB query | `backend/models/signal_log.py` |
| **CLOB events** | SQLAlchemy `ClobEvent` | Direct DB query | `backend/models/database.py` |

## Backtest Metrics

### Core Metrics (BacktestResult)
- **total_pnl**: Net profit/loss across all trades
- **win_rate**: Percentage of winning trades
- **max_drawdown**: Peak-to-trough equity decline
- **sharpe_ratio**: Risk-adjusted return (annualized)
- **sortino_ratio**: Downside risk-adjusted return
- **profit_factor**: Gross profit / gross loss
- **return_pct**: Total return as percentage of initial bankroll

### Extended Metrics (via PolymarketBacktestEngine)
- **spread_cost**: Bid-ask spread cost per trade (Polymarket-specific)
- **binary_resolution**: Settlement at 0.0 or 1.0 USDC (Polymarket-specific)

## Running Backtests

```python
from backend.core.backtester import BacktestConfig, BacktestEngine

config = BacktestConfig(
    strategy_name="crypto_oracle",
    start_date=datetime(2026, 1, 1),
    end_date=datetime(2026, 5, 1),
    initial_bankroll=100.0,
)
engine = BacktestEngine(config)
result = await engine.run()
```

```python
from backend.core.backtester import PolymarketBacktestConfig, PolymarketBacktestEngine

config = PolymarketBacktestConfig(
    strategy_name="crypto_oracle",
    start_date=datetime(2026, 1, 1),
    end_date=datetime(2026, 5, 1),
    spread_cost=0.02,  # 2 cents per share
)
engine = PolymarketBacktestEngine(config)
result = await engine.run()
```
