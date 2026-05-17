# TEST SUITE
<!-- Parent: ../AGENTS.md -->

**Module**: `tests/` — pytest test coverage (24 files)

## PURPOSE

Python pytest test suite: strategy execution, settlement, reconciliation, API endpoints, reliability.

## TEST STRUCTURE

| Test Category | Purpose | Files |
|---------------|---------|-------|
| **Strategy** | Strategy executor, logic | test_strategy_executor.py (1150 LOC) |
| **Settlement** | Settlement, reconciliation | test_settlement_*.py |
| **Reliability** | Error recovery, edge cases | reliability/ |
| **API** | API endpoint tests | test_api_*.py |
| **Unit** | Individual function tests | Various |

## KEY TEST FILES

- `test_strategy_executor.py` (1150 LOC) — Executor tests (largest)
- `test_queue/` — Job queue tests
- `reliability/` — Error recovery tests
- `SHUTDOWN_TEST_RESULTS.md` — Recent test run results
- `TASK_32_COMPLETION.md` — Test completion tracking

## CONVENTIONS

- Fixtures: pytest `conftest.py` for shared setup
- Markers: `@pytest.mark.slow` for long tests
- Mocking: mock external APIs (Polymarket, Kalshi)
- Database: isolated test DB (not production)
- Assertions: descriptive assertion messages

## CRITICAL TESTS

- Settlement transaction rollback scenarios
- Stale position handling (closed_unresolved state)
- Auto-kill strategy governance (win rate <30%)
- Health check timeout handling

## RUNNING TESTS

```bash
pytest tests/ -v                              # All tests
pytest tests/test_strategy_executor.py -v    # Executor tests
pytest tests/ -m slow -v                      # Long tests
pytest tests/ -k "settlement" -v              # Settlement tests
pytest tests/ --tb=short                      # Short traceback
```

## ANTI-PATTERNS

- ❌ Tests without mocking external APIs
- ❌ Tests that use production database
- ❌ Flaky tests with timing dependencies
- ❌ No teardown (leaves test data)

## NOTES

- See test_results.txt for recent runs
- E2E tests in frontend/e2e/ (Playwright)
- Non-blocking E2E: Playwright tests use `|| true` in CI (failures don't break build)


## Current Test State (May 2026)

### Strategy Gate — 0 tests (GAP G-22)
`strategy_gate.py` has no unit tests. Needs coverage.

### Key Areas Needing Tests
- StrategyGate.can_execute_live()
- check_risk_and_disable()
- resolve_paper_trades()
