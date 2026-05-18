# Freqtrade Architecture Patterns

**Date**: 2026-05-18
**Source**: https://github.com/freqtrade/freqtrade

## Key Architecture Patterns

### 1. Strategy Lifecycle

Freqtrade strategies follow a clear lifecycle:

```
Populate Indicators -> Generate Signals -> Enter/Exit -> Track Positions
```

- **`populate_indicators()`**: Computes all technical indicators upfront on the full dataframe
- **`populate_entry_trend()`**: Sets entry signals based on indicator conditions
- **`populate_exit_trend()`**: Sets exit signals similarly
- Strategies are loaded as Python modules from a configurable directory

**Relevance to PolyEdge**: Our strategies use `BaseStrategy.run_cycle()` instead. The freqtrade pattern of pre-computing all indicators is more efficient than computing per-tick. Consider adopting for our `general_market_scanner`.

### 2. Backtesting Pipeline

```
DataDownload -> DataProvider -> StrategyExecutor -> MetricsCalculator -> Report
```

- Uses `DataProvider` abstraction to load historical data
- Strategy executed on historical candles sequentially
- Metrics computed post-hoc (Sharpe, drawdown, win rate, profit factor)
- Supports multiple timeframes simultaneously

**Relevance to PolyEdge**: Our `backend/backtesting/` uses a similar plugin pattern with `BaseBacktestDataSource` and `BaseBacktestStrategyRunner`. The freqtrade approach of multi-timeframe support could enhance our backtester.

### 3. Configuration Pattern

- YAML-based configuration (`config.json`)
- Strategy-level overrides via `strategy_config`
- Environment variable overrides for secrets
- Configurable via Telegram bot commands at runtime

**Relevance to PolyEdge**: We use `backend/config.py` (1776 LOC) with Pydantic settings. Freqtrade's runtime config changes via bot commands could be useful for our admin API.

### 4. Deployment Patterns

- **Docker**: Official Docker images with volume-mounted strategies
- **FreqtradeBot**: Single-process asyncio loop
- **Worker mode**: Separate worker processes for backtesting
- **Telegram integration**: In-process bot for monitoring/control

**Relevance to PolyEdge**: Similar to our `main.py` entry point and Telegram bot (`backend/bot/`).

### 5. Risk Management

- `stoploss`: Global stop-loss percentage
- `trailing_stop`: Dynamic stop-loss that follows price
- `max_open_trades`: Position limit
- `stake_amount`: Fixed or dynamic position sizing
- `protections`: Cooldown periods, drawdown limits, stoploss guards

**Relevance to PolyEdge**: Our risk management in `core/risk_manager.py` is more sophisticated (Kelly criterion, dynamic sizing), but freqtrade's `protections` pattern (cooldown after consecutive losses) is worth adopting.

### 6. Order Types

- Market orders, limit orders, stop-loss orders
- Custom pricing via `custom_entry_price()` / `custom_exit_price()`
- Order book analysis for optimal fill prices

**Relevance to PolyEdge**: Our CLOB integration handles this at a lower level. Freqtrade's custom pricing hooks could inform our `order_executor` strategy.

## Patterns Worth Adopting

1. **Indicator pre-computation**: Compute all signals in one pass over the dataframe
2. **Protection system**: Cooldown/drawdown guards as pluggable modules
3. **Multi-timeframe analysis**: Analyze multiple candle sizes simultaneously
4. **Strategy versioning**: Track strategy performance by version hash
