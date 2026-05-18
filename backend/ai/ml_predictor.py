"""ML predictor — uses trained model for market predictions.

Loads a trained model and provides probability predictions for
market outcomes based on engineered features.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from backend.ai.training.feature_engineering import FEATURE_ORDER, FeatureEngineer

from loguru import logger

DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "models", "ml_predictor.pkl"
)


@dataclass
class Prediction:
    """A market outcome prediction."""
    market_id: str
    probability: float  # P(YES)
    confidence: float   # model confidence (distance from 0.5)
    features: Dict[str, float]
    model_type: str = ""


class MLPredictor:
    """Load a trained model and make predictions."""

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or DEFAULT_MODEL_PATH
        self.fe = FeatureEngineer()
        self._model = None
        self._model_type = ""

    def load(self) -> bool:
        """Load the trained model from disk. Returns False if not found."""
        import joblib
        if not os.path.exists(self.model_path):
            logger.warning(f"ml_predictor: model not found at {self.model_path}")
            return False
        try:
            with open(self.model_path, "rb") as fh:
                bundle = joblib.load(fh)
            self._model = bundle["model"]
            self._model_type = bundle.get("model_type", "unknown")
            logger.info(f"ml_predictor: loaded {self._model_type} model")
            return True
        except Exception as e:
            logger.error(f"ml_predictor: failed to load model: {e}")
            return False

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def predict(self, market_row: Dict[str, Any], market_id: str = "") -> Prediction:
        """Predict outcome probability for a single market."""
        if not self.is_loaded:
            if not self.load():
                return Prediction(
                    market_id=market_id, probability=0.5, confidence=0.0,
                    features={}, model_type="none",
                )

        features = self.fe.transform_one(market_row)
        x = np.array([self.fe.to_vector(features)], dtype=float)
        prob = float(self._model.predict_proba(x)[0, 1])
        confidence = abs(prob - 0.5) * 2  # 0..1 scale

        return Prediction(
            market_id=market_id,
            probability=prob,
            confidence=confidence,
            features=features,
            model_type=self._model_type,
        )

    def predict_batch(
        self, market_rows: List[Dict[str, Any]], market_ids: Optional[List[str]] = None
    ) -> List[Prediction]:
        """Predict outcome probabilities for multiple markets."""
        if not self.is_loaded:
            if not self.load():
                return [
                    Prediction(market_id=mid or "", probability=0.5, confidence=0.0, features={})
                    for mid in (market_ids or [""] * len(market_rows))
                ]

        features_list = [self.fe.transform_one(row) for row in market_rows]
        X = np.array([self.fe.to_vector(f) for f in features_list], dtype=float)
        probs = self._model.predict_proba(X)[:, 1]

        predictions = []
        for i, (prob, features) in enumerate(zip(probs, features_list)):
            mid = market_ids[i] if market_ids and i < len(market_ids) else ""
            predictions.append(Prediction(
                market_id=mid,
                probability=float(prob),
                confidence=abs(float(prob) - 0.5) * 2,
                features=features,
                model_type=self._model_type,
            ))
        return predictions
