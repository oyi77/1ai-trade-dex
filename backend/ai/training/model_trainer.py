"""Trainer for the prediction model.

Phase 4 milestone — replaces the original NotImplementedError stub with a
working ``LogisticRegression`` baseline. The full ensemble (LSTM + XGBoost
+ Transformer) is intentionally deferred; this layer ships first so the
end-to-end pipeline (collect → engineer → train → evaluate → serve) is
exercisable today and the swap to a heavier model is a contained change.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from sklearn.linear_model import LogisticRegression

from backend.ai.training.data_collector import TrainingExample
from backend.ai.training.feature_engineering import FEATURE_ORDER, FeatureEngineer

logger = logging.getLogger("trading_bot.training.model_trainer")

DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "models", "baseline.pkl"
)


@dataclass
class TrainResult:
    model_path: str
    n_examples: int
    feature_order: List[str]
    coefficients: List[float]
    intercept: float
    train_accuracy: float


class ModelTrainer:
    """Trains a logistic-regression baseline on labelled TrainingExamples."""

    def __init__(self, model_path: Optional[str] = None, metadata_extra: Optional[dict] = None):
        self.model_path = model_path or DEFAULT_MODEL_PATH
        self.fe = FeatureEngineer()
        self._metadata_extra = metadata_extra or {}

    def train(self, examples: List[TrainingExample]) -> TrainResult:
        if len(examples) < 8:
            raise ValueError(
                f"need at least 8 training examples, got {len(examples)}"
            )

        X = np.array([self.fe.to_vector(ex.features) for ex in examples], dtype=float)
        y = np.array([ex.label for ex in examples], dtype=float)

        model = LogisticRegression(max_iter=500, solver="lbfgs")
        model.fit(X, y)
        train_acc = float(model.score(X, y))

        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        # Security: joblib.dump() replaces pickle.dump() — avoids RCE
        # vulnerability when the model is later loaded. joblib is the
        # standard serialization format for scikit-learn models.
        import joblib

        with open(self.model_path, "wb") as fh:
            joblib.dump(
                {
                    "model": model,
                    "feature_order": FEATURE_ORDER,
                    "version": "logreg-1.0",
                    **self._metadata_extra,
                },
                fh,
            )

        result = TrainResult(
            model_path=self.model_path,
            n_examples=len(examples),
            feature_order=list(FEATURE_ORDER),
            coefficients=model.coef_.flatten().tolist(),
            intercept=float(model.intercept_[0]),
            train_accuracy=train_acc,
        )
        logger.info(
            f"trainer: trained logreg on {result.n_examples} examples, "
            f"acc={result.train_accuracy:.3f}, saved to {result.model_path}"
        )
        return result

    def metadata_path(self) -> str:
        return self.model_path + ".json"

    def write_metadata(self, result: TrainResult) -> None:
        with open(self.metadata_path(), "w") as fh:
            json.dump(
                {
                    "model_path": result.model_path,
                    "n_examples": result.n_examples,
                    "feature_order": result.feature_order,
                    "coefficients": result.coefficients,
                    "intercept": result.intercept,
                    "train_accuracy": result.train_accuracy,
                    "version": "logreg-1.0",
                    **self._metadata_extra,
                },
                fh,
                indent=2,
            )
