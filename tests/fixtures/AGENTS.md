<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-05 | Updated: 2026-05-09 -->

# tests/fixtures

## Purpose
Test fixture data for integration and load tests. Provides sample JSON payloads that mirror real API responses.

## Key Files

| File | Description |
|------|-------------|
| `sample_signal.json` | Sample trading signal JSON with all required fields: `market`, `side`, `size`, `confidence`, `edge`, `timestamp`. |
| `sample_activity.json` | Sample activity log entry JSON for dashboard activity stream tests. |
| `sample_audit.json` | Sample audit trail JSON for compliance and audit log tests. |
| `sample_proposal.json` | Sample strategy proposal JSON for AGI proposal workflow tests. |

## For AI Agents

### Working In This Directory
- Fixtures are static JSON — no code, no computation
- Update fixtures when API response schemas change
- Use fixtures in tests with `json.load()` or `open().read()`

### Common Patterns
- All timestamps use ISO 8601 format (`2024-01-01T00:00:00Z`)
- Prices are in USDC cents (integer) or decimal (float)

## Dependencies

### Internal
- `tests/conftest.py` — Fixture loading helpers

### External
- `json` — Standard library

<!-- MANUAL: -->
