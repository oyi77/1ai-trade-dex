<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# tests/integration

## Purpose
Integration tests for cross-module phase gate validation. Tests that system components work together correctly across phase transitions (gates 5 and 6).

## Key Files
| File | Description |
|------|-------------|
| `test_phase_gate_5.py` | Phase gate 5 integration test — validates strategy execution pipeline end-to-end |
| `test_phase_gate_6.py` | Phase gate 6 integration test — validates AGI certification pipeline end-to-end |

## For AI Agents

### Testing Requirements
- Run: `pytest backend/tests/integration/ -v`
- These tests exercise multiple modules together — expect slower execution than unit tests
- May require test database fixtures (see `backend/tests/conftest.py`)

## Dependencies

### Internal
- `backend.core` — execution pipeline, settlement
- `backend.strategies` — strategy implementations
- `backend.evals` — evaluation framework
- `backend.tests.conftest` — shared test fixtures
