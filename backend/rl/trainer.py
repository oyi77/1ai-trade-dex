"""RL Trainer — PPO agent for the PredictionMarketEnv using Stable-Baselines3.

Trains a PPO policy on the Gymnasium environment defined in
backend.core.rl_environment and saves the model for deployment.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from loguru import logger

# Model save directory
MODELS_DIR = Path(__file__).parent / "models"


def _flatten_obs(obs: dict) -> "np.ndarray":
    """Flatten Dict observation into a single array for SB3."""
    import numpy as np
    parts = []
    for key in sorted(obs.keys()):
        parts.append(np.asarray(obs[key]).flatten())
    return np.concatenate(parts)


class DictObsWrapper:
    """Wrapper that flattens Dict observations for SB3 compatibility."""

    def __init__(self, env):
        self.env = env
        import numpy as np
        from gymnasium import spaces
        # Compute flat observation dimension
        sample_obs, _ = env.reset()
        flat = _flatten_obs(sample_obs)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=flat.shape, dtype=np.float32,
        )
        self.action_space = spaces.Box(
            low=np.array([0.0, 0.0]),
            high=np.array([2.99, 1.0]),
            shape=(2,),
            dtype=np.float32,
        )

    def reset(self, **kwargs):
        obs, info = self.env.reset(**kwargs)
        return _flatten_obs(obs).astype("float32"), info

    def step(self, action):
        import numpy as np
        # Convert flat action back to dict
        action_type = int(np.clip(action[0], 0, 2))
        pos_size = float(np.clip(action[1], 0, 1))
        dict_action = {
            "action_type": action_type,
            "position_size": np.array([pos_size], dtype=np.float32),
        }
        obs, reward, terminated, truncated, info = self.env.step(dict_action)
        return _flatten_obs(obs).astype("float32"), reward, terminated, truncated, info

    def close(self):
        self.env.close()


class RLTrainer:
    """Trains a PPO agent on the PredictionMarketEnv.

    Args:
        n_opportunities: Number of market opportunities per episode.
        total_timesteps: Total training timesteps.
        learning_rate: PPO learning rate.
        seed: Random seed for reproducibility.
    """

    def __init__(
        self,
        n_opportunities: int = 200,
        total_timesteps: int = 50_000,
        learning_rate: float = 3e-4,
        seed: int = 42,
    ):
        self.n_opportunities = n_opportunities
        self.total_timesteps = total_timesteps
        self.learning_rate = learning_rate
        self.seed = seed
        self._model = None

    def train(self, save_path: Optional[str] = None) -> dict[str, Any]:
        """Train the PPO agent and save the model.

        Returns training stats dict.
        """
        stats: dict[str, Any] = {
            "timesteps": 0,
            "episodes": 0,
            "mean_reward": 0.0,
            "model_path": "",
            "error": None,
        }

        try:
            from stable_baselines3 import PPO
            from backend.core.rl_environment import PredictionMarketEnv

            # Create and wrap environment
            env = PredictionMarketEnv(
                n_opportunities=self.n_opportunities,
                seed=self.seed,
            )
            wrapped = DictObsWrapper(env)

            # Create PPO agent
            self._model = PPO(
                "MlpPolicy",
                wrapped,
                learning_rate=self.learning_rate,
                n_steps=2048,
                batch_size=64,
                n_epochs=10,
                gamma=0.99,
                gae_lambda=0.95,
                clip_range=0.2,
                verbose=0,
                seed=self.seed,
            )

            logger.info(
                "[RLTrainer] Starting PPO training: %d timesteps, %d opportunities/ep",
                self.total_timesteps, self.n_opportunities,
            )

            # Train
            self._model.learn(total_timesteps=self.total_timesteps)
            stats["timesteps"] = self.total_timesteps

            # Evaluate
            eval_reward = self._evaluate(wrapped, n_episodes=10)
            stats["mean_reward"] = eval_reward

            # Save model
            if save_path is None:
                MODELS_DIR.mkdir(parents=True, exist_ok=True)
                save_path = str(MODELS_DIR / "ppo_trading_agent")

            self._model.save(save_path)
            stats["model_path"] = save_path

            logger.info(
                "[RLTrainer] Training complete: mean_reward=%.3f, saved to %s",
                eval_reward, save_path,
            )

            wrapped.close()

        except ImportError as e:
            logger.warning("[RLTrainer] stable-baselines3 not installed: %s", e)
            stats["error"] = f"Missing dependency: {e}"
        except Exception as e:
            logger.error("[RLTrainer] Training failed: %s", e, exc_info=True)
            stats["error"] = str(e)

        return stats

    def load(self, path: str) -> bool:
        """Load a pre-trained model."""
        try:
            from stable_baselines3 import PPO
            self._model = PPO.load(path)
            logger.info("[RLTrainer] Loaded model from %s", path)
            return True
        except Exception as e:
            logger.error("[RLTrainer] Failed to load model: %s", e)
            return False

    def predict(self, observation) -> Any:
        """Predict action from observation."""
        if self._model is None:
            raise RuntimeError("No model loaded. Call train() or load() first.")
        action, _ = self._model.predict(observation, deterministic=True)
        return action

    def _evaluate(self, env, n_episodes: int = 10) -> float:
        """Evaluate the trained policy over n episodes."""
        import numpy as np
        total_rewards = []

        for _ in range(n_episodes):
            obs, _ = env.reset()
            episode_reward = 0.0
            done = False

            while not done:
                action, _ = self._model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, info = env.step(action)
                episode_reward += reward
                done = terminated or truncated

            total_rewards.append(episode_reward)

        return float(np.mean(total_rewards))


async def rl_training_job() -> dict[str, Any]:
    """Scheduled job: train or retrain the RL agent.

    Called by APScheduler on the configured interval.
    """
    from backend.config import settings

    if not getattr(settings, "RL_TRAINING_ENABLED", False):
        return {"skipped": True, "reason": "RL_TRAINING_ENABLED is False"}

    trainer = RLTrainer(
        n_opportunities=getattr(settings, "RL_N_OPPORTUNITIES", 200),
        total_timesteps=getattr(settings, "RL_TOTAL_TIMESTEPS", 50_000),
        learning_rate=getattr(settings, "RL_LEARNING_RATE", 3e-4),
    )
    stats = trainer.train()
    return stats
