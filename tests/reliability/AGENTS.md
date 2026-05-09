<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-05 | Updated: 2026-05-09 -->

# tests/reliability

## Purpose
Reliability and fault-tolerance tests. Validates system recovery from errors, crashes, and unexpected conditions.

## Key Files

| File | Description |
|------|-------------|
| `error_recovery_test.py` | Error recovery tests: validates graceful failure handling, automatic retry, and circuit breaker recovery. |
| `error_recovery_report.md` | Report template for documenting error recovery scenarios and test results. |

## For AI Agents

### Working In This Directory
- Tests simulate failures: kill DB connection, drop network, corrupt data
- Validate system recovers without manual intervention
- Log all recovery actions for audit purposes

### Common Patterns
- Use `unittest.mock.patch` to simulate failures in dependencies
- Assert system state returns to "healthy" within 60 seconds

## Dependencies

### Internal
- `backend.core.circuit_breaker` — Circuit breaker for resilience
- `backend.core.retry` — Retry logic

### External
- `pytest` — Test runner
- `unittest.mock` — Failure simulation

<!-- MANUAL: -->
