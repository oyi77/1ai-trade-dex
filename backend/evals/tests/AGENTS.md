<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# evals/tests

## Purpose
Integration tests for the AGI evaluation framework. Tests the Phase 2 certification pipeline end-to-end.

## Key Files
| File | Description |
|------|-------------|
| `test_phase2_integration.py` | End-to-end Phase 2 certification test — runs benchmarks, verifies scores, checks report generation |

## For AI Agents

### Testing Requirements
- Run: `pytest backend/evals/tests/ -v`
- Uses `custom_scores` parameter for deterministic test results

## Dependencies

### Internal
- `backend.evals` — evals package under test
- `pytest` — test framework
