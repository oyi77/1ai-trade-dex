<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-09 -->

# models

## Purpose
Serialized ML model artifacts. Directory contains trained logistic regression model and metadata. `baseline.pkl` is the pickled sklearn LogisticRegression model loaded at runtime by `prediction_engine.py`. `baseline.pkl.json` contains feature order, coefficients, intercept, training metadata, and model version for reproducibility.

## Key Files
| File | Description |
|------|-------------|
| baseline.pkl | Pickled sklearn LogisticRegression model (6 features, intercept=0.207); loaded by prediction_engine.py at startup |
| baseline.pkl.json | Model metadata: feature_order, coefficients, intercept, n_examples (800), train_accuracy (0.564), version (logreg-1.0) |

## For AI Agents
### Working In This Directory
- This directory is write-only for training pipeline; read-only for prediction engine
- Model loading happens in `prediction_engine.py` via `pickle.load()`
- Feature order in baseline.pkl.json must exactly match FEATURE_ORDER in `backend.ai.training.feature_engineering`
- Trained model is deterministic; same input features always produce same prediction
- Model version in metadata (logreg-1.0) distinguishes baseline from future ensemble/LSTM models

### Testing Requirements
- Verify baseline.pkl loads without corruption: `pickle.load()` succeeds
- Verify baseline.pkl.json parses valid JSON with all required keys
- Test prediction_engine correctly loads baseline.pkl and produces predictions
- Verify feature count (6) matches coefficients array length
- Validate model intercept and coefficients are within expected ranges (e.g., not NaN/Inf)

### Common Patterns
- Binary classification: intercept + dot(features, coefficients), then sigmoid activation
- Feature order stability is critical; retraining must preserve order or update both files
- Metadata file (baseline.pkl.json) is human-readable for debugging; pkl file is binary
- Model artifacts are versioned by training run; older models can coexist if needed

## Dependencies
### Internal
- backend.ai.prediction_engine (loads and uses baseline.pkl at runtime)
- backend.ai.training.model_trainer (writes baseline.pkl during training)

### External
- pickle (Python serialization)
- json (metadata reading/writing)
- sklearn.linear_model.LogisticRegression (model class)

<!-- MANUAL: -->
