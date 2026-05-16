"""RL trading environment — Gymnasium.Env for prediction market trading.

Implements a reinforcement learning environment that wraps historical market
data into a standard gymnasium interface for training trading policies.
See docs/architecture/adr-011-rl-environment.md for design decisions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from loguru import logger


# --- Action constants ---
ACTION_BUY = 0
ACTION_SELL = 1
ACTION_HOLD = 2


@dataclass
class MarketOpportunity:
    """A single market opportunity used as one step in an episode."""

    probability: float  # current yes-price [0, 1]
    volume: float  # 24h volume in USD
    spread: float  # bid-ask spread [0, 1]
    time_to_settlement: float  # fraction of time remaining [0, 1]
    regime: float  # market regime indicator [0, 1]
    signal_confidence: float  # strategy signal confidence [0, 1]
    outcome: float  # actual settlement outcome: 1.0 or 0.0

    def to_observation(self) -> np.ndarray:
        """Return market features as a flat array (6 values)."""
        return np.array(
            [
                self.probability,
                self.volume,
                self.spread,
                self.time_to_settlement,
                self.regime,
                self.signal_confidence,
            ],
            dtype=np.float32,
        )


@dataclass
class PortfolioState:
    """Tracks portfolio across an episode."""

    positions: np.ndarray  # array of position sizes (positive=long, negative=short)
    bankroll: float = 1000.0
    unrealized_pnl: float = 0.0

    max_positions: int = 10

    def to_observation(self) -> np.ndarray:
        """Return portfolio state as flat array (1 + max_positions + 1 values)."""
        pos = np.zeros(self.max_positions, dtype=np.float32)
        n = min(len(self.positions), self.max_positions)
        pos[:n] = self.positions[:n]
        return np.concatenate(
            [
                np.array([self.bankroll], dtype=np.float32),
                pos,
                np.array([self.unrealized_pnl], dtype=np.float32),
            ]
        )


def generate_synthetic_opportunities(
    n: int, rng: np.random.Generator | None = None
) -> list[MarketOpportunity]:
    """Generate synthetic market opportunities for testing/training.

    Produces realistic-looking prediction market data with correlated features.
    """
    if rng is None:
        rng = np.random.default_rng()

    opportunities = []
    for _ in range(n):
        prob = rng.uniform(0.05, 0.95)
        volume = rng.exponential(5000.0)
        spread = rng.uniform(0.01, 0.15)
        time_to_settlement = rng.uniform(0.0, 1.0)
        regime = rng.uniform(0.0, 1.0)
        signal_confidence = rng.uniform(0.0, 1.0)
        # Outcome is probabilistic based on probability (noisy)
        outcome = 1.0 if rng.random() < prob else 0.0
        opportunities.append(
            MarketOpportunity(
                probability=prob,
                volume=volume,
                spread=spread,
                time_to_settlement=time_to_settlement,
                regime=regime,
                signal_confidence=signal_confidence,
                outcome=outcome,
            )
        )
    return opportunities


class PredictionMarketEnv(gym.Env):
    """Gymnasium environment for prediction market trading.

    Observation space (Dict):
        - market_features: Box(6,) — [probability, volume, spread, time_to_settlement, regime, signal_confidence]
        - portfolio: Box(max_positions+2,) — [bankroll, positions..., unrealized_pnl]

    Action space (Dict):
        - action_type: Discrete(3) — BUY=0, SELL=1, HOLD=2
        - position_size: Box(0,1) — fraction of bankroll to allocate

    Reward: Sharpe increment = (pnl_change - risk_free) / volatility
    Episode: one trading session (collection of market opportunities)
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        opportunities: list[MarketOpportunity] | None = None,
        n_opportunities: int = 100,
        initial_bankroll: float = 1000.0,
        max_positions: int = 10,
        risk_free_rate: float = 0.0,
        max_steps: int | None = None,
        seed: int | None = None,
    ):
        super().__init__()
        self._rng = np.random.default_rng(seed)
        self._all_opportunities = opportunities or []
        self._n_opportunities = n_opportunities
        self._initial_bankroll = initial_bankroll
        self._max_positions = max_positions
        self._risk_free_rate = risk_free_rate
        self._max_steps = max_steps or n_opportunities
        self._episode_seed = seed

        # Spaces
        market_dim = 6  # probability, volume, spread, time_to_settlement, regime, signal_confidence
        portfolio_dim = 1 + max_positions + 1  # bankroll + positions + unrealized_pnl

        self.observation_space = spaces.Dict(
            {
                "market_features": spaces.Box(
                    low=np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32),
                    high=np.array(
                        [1.0, np.inf, 1.0, 1.0, 1.0, 1.0], dtype=np.float32
                    ),
                    dtype=np.float32,
                ),
                "portfolio": spaces.Box(
                    low=-np.inf,
                    high=np.inf,
                    shape=(portfolio_dim,),
                    dtype=np.float32,
                ),
            }
        )

        self.action_space = spaces.Dict(
            {
                "action_type": spaces.Discrete(3),
                "position_size": spaces.Box(
                    low=0.0, high=1.0, shape=(1,), dtype=np.float32
                ),
            }
        )

        # Episode state
        self._opportunities: list[MarketOpportunity] = []
        self._portfolio = PortfolioState(
            positions=np.array([], dtype=np.float32),
            bankroll=initial_bankroll,
            max_positions=max_positions,
        )
        self._current_step = 0
        self._pnl_history: list[float] = []
        self._prev_bankroll = initial_bankroll

    def _get_obs(self) -> dict[str, np.ndarray]:
        market_obs = self._opportunities[self._current_step].to_observation()
        portfolio_obs = self._portfolio.to_observation()
        return {"market_features": market_obs, "portfolio": portfolio_obs}

    def _get_info(self) -> dict[str, Any]:
        return {
            "step": self._current_step,
            "bankroll": self._portfolio.bankroll,
            "n_positions": len(self._portfolio.positions),
            "unrealized_pnl": self._portfolio.unrealized_pnl,
            "total_pnl": self._portfolio.bankroll - self._initial_bankroll,
        }

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        super().reset(seed=seed)

        if seed is not None:
            self._rng = np.random.default_rng(seed)

        # Select opportunities for this episode
        if self._all_opportunities:
            indices = self._rng.choice(
                len(self._all_opportunities),
                size=min(self._n_opportunities, len(self._all_opportunities)),
                replace=False,
            )
            self._opportunities = [self._all_opportunities[i] for i in indices]
        else:
            self._opportunities = generate_synthetic_opportunities(
                self._n_opportunities, self._rng
            )

        self._portfolio = PortfolioState(
            positions=np.array([], dtype=np.float32),
            bankroll=self._initial_bankroll,
            max_positions=self._max_positions,
        )
        self._current_step = 0
        self._pnl_history = []
        self._prev_bankroll = self._initial_bankroll

        obs = self._get_obs()
        info = self._get_info()
        return obs, info

    def step(
        self, action: dict[str, Any]
    ) -> tuple[dict[str, np.ndarray], float, bool, bool, dict[str, Any]]:
        action_type = int(action["action_type"])
        pos_size_raw = np.asarray(action["position_size"]).flatten()
        position_size_frac = float(np.clip(pos_size_raw[0], 0.0, 1.0))

        opp = self._opportunities[self._current_step]
        bankroll_before = self._portfolio.bankroll
        pnl_change = 0.0

        if action_type == ACTION_BUY and position_size_frac > 0:
            trade_size = bankroll_before * position_size_frac
            cost = trade_size * opp.probability
            if cost <= bankroll_before and len(self._portfolio.positions) < self._max_positions:
                # Buy YES tokens: payout is 1.0 per token if outcome=1
                shares = trade_size / max(opp.probability, 1e-8)
                self._portfolio.bankroll -= cost
                self._portfolio.positions = np.append(
                    self._portfolio.positions, shares
                )
                # Settlement: outcome determines payout
                payout = shares * opp.outcome
                pnl_change = payout - cost

        elif action_type == ACTION_SELL and len(self._portfolio.positions) > 0:
            # Sell oldest position ( FIFO)
            shares = self._portfolio.positions[0]
            sell_proceeds = shares * opp.probability * position_size_frac
            self._portfolio.bankroll += sell_proceeds
            remaining = shares * (1.0 - position_size_frac)
            if remaining > 1e-8:
                self._portfolio.positions = np.append(
                    remaining, self._portfolio.positions[1:]
                )
            else:
                self._portfolio.positions = self._portfolio.positions[1:]
            pnl_change = sell_proceeds - (shares * opp.probability * position_size_frac)

        # HOLD: no-op, pnl_change = 0

        # Update unrealized PnL
        if len(self._portfolio.positions) > 0:
            current_value = np.sum(self._portfolio.positions) * opp.probability
            cost_basis = np.sum(self._portfolio.positions) * opp.probability
            self._portfolio.unrealized_pnl = current_value - cost_basis
        else:
            self._portfolio.unrealized_pnl = 0.0

        # Compute reward: Sharpe increment
        self._pnl_history.append(pnl_change)
        reward = self._compute_reward(pnl_change)

        self._prev_bankroll = self._portfolio.bankroll
        self._current_step += 1

        terminated = self._current_step >= len(self._opportunities)
        truncated = self._current_step >= self._max_steps

        obs = self._get_obs() if not (terminated or truncated) else self._zero_obs()
        info = self._get_info()
        info["pnl_change"] = pnl_change

        return obs, reward, terminated, truncated, info

    def _compute_reward(self, pnl_change: float) -> float:
        """Sharpe increment: (pnl_change - risk_free) / volatility."""
        if len(self._pnl_history) < 2:
            return pnl_change - self._risk_free_rate

        returns = np.array(self._pnl_history)
        volatility = np.std(returns)
        if volatility < 1e-8:
            return pnl_change - self._risk_free_rate
        return (pnl_change - self._risk_free_rate) / volatility

    def _zero_obs(self) -> dict[str, np.ndarray]:
        """Return zero observation for terminal state."""
        market_dim = 6
        portfolio_dim = 1 + self._max_positions + 1
        return {
            "market_features": np.zeros(market_dim, dtype=np.float32),
            "portfolio": np.zeros(portfolio_dim, dtype=np.float32),
        }
