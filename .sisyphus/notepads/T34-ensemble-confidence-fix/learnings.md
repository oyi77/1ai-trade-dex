
### Learnings from T34: Ensemble Confidence Calculation

- The `combine_signals` function in `backend/ai/ensemble.py` was updated to include `technical_conf`, `ai_confidence`, and `orderbook_conf` as parameters.
- The confidence calculation logic was changed to a weighted average of component confidences, and then taking the maximum of this weighted average and the quality-adjusted agreement.
- The `component_breakdown` was updated to include `"weighted_avg_confidence"` and `"confidence_source"` for observability.
- Removed unused `dataclasses.field` import.

### Decisions for T34:

- Prioritized the provided confidence calculation logic for `EnsembleSignalGenerator` as per task instructions.
- Ensured `component_breakdown` now includes new fields for better observability of confidence origin.

### Problems Encountered for T34:

- **Test Blocking Issue**: Similar to T33, running automated tests for `backend/ai/ensemble.py` (or broader integration tests covering it) is blocked by the persistent `sqlalchemy.exc.InternalError: (sqlite3.InternalError) Cannot add a NOT NULL column with default value NULL` during `Base.metadata.create_all` in the test setup (`tests/conftest.py`). This issue is external to the changes made for T34 and prevents full verification of the implemented changes. `lsp_diagnostics` passed for `ensemble.py`, but functional testing is not possible in the current environment.
