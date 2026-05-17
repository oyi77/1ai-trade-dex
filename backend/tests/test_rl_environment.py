"""Tests for PredictionMarketEnv — gymnasium interface, step/reset, and shapes."""
import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env

from backend.core.rl_environment import (
    ACTION_BUY,
    ACTION_HOLD,
    ACTION_SELL,
    MarketOpportunity,
    PredictionMarketEnv,
    generate_synthetic_opportunities,
)


# --- Fixtures ---


@pytest.fixture
def sample_opportunities():
    """Generate 20 synthetic market opportunities for testing."""
    rng = np.random.default_rng(42)
    return generate_synthetic_opportunities(20, rng)


@pytest.fixture
def env(sample_opportunities):
    """Create a PredictionMarketEnv with known opportunities."""
    return PredictionMarketEnv(
        opportunities=sample_opportunities,
        n_opportunities=10,
        initial_bankroll=1000.0,
        max_positions=5,
        seed=42,
    )


# --- Gymnasium env checker ---


def test_env_passes_gymnasium_check(sample_opportunities):
    """The environment must pass gymnasium's built-in env checker."""
    env = PredictionMarketEnv(
        opportunities=sample_opportunities,
        n_opportunities=5,
        initial_bankroll=500.0,
        max_positions=3,
        seed=99,
    )
    check_env(env, skip_render_check=True)


# --- Observation / action space shapes ---


def test_observation_space_shapes(env):
    obs, info = env.reset()
    assert "market_features" in obs
    assert "portfolio" in obs
    assert obs["market_features"].shape == (6,)
    assert obs["portfolio"].shape == (env._max_positions + 2,)  # bankroll + positions + unrealized_pnl


def test_action_space_sample_shape(env):
    env.reset()
    action = env.action_space.sample()
    assert "action_type" in action
    assert "position_size" in action
    assert action["position_size"].shape == (1,)
    assert 0 <= int(action["action_type"]) < 3


def test_observation_dtype(env):
    obs, _ = env.reset()
    assert obs["market_features"].dtype == np.float32
    assert obs["portfolio"].dtype == np.float32


# --- Reset ---


def test_reset_returns_obs_and_info(env):
    result = env.reset()
    assert isinstance(result, tuple)
    assert len(result) == 2
    obs, info = result
    assert isinstance(obs, dict)
    assert isinstance(info, dict)


def test_reset_bankroll(env):
    obs, info = env.reset()
    assert info["bankroll"] == 1000.0
    assert info["n_positions"] == 0


def test_reset_with_seed(env):
    obs1, _ = env.reset(seed=123)
    obs2, _ = env.reset(seed=123)
    np.testing.assert_array_equal(obs1["market_features"], obs2["market_features"])


# --- Step ---


def test_step_hold_returns_correct_shapes(env):
    env.reset()
    action = {"action_type": ACTION_HOLD, "position_size": np.array([0.0], dtype=np.float32)}
    obs, reward, terminated, truncated, info = env.step(action)
    assert obs["market_features"].shape == (6,)
    assert obs["portfolio"].shape == (env._max_positions + 2,)
    assert isinstance(reward, float)
    assert isinstance(terminated, bool)
    assert isinstance(truncated, bool)
    assert isinstance(info, dict)


def test_step_buy_reduces_bankroll(env):
    obs, info = env.reset()
    initial_bankroll = info["bankroll"]
    action = {"action_type": ACTION_BUY, "position_size": np.array([0.1], dtype=np.float32)}
    obs, reward, terminated, truncated, info = env.step(action)
    if not terminated:
        assert info["bankroll"] < initial_bankroll or info["n_positions"] > 0


def test_step_sell_with_no_positions_is_noop(env):
    env.reset()
    action = {"action_type": ACTION_SELL, "position_size": np.array([0.5], dtype=np.float32)}
    obs, reward, terminated, truncated, info = env.step(action)
    if not terminated:
        assert info["n_positions"] == 0


def test_episode_completes(env):
    """Run a full episode with HOLD actions — should terminate after all opportunities."""
    env.reset()
    terminated = False
    truncated = False
    steps = 0
    while not (terminated or truncated):
        action = {"action_type": ACTION_HOLD, "position_size": np.array([0.0], dtype=np.float32)}
        _, _, terminated, truncated, _ = env.step(action)
        steps += 1
        assert steps <= env._n_opportunities + 1  # safety


def test_step_returns_zero_obs_on_termination(env):
    env.reset()
    for _ in range(env._n_opportunities):
        action = {"action_type": ACTION_HOLD, "position_size": np.array([0.0], dtype=np.float32)}
        obs, reward, terminated, truncated, info = env.step(action)
    # After all steps, obs should be zeroed
    np.testing.assert_array_equal(obs["market_features"], np.zeros(6, dtype=np.float32))


# --- Synthetic data ---


def test_generate_synthetic_opportunities():
    opps = generate_synthetic_opportunities(50)
    assert len(opps) == 50
    for opp in opps:
        assert 0.0 <= opp.probability <= 1.0
        assert opp.volume >= 0.0
        assert 0.0 <= opp.spread <= 1.0
        assert 0.0 <= opp.time_to_settlement <= 1.0
        assert 0.0 <= opp.regime <= 1.0
        assert 0.0 <= opp.signal_confidence <= 1.0
        assert opp.outcome in (0.0, 1.0)


def test_generate_synthetic_opportunities_reproducible():
    opps1 = generate_synthetic_opportunities(10, np.random.default_rng(7))
    opps2 = generate_synthetic_opportunities(10, np.random.default_rng(7))
    for o1, o2 in zip(opps1, opps2):
        assert o1.probability == o2.probability
        assert o1.outcome == o2.outcome


# --- Reward ---


def test_reward_is_finite(env):
    env.reset()
    action = {"action_type": ACTION_BUY, "position_size": np.array([0.05], dtype=np.float32)}
    _, reward, _, _, _ = env.step(action)
    assert np.isfinite(reward)
