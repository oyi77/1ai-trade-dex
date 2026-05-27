<!-- Parent: ../AGENTS.md -->
<!-- Updated: 2026-05-27 -->

# models

## Purpose
Serialized ML model artifacts. Directory contains trained logistic regression model and metadata. `baseline.pkl` is the pickled sklearn LogisticRegression model loaded at runtime by `prediction_engine.py` (in parent `backend/ai/` directory). `baseline.pkl.json` contains feature order, coefficients, intercept, training metadata, and model version for reproducibility.

## Key Files
| File | Description |
|------|-------------|
| `baseline.pkl` | Pickled sklearn LogisticRegression model (6 features); loaded by `backend.ai.prediction_engine` at startup |
| `baseline.pkl.json` | Model metadata: feature_order, coefficients, intercept, n_examples, train_accuracy, version |
| `model_hashes.json` | Hash verification for model integrity checks |

## For AI Agents
### Working In This Directory
- This directory is write-only for training pipeline; read-only for prediction engine
- Model loading happens in `prediction_engine.py` (parent directory) via `pickle.load()`
- Feature order in `baseline.pkl.json` must exactly match FEATURE_ORDER in `backend.ai.training.feature_engineering`
- Trained model is deterministic; same input features always produce same prediction
- Model artifacts are versioned by training run; older models can coexist if needed

## Dependencies
### Internal
- `backend.ai.prediction_engine` (loads and uses baseline.pkl at runtime)
- `backend.ai.training.model_trainer` (writes baseline.pkl during training)

### External
- `pickle` (Python serialization)
- `json` (metadata reading/writing)
- `sklearn.linear_model.LogisticRegression` (model class)
