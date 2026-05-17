# RL Environment Design

## Overview

`PredictionMarketEnv` is a `gymnasium.Env` implementation for training reinforcement learning agents to trade prediction markets. It wraps historical (or synthetic) market data into the standard Gymnasium step/reset interface.

**Module**: `backend/core/rl_environment.py`
**ADR**: `docs/architecture/adr-011-rl-environment.md`

## Observation Space

Dict with two keys:

| Key | Shape | Description |
|-----|-------|-------------|
| `market_features` | Box(6,) | `[probability, volume, spread, time_to_settlement, regime, signal_confidence]` |
| `portfolio` | Box(max_positions+2,) | `[bankroll, position_0, ..., position_n, unrealized_pnl]` |

- `probability`: current YES price in [0, 1]
- `volume`: 24h USD volume (unbounded)
- `spread`: bid-ask spread in [0, 1]
- `time_to_settlement`: fraction of time remaining in [0, 1]
- `regime`: market regime indicator in [0, 1] (0=bearish, 1=bullish)
- `signal_confidence`: strategy signal confidence in [0, 1]
- `bankroll`: current cash in USD
- `positions`: array of held YES-token shares per open position
- `unrealized_pnl`: mark-to-market PnL of open positions

## Action Space

Dict with two keys:

| Key | Type | Description |
|-----|------|-------------|
| `action_type` | Discrete(3) | BUY=0, SELL=1, HOLD=2 |
| `position_size` | Box(0,1) | Fraction of bankroll to allocate (BUY) or fraction of oldest position to sell (SELL) |

## Reward Function

Sharpe increment per step:

```
reward = (pnl_change - risk_free_rate) / volatility
```

Where `volatility` is the standard deviation of all PnL changes in the current episode. For the first step (insufficient history), reward is simply `pnl_change - risk_free_rate`.

This encourages the agent to maximize risk-adjusted returns rather than raw PnL.

## Episode Structure

- Each episode is one "trading session" — a sequence of market opportunities
- `reset()` selects a random subset of historical markets (or generates synthetic ones)
- `step()` processes one market opportunity: the agent decides to buy/sell/hold
- Episode terminates when all opportunities are exhausted
- Episode truncates at `max_steps` if configured

## Trade Execution

- **BUY**: Allocates `bankroll * position_size_fraction` to buy YES tokens at current probability. Shares = allocation / probability. Settlement payout = shares * outcome.
- **SELL**: Sells `position_size_fraction` of the oldest held position at current probability price.
- **HOLD**: No trade executed.

## Safety Boundaries

- RL training runs ONLY against historical/synthetic data — never live markets
- Trained policies enter the promotion pipeline at SHADOW status (ADR-006)
- Statistical gates (minimum trades, Sharpe threshold, max drawdown) still apply
- RL does not have authority to bypass RiskManager

## Usage

```python
from backend.core.rl_environment import PredictionMarketEnv, generate_synthetic_opportunities

# With synthetic data
env = PredictionMarketEnv(n_opportunities=100, initial_bankroll=1000.0)
obs, info = env.reset(seed=42)

# With historical data
from backend.core.rl_environment import MarketOpportunity
opportunities = [...]  # loaded from DB or CSV
env = PredictionMarketEnv(opportunities=opportunities, n_opportunities=50)

# Training with SB3
from stable_baselines3 import PPO
model = PPO("MultiInputPolicy", env, verbose=1)
model.learn(total_timesteps=10000)
```

## Integration with Evolution

The RL environment connects to the evolution system via `RLEvolution` (to be implemented in `backend/core/rl_evolution.py`):

- `train(genome, episodes)` produces a trained policy
- `export_parameters(policy)` converts to genome-compatible parameter dict
- Trained parameters flow through the same promotion pipeline as evolved genomes

## Tests

```bash
pytest backend/tests/test_rl_environment.py -v
```

Tests cover:
- Gymnasium env checker compliance (`check_env`)
- Observation/action space shapes and dtypes
- Reset produces valid initial state
- Step transitions produce correct shapes
- Buy reduces bankroll, sell with no positions is no-op
- Full episode terminates correctly
- Synthetic data generation is reproducible
- Reward is always finite
