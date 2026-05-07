"""Prediction engine — loads the Phase-4 trained logistic regression if
available; otherwise falls back to a deterministic logistic baseline so
the end-to-end pipeline stays callable on a fresh checkout.
"""
import logging
import math
import os
import pickle
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("trading_bot.prediction_engine")


@dataclass
class Prediction:
    probability_yes: float
    confidence: float
    model_version: str


# Default feature weights for the baseline scorer (used when no trained
# model is on disk). The Phase-4 trainer overwrites these via the saved
# logistic-regression coefficients in backend/ai/models/baseline.pkl.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "edge": 1.5,
    "model_probability": 2.0,
    "market_probability": -2.0,
    "whale_pressure": 0.8,
    "sentiment": 0.6,
    "volume_log": 0.3,
}

DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "models", "baseline.pkl"
)


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


class PredictionEngine:
    MODEL_VERSION = "baseline-0.1"

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        model_path: Optional[str] = None,
    ):
        self.weights = weights or DEFAULT_WEIGHTS
        self._sk_model = None
        self._feature_order: List[str] = list(self.weights.keys())
        self._model_path = model_path or DEFAULT_MODEL_PATH
        self._try_load_model()

    def _try_load_model(self) -> None:
        if not os.path.exists(self._model_path):
            return
        try:
            import pickle
            import io
            
            class _RestrictedUnpickler(pickle.Unpickler):
                ALLOWED_PREFIXES = (
                    "sklearn.", "numpy.", "numpy",
                    "scipy.", "__builtin__", "builtins",
                    "collections", "pickle", "copyreg",
                )
                
                def find_class(self, module, name):
                    for prefix in _RestrictedUnpickler.ALLOWED_PREFIXES:
                        if module.startswith(prefix):
                            return super().find_class(module, name)
                    raise pickle.UnpicklingError(f"Blocked: {module}.{name}")
            
            with open(self._model_path, "rb") as fh:
                bundle = _RestrictedUnpickler(fh).load()
            self._sk_model = bundle.get("model")
            self._feature_order = list(
                bundle.get("feature_order", list(self.weights.keys()))
            )
            self.MODEL_VERSION = bundle.get("version", "logreg-1.0")
            logger.info(
                f"prediction_engine: loaded {self.MODEL_VERSION} from {self._model_path}"
            )
        except Exception as e:
            logger.warning(f"prediction_engine: failed to load model: {e}")
            self._sk_model = None

    def extract_features(self, market: Dict[str, Any], signal_data: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
        signal_data = signal_data or {}
        volume = float(market.get("volume", 0.0))
        # Cap volume to prevent extreme values from dominating the logistic sum.
        # Typical Polymarket market volumes are O(1k–100k); cap at 1000 keeps
        # the feature on the same scale as the other inputs.
        volume_capped = min(max(volume, 0.0), 1000.0)
        return {
            "edge": float(signal_data.get("edge", 0.0)),
            "model_probability": float(signal_data.get("model_probability", 0.5)),
            "market_probability": float(signal_data.get("market_probability", 0.5)),
            "whale_pressure": float(signal_data.get("whale_pressure", 0.0)),
            "sentiment": float(signal_data.get("sentiment", 0.0)),
            "volume_log": math.log1p(volume_capped),
        }

    def predict(self, features: Dict[str, float], strategy: Optional[str] = None) -> Prediction:
        if self._sk_model is not None:
            try:
                vec = [[float(features.get(k, 0.0)) for k in self._feature_order]]
                prob = float(self._sk_model.predict_proba(vec)[0][1])
            except Exception as e:
                logger.warning(f"sklearn predict failed, using baseline: {e}")
                prob = self._baseline_predict(features)
        else:
            prob = self._baseline_predict(features)

        if strategy is not None:
            try:
                from backend.core.outcome_repository import get_strategy_stats
                from backend.models.database import SessionLocal
                from backend.db.utils import get_db_session
                with get_db_session() as db:
                    stats = get_strategy_stats(strategy, None, db)
                    if stats and stats.get("total_trades", 0) >= 30:
                        empirical_win_rate = stats["win_rate"]
                        prob = 0.8 * prob + 0.2 * empirical_win_rate
            except Exception as e:
                logger.debug(f"Empirical blend skipped for {strategy}: {e}")

        confidence = min(1.0, abs(prob - 0.5) * 2.0)
        prob = max(0.01, min(0.99, prob))
        return Prediction(
            probability_yes=round(prob, 6),
            confidence=round(confidence, 6),
            model_version=self.MODEL_VERSION,
        )

    def _baseline_predict(self, features: Dict[str, float]) -> float:
        z = sum(self.weights.get(k, 0.0) * v for k, v in features.items())
        return _sigmoid(z)
