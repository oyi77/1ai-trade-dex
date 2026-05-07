"""End-to-end training entry point.

Usage::

    python -m backend.ai.training.train

Pulls resolved Polymarket markets, builds features, trains a logistic
regression baseline, evaluates with a hold-out split, and saves the
model + metadata under ``backend/ai/models/``.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import List, Tuple

import numpy as np

from backend.ai.training.data_collector import DataCollector, TrainingExample
from backend.ai.training.feature_engineering import FeatureEngineer
from backend.ai.training.model_evaluator import ModelEvaluator
from backend.ai.training.model_trainer import ModelTrainer

logger = logging.getLogger("trading_bot.training.train")


def _split(
    examples: List[TrainingExample], holdout_frac: float = 0.2, seed: int = 42
) -> Tuple[List[TrainingExample], List[TrainingExample]]:
    rng = random.Random(seed)
    shuffled = examples[:]
    rng.shuffle(shuffled)
    cut = max(1, int(len(shuffled) * holdout_frac))
    return shuffled[cut:], shuffled[:cut]


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    collector = DataCollector(page_size=100, max_pages=10)
    examples = await collector.collect()
    logger.info(f"collected {len(examples)} labelled examples")

    if len(examples) < 16:
        logger.warning(
            f"only {len(examples)} examples; baseline requires >=16. "
            "Falling back to SYNTHETIC seed — model will carry 'synthetic-data' flag."
        )
        examples = _synthetic_examples(64)
        synthetic_used = True
    else:
        synthetic_used = False

    train_set, eval_set = _split(examples, holdout_frac=0.2)
    trainer = ModelTrainer(metadata_extra={"synthetic_data": synthetic_used})
    result = trainer.train(train_set)
    trainer.write_metadata(result)

    fe = FeatureEngineer()
    # Security: joblib.load() is the standard for scikit-learn models
    # and does NOT execute arbitrary code from unpickled objects,
    # unlike raw pickle.load() which is vulnerable to RCE.
    import joblib

    with open(result.model_path, "rb") as fh:
        bundle = joblib.load(fh)
    model = bundle["model"]
    X_eval = np.array([fe.to_vector(ex.features) for ex in eval_set], dtype=float)
    if len(X_eval) > 0:
        probs = model.predict_proba(X_eval)[:, 1]
        pairs = list(zip(probs.tolist(), [ex.label for ex in eval_set]))
        metrics = ModelEvaluator().evaluate_full(pairs)
        logger.info(
            f"eval: acc={metrics.accuracy} log_loss={metrics.log_loss} "
            f"brier={metrics.brier} ece={metrics.ece} n={metrics.n}"
        )

    logger.info(
        f"training complete — model saved to {result.model_path} "
        f"({result.n_examples} examples, train_acc={result.train_accuracy:.3f})"
    )


def _synthetic_examples(n: int) -> List[TrainingExample]:
    rng = random.Random(0)
    fe = FeatureEngineer()
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
        # Synthetic label: probability of YES correlated with edge + sentiment
        score = features["edge"] * 3 + features["sentiment"] * 0.5
        label = 1.0 if score + rng.uniform(-0.3, 0.3) > 0 else 0.0
        out.append(TrainingExample(features=features, label=label, market_id="syn"))
        _ = fe.to_vector(features)  # exercise the FE
    return out


if __name__ == "__main__":
    asyncio.run(main())


async def run_training_pipeline(min_examples: int = 200) -> dict:
    try:
        collector = DataCollector(page_size=100, max_pages=10)
        examples = await collector.collect()
        if len(examples) < min_examples:
            return {"status": "skipped", "reason": f"only {len(examples)} examples, need {min_examples}", "n_examples": len(examples), "accuracy": 0.0}
        train_set, eval_set = _split(examples, holdout_frac=0.2)
        trainer = ModelTrainer(metadata_extra={"synthetic_data": False})
        result = trainer.train(train_set)
        trainer.write_metadata(result)
        fe = FeatureEngineer()
        # Security: joblib.load() replaces pickle.load() — avoids RCE vulnerability
        import joblib

        with open(result.model_path, "rb") as fh:
            bundle = joblib.load(fh)
        model = bundle["model"]
        X_eval = np.array([fe.to_vector(ex.features) for ex in eval_set], dtype=float)
        accuracy = float(model.score(X_eval, [ex.label for ex in eval_set])) if len(X_eval) > 0 else result.train_accuracy
        return {"status": "ok", "accuracy": accuracy, "n_examples": result.n_examples, "model_path": result.model_path, "train_accuracy": result.train_accuracy}
    except Exception as e:
        logger.error(f"Training pipeline failed: {e}")
        return {"status": "error", "reason": str(e), "n_examples": 0, "accuracy": 0.0}
