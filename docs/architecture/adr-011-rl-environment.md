# ADR-011: RL Environment

**Status:** Accepted
**Date:** 2026-05-17

## Context

PolyEdge's strategy optimization currently relies on genome evolution (ADR-010) and Bayesian optimization (`ai/bayesian_optimizer.py`). These approaches optimize parameters in isolation — they do not learn from sequential decision-making under uncertainty, which is the core nature of trading.

Reinforcement learning enables agents to learn optimal trading policies by interacting with a simulated market environment, receiving rewards based on P&L outcomes. The gap analysis identified FinRL's gymnasium.Env pattern as the standard interface for financial RL, with Stable-Baselines3 (SB3) as the recommended initial library.

The system needs an RL environment that:
1. Wraps the existing backtester into a standard Gymnasium interface
2. Defines state (market features, portfolio), action (position sizing, entry/exit), and reward (risk-adjusted returns) spaces
3. Supports training against historical data without affecting production
4. Produces trained policies that can be deployed as strategy parameter sets

## Decision

Introduce a `PredictionMarketEnv` implementing `gymnasium.Env` for RL-based strategy parameter optimization.

### Environment Definition

`backend/core/rl_environment.py` defines:

```
PredictionMarketEnv(gymnasium.Env)
    observation_space  — Box containing:
        - market features (price, volume, spread, regime indicator)
        - portfolio state (positions, unrealized P&L, available capital)
        - strategy parameters (current genome values)
    action_space       — Box containing:
        - position size adjustment [-1.0, 1.0]
        - entry confidence threshold [0.0, 1.0]
        - exit threshold [0.0, 1.0]
    reward             — Risk-adjusted return:
        - Sharpe contribution per step
        - Penalty for drawdown breaches
        - Penalty for transaction costs
    step(action)       — Apply action, advance market state, return (obs, reward, done, info)
    reset()            — Reset to random historical starting point
```

### RL Algorithm Strategy

| Phase | Algorithm | Purpose |
|---|---|---|
| Initial | SB3 PPO | Stable, well-understood, good for continuous action spaces |
| Initial | SB3 SAC | Better sample efficiency for off-policy learning |
| Long-term | Ray RLlib | Distributed training across multiple strategy genomes |

SB3 is chosen initially because:
- Single-process simplicity matches current deployment model
- Gymnasium integration is native
- FinRL's own progression validates this staged approach

### Integration with Evolution

The RL environment connects to the evolution system via `RLEvolution`:

```
class RLEvolution:
    """Trains RL policies and exports them as StrategyGenome parameter sets."""
    
    def train(genome, episodes) → TrainedPolicy
    def export_parameters(policy) → dict  # genome-compatible parameter dict
```

Trained policies are exported as parameter dictionaries that plug into existing `StrategyGenome` chromosomes. This means RL-optimized parameters flow through the same promotion pipeline (ADR-006) as evolved genomes — no special deployment path.

### Safety Boundaries

- RL training runs ONLY against historical data — never live market interaction
- Trained policies enter the promotion pipeline at SHADOW status (ADR-006)
- Statistical gates (minimum trades, Sharpe threshold, max drawdown) still apply
- RL does not have authority to bypass RiskManager (ADR-004, ADR-005)

## Alternatives Considered

1. **Ray RLlib as primary.** Deferred because the distributed training overhead is not justified for current scale. Single-process SB3 is simpler and sufficient for training against historical data.

2. **Custom RL implementation.** Rejected because Gymnasium provides a well-tested standard interface. Building a custom environment interface adds maintenance burden without benefit.

3. **Online RL with live market data.** Rejected because the risk of RL exploration (trying random actions) in live markets is unacceptable. All training must be offline against historical data, with policies validated through the standard promotion pipeline.

4. **RL as replacement for genome evolution.** Rejected because RL and evolution solve different problems. RL optimizes sequential decision policies; evolution optimizes parameter spaces. They are complementary — RL can optimize within a genome, evolution can evolve the genome structure.

## Consequences

**Positive**
- Standard Gymnasium interface enables using any RL library (SB3, RLlib, CleanRL)
- Offline training eliminates live market risk during learning
- Trained policies integrate with existing promotion pipeline — no new deployment path
- Enables learning from sequential market interactions, not just static parameter optimization
- Environment can be reused for backtesting any strategy against historical regimes

**Negative**
- Reward shaping is non-trivial — poor reward functions produce degenerate trading policies
- Training is computationally expensive — large historical datasets require significant GPU/CPU time
- Overfitting to historical data is a real risk — out-of-sample validation is mandatory
- Action space definition constrains what the agent can learn — poor action design limits policy quality

## Rollback Plan

Remove `backend/core/rl_environment.py` and `backend/core/rl_evolution.py`. The RL environment is a standalone module with no production dependencies — removing it has zero impact on existing trading functionality. Any RL-trained parameters already in the genome registry continue to function as regular genomes.
