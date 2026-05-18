"""ML training pipeline for prediction models on Polymarket data.

Extends the existing training/ infrastructure with gradient boosting,
enhanced features, and periodic retraining support.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from backend.ai.training.data_collector import DataCollector, TrainingExample
from backend.ai.training.feature_engineering import FEATURE_ORDER, FeatureEngineer

from loguru import logger

DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "models", "ml_predictor.pkl"
)


@dataclass
class MLTrainResult:
    """Result from ML training run."""
    model_path: str
    n_examples: int
    feature_order: List[str]
    train_accuracy: float
    model_type: str
    feature_importances: Dict[str, float] = field(default_factory=dict)


class MLTrainer:
    """Trains prediction models on Polymarket training data.

    Supports logistic regression (baseline) and gradient boosting (advanced).
    Fetches data via DataCollector, engineers features via FeatureEngineer.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        model_type: str = "gradient_boosting",
    ):
        self.model_path = model_path or DEFAULT_MODEL_PATH
        self.model_type = model_type
        self.fe = FeatureEngineer()

    async def collect_and_train(
        self,
        min_examples: int = 16,
        lookback_days: int = 30,
        use_synthetic_fallback: bool = True,
    ) -> MLTrainResult:
        """Collect training data and train model."""
        collector = DataCollector(page_size=100, max_pages=10)
        examples = await collector.collect(lookback_days=lookback_days)

        if len(examples) < min_examples:
            if use_synthetic_fallback:
                logger.warning(
                    f"Only {len(examples)} examples, generating synthetic fallback"
                )
                examples.extend(self._synthetic_examples(max(min_examples, 64) - len(examples)))
            else:
                raise ValueError(
                    f"Need at least {min_examples} examples, got {len(examples)}"
                )

        return self.train(examples)

    def train(self, examples: List[TrainingExample]) -> MLTrainResult:
        """Train model on provided examples."""
        if len(examples) < 8:
            raise ValueError(f"Need at least 8 examples, got {len(examples)}")

        X = np.array([self.fe.to_vector(ex.features) for ex in examples], dtype=float)
        y = np.array([ex.label for ex in examples], dtype=float)

        model = self._create_model()
        model.fit(X, y)
        train_acc = float(model.score(X, y))

        importances = self._get_feature_importances(model)
        self._save_model(model)

        result = MLTrainResult(
            model_path=self.model_path,
            n_examples=len(examples),
            feature_order=list(FEATURE_ORDER),
            train_accuracy=train_acc,
            model_type=self.model_type,
            feature_importances=importances,
        )
        logger.info(
            f"ml_trainer: trained {self.model_type} on {result.n_examples} examples, "
            f"acc={result.train_accuracy:.3f}"
        )
        return result

    def _create_model(self):
        """Create the sklearn model based on model_type."""
        if self.model_type == "gradient_boosting":
            return GradientBoostingClassifier(
                n_estimators=100,
                max_depth=3,
                learning_rate=0.1,
                random_state=42,
            )
        elif self.model_type == "logistic_regression":
            return LogisticRegression(max_iter=500, solver="lbfgs")
        else:
            raise ValueError(f"Unknown model_type: {self.model_type}")

    def _get_feature_importances(self, model) -> Dict[str, float]:
        """Extract feature importances from trained model."""
        if hasattr(model, "feature_importances_"):
            return dict(zip(FEATURE_ORDER, model.feature_importances_.tolist()))
        elif hasattr(model, "coef_"):
            coefs = model.coef_.flatten()
            return dict(zip(FEATURE_ORDER, coefs.tolist()))
        return {}

    def _save_model(self, model) -> None:
        """Save trained model to disk."""
        import joblib
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        with open(self.model_path, "wb") as fh:
            joblib.dump(
                {
                    "model": model,
                    "feature_order": FEATURE_ORDER,
                    "model_type": self.model_type,
                    "version": "ml-predictor-1.0",
                },
                fh,
            )

    def _synthetic_examples(self, n: int) -> List[TrainingExample]:
        """Generate synthetic training examples for fallback."""
        import random as _random
        rng = _random.Random(42)
        out: List[TrainingExample] = []
        for _ in range(n):
            edge = rng.uniform(-0.2, 0.2)
            yes = rng.uniform(0.1, 0.9)
            features = {
                "edge": edge,
                "model_probability": max(0.0, min(1.0, yes + edge)),
                "market_probability": yes,
                "whale_pressure": rng.uniform(-1, 1),
                "sentiment": rng.uniform(-1, 1),
                "volume_log": rng.uniform(0, 12),
            }
            score = features["edge"] * 3 + features["sentiment"] * 0.5
            label = 1.0 if score + rng.uniform(-0.3, 0.3) > 0 else 0.0
            out.append(TrainingExample(features=features, label=label, market_id="syn"))
        return out
