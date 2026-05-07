"""End-to-end smoke for the Phase-4 training pipeline.

Uses synthetic examples (no network) to exercise:
- FeatureEngineer.transform_one + to_vector
- ModelTrainer.train -> writes a pickle
- PredictionEngine loads the trained pickle and predicts in [0, 1]
- ModelEvaluator computes accuracy / log_loss / brier / ece
"""
import os
import random

import pytest

from backend.ai.prediction_engine import PredictionEngine
from backend.ai.training.data_collector import TrainingExample
from backend.ai.training.feature_engineering import FEATURE_ORDER, FeatureEngineer
from backend.ai.training.model_evaluator import ModelEvaluator
from backend.ai.training.model_trainer import ModelTrainer


def _synthetic(n: int = 64) -> list[TrainingExample]:
    rng = random.Random(0)
    out = []
    for _ in range(n):
        edge = rng.uniform(-0.2, 0.2)
        yes = rng.uniform(0.1, 0.9)
        sentiment = rng.uniform(-1, 1)
        features = {
            "edge": edge,
            "model_probability": max(0.0, min(1.0, yes + edge)),
            "market_probability": yes,
            "whale_pressure": rng.uniform(-1, 1),
            "sentiment": sentiment,
            "volume_log": rng.uniform(0, 12),
        }
        score = features["edge"] * 3 + sentiment * 0.5
        label = 1.0 if score + rng.uniform(-0.3, 0.3) > 0 else 0.0
        out.append(TrainingExample(features=features, label=label, market_id="syn"))
    return out


def test_feature_engineer_canonical_order():
    fe = FeatureEngineer()
    f = fe.transform_one({"yes_price": 0.4, "volume": 1000, "sentiment": 0.5})
    assert set(f.keys()) == set(FEATURE_ORDER)
    vec = fe.to_vector(f)
    assert len(vec) == len(FEATURE_ORDER)


def test_trainer_writes_pickle_and_predicts(tmp_path):
    model_path = str(tmp_path / "test_model.pkl")
    trainer = ModelTrainer(model_path=model_path)
    result = trainer.train(_synthetic(64))
    assert os.path.exists(model_path)
    assert result.n_examples == 64
    assert 0.0 <= result.train_accuracy <= 1.0
    assert len(result.coefficients) == len(FEATURE_ORDER)

    engine = PredictionEngine(model_path=model_path)
    sample_features = {k: 0.0 for k in FEATURE_ORDER}
    sample_features["edge"] = 0.1
    sample_features["sentiment"] = 0.5
    pred = engine.predict(sample_features)
    assert 0.0 <= pred.probability_yes <= 1.0
    assert 0.0 <= pred.confidence <= 1.0
    assert pred.model_version == "logreg-1.0"


def test_evaluator_metrics():
    evalr = ModelEvaluator()
    perfect = [(0.99, 1.0), (0.01, 0.0), (0.95, 1.0), (0.05, 0.0)]
    m = evalr.evaluate_full(perfect)
    assert m.accuracy == 1.0
    assert m.brier < 0.05
    assert m.log_loss < 0.1

    flipped = [(0.99, 0.0), (0.01, 1.0)]
    m2 = evalr.evaluate_full(flipped)
    assert m2.accuracy == 0.0
    assert m2.brier > 0.5

    assert evalr.evaluate_full([]).n == 0


def test_prediction_engine_falls_back_to_baseline_when_no_model(tmp_path):
    missing = str(tmp_path / "does_not_exist.pkl")
    engine = PredictionEngine(model_path=missing)
    pred = engine.predict({k: 0.0 for k in FEATURE_ORDER})
    assert 0.0 <= pred.probability_yes <= 1.0
    assert engine._sk_model is None
    assert engine.MODEL_VERSION == "baseline-0.1"


def test_trainer_rejects_too_few_examples(tmp_path):
    trainer = ModelTrainer(model_path=str(tmp_path / "x.pkl"))
    with pytest.raises(ValueError):
        trainer.train(_synthetic(4))
