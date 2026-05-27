"""Feature engineering for the prediction model.

Transforms raw Polymarket market dicts into the canonical feature dict
that ``PredictionEngine.predict`` consumes. Phase 4 milestone — replaces
the original NotImplementedError stub with a working transform that
mirrors ``PredictionEngine.extract_features``.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List
import logging

# Canonical feature order — kept stable so trained model coefficients align.
FEATURE_ORDER: List[str] = [
    "edge",
    "model_probability",
    "market_probability",
    "whale_pressure",
    "sentiment",
    "volume_log",
]


class FeatureEngineer:
    """Stateless transformer from raw market rows to canonical features."""

    def transform(self, raw: List[Dict[str, Any]]) -> List[Dict[str, float]]:
        return [self.transform_one(row) for row in raw]

    def transform_one(self, row: Dict[str, Any]) -> Dict[str, float]:
        yes_price = float(row.get("yes_price", row.get("yesPrice", 0.5)) or 0.5)
        volume = float(row.get("volume", 0.0) or 0.0)
        liquidity = float(row.get("liquidity", 0.0) or 0.0)
        whale_pressure = float(row.get("whale_pressure", 0.0) or 0.0)
        sentiment = float(row.get("sentiment", 0.0) or 0.0)

        if "model_probability" in row and row["model_probability"] is not None:
            model_probability = float(row["model_probability"])
        else:
            # Gamma API does not include model_probability in market responses;
            # we synthesise it from sentiment and whale signals. When those
            # features are also absent, edge collapses to zero, so log a
            # warning for observability.
            if row.get("sentiment") is None and row.get("whale_pressure") is None:

                logging.getLogger(__name__).warning(
                    "model_probability missing and no sentiment/whale data; edge will be 0"
                )
            sentiment_signal = max(-0.15, min(0.15, sentiment * 0.1))
            whale_signal = max(-0.15, min(0.15, whale_pressure * 0.1))
            model_probability = max(
                0.01, min(0.99, yes_price + sentiment_signal + whale_signal)
            )
        edge = model_probability - yes_price

        return {
            "edge": edge,
            "model_probability": model_probability,
            "market_probability": yes_price,
            "whale_pressure": whale_pressure,
            "sentiment": sentiment,
            "volume_log": math.log1p(max(volume + liquidity * 0.1, 0.0)),
        }

    def to_vector(self, features: Dict[str, float]) -> List[float]:
        return [features.get(k, 0.0) for k in FEATURE_ORDER]
