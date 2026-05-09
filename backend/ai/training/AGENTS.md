<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-09 -->

# training

## Purpose
ML training pipeline for the prediction model. Collects historical resolved Polymarket data, engineers features (edge, liquidity, price spread, whale pressure, sentiment, volume), trains logistic regression models, and evaluates performance with accuracy, log-loss, and calibration metrics. Saves trained artifacts to `ai/models/baseline.pkl` and metadata to `baseline.pkl.json`.

## Key Files
| File | Description |
|------|-------------|
| train.py | End-to-end entry point; orchestrates collection → feature engineering → training → evaluation; 80/20 train/eval split with seed=42 |
| data_collector.py | Fetches resolved markets from Polymarket Gamma API; builds labelled TrainingExample objects (features + label + market_id) |
| feature_engineering.py | Stateless transformer converting raw market rows to canonical 6-feature dict (edge, model_probability, market_probability, whale_pressure, sentiment, volume_log) |
| model_trainer.py | Logistic regression trainer; outputs TrainResult (model path, accuracy, feature order, coefficients, intercept) |
| model_evaluator.py | Computes accuracy, log-loss, Brier score, and ECE calibration metric from (predicted_prob, true_label) pairs |
| __init__.py | Package marker |

## For AI Agents
### Working In This Directory
- Entry point: `python -m backend.ai.training.train`
- Data source: Polymarket Gamma API (gamma-api.polymarket.com), paginated up to 100 markets/page, max 10 pages
- Feature order is canonical and immutable (FEATURE_ORDER in feature_engineering.py); trained model coefficients depend on this order
- Minimum 8 examples required for training; pipeline falls back to synthetic data if <16 examples collected
- Holdout split: 80% train, 20% eval; reproducible with seed=42

### Testing Requirements
- Test DataCollector with mocked Gamma API responses (resolved and unresolved markets)
- Verify FeatureEngineer.transform_one() produces correct feature dict for sample market rows
- Test ModelTrainer with minimum (8), normal (64+), and large (1000+) example counts
- Verify ModelEvaluator computes accuracy, log-loss, Brier, ECE correctly on known predictions
- Test train.py end-to-end with synthetic data pipeline
- Verify train.py writes baseline.pkl and baseline.pkl.json to ai/models/
- Validate feature order stability across training runs

### Common Patterns
- DataCollector and FeatureEngineer both stateless; reusable across runs
- All features normalized to float; edge can be negative (model < market probability)
- Model path defaults to `backend/ai/models/baseline.pkl` if not specified
- TrainResult captures feature order, coefficients, intercept for reproducibility
- Evaluation uses (predicted_probability, true_label) tuples; probability clipped to [1e-9, 1-1e-9]

## Dependencies
### Internal
- backend.ai.training.data_collector (DataCollector, TrainingExample)
- backend.ai.training.feature_engineering (FeatureEngineer, FEATURE_ORDER)
- backend.ai.training.model_trainer (ModelTrainer, TrainResult)
- backend.ai.training.model_evaluator (ModelEvaluator, EvalResult)

### External
- sklearn.linear_model (LogisticRegression)
- httpx (async HTTP client for Gamma API)
- numpy (numerical operations)
- logging (standard logging)

<!-- MANUAL: -->
