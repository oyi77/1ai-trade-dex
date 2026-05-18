# vectorbt Portfolio Optimization Integration

**Date**: 2026-05-18
**Package**: vectorbt >= 0.26.0

## What is vectorbt

vectorbt is a high-performance backtesting library that uses vectorized operations (NumPy/pandas) for extremely fast portfolio-level analysis. Unlike sequential backtesters, it can evaluate thousands of parameter combinations in seconds.

## Key Capabilities

### 1. Vectorized Backtesting

```python
import vectorbt as vbt
import pandas as pd

# Load price data
price = pd.Series(...)

# Generate signals (vectorized)
entries = price > price.rolling(20).mean()
exits = price < price.rolling(20).mean()

# Run backtest (all combinations at once)
pf = vbt.Portfolio.from_signals(price, entries, exits, init_cash=10000)
print(pf.stats())
```

### 2. Parameter Optimization

```python
# Test all SMA crossover combinations
fast = vbt.MA.run(price, window=[5, 10, 20, 50])
slow = vbt.MA.run(price, window=[20, 50, 100, 200])
entries = fast.ma_crossed_above(slow)
exits = fast.ma_crossed_below(slow)

# Vectorized evaluation of 16 combinations
pf = vbt.Portfolio.from_signals(price, entries, exits)
```

### 3. Portfolio Analytics

- Sharpe ratio, Sortino ratio, Calmar ratio
- Maximum drawdown analysis
- Rolling performance metrics
- Correlation analysis between positions

## Integration with PolyEdge

### Use Case 1: Strategy Parameter Optimization

Replace manual parameter tuning with vectorbt's grid search:

```python
# Current: manual tuning in config.py
# Proposed: vectorbt sweep
from backend.backtesting.data_sources.polymarket import PolymarketBacktestDataSource

source = PolymarketBacktestDataSource()
data = source.load_data("BTC-5MIN", "2026-01-01", "2026-05-01")

# Sweep edge thresholds
edges = [0.02, 0.03, 0.05, 0.08]
results = {e: backtest_with_edge(data, e) for e in edges}
```

### Use Case 2: Portfolio-Level Risk

Analyze cross-strategy correlation:

```python
import vectorbt as vbt

# Returns from each strategy
returns = pd.DataFrame({
    "crypto_oracle": oracle_returns,
    "whale_frontrun": whale_returns,
    "bond_scanner": bond_returns,
})

# Correlation matrix
print(returns.vbt.returns(freq="1h").corr())
```

### Use Case 3: Walk-Forward Analysis

Test strategy robustness across time periods:

```python
# Rolling window backtest
pf = vbt.Portfolio.from_signals(
    price, entries, exits,
    freq="5min",
    slippage=0.001,
    fees=0.001,
)
```

## Installation

```bash
pip install vectorbt>=0.26.0
```

## Caveats

1. **Memory usage**: Vectorized operations load all data into RAM. For large datasets, chunk the analysis.
2. **Prediction markets**: vectorbt assumes continuous price data. Polymarket binary markets (0-1 range) need custom handling.
3. **Slippage model**: Default slippage model doesn't account for CLOB order book depth. Custom slippage needed.
4. **Settlement**: Binary markets settle at 0 or 1. vectorbt's default exit logic needs modification for settlement events.

## Recommended Approach

1. Use vectorbt for **parameter sweeps** on historical 5-min market data
2. Use our existing backtester for **strategy execution** with Polymarket-specific logic
3. Use vectorbt's **analytics** (Sharpe, drawdown) on top of our backtester output
