## Decisions — Fix P0 Silent Error Swallowing in AGI Orchestrator

- **Date**: 2026-05-07
- **classify_exception() function** returns ErrorType enum — centralized classification logic so all 7 except blocks use the same criteria. Avoids duplicating exception tuples in 7 places.
- **PERMANENT errors always re-raise** — programming errors (ImportError, TypeError, etc.) mean the code is broken; continuing is dangerous. Re-raise so scheduler/human sees the failure.
- **TRANSIENT errors re-raise through circuit breaker** — _record_transient_failure() increments counter; after 3 consecutive failures, circuit opens and halts the cycle entirely.
- **BENIGN errors continue** — unexpected/unclassified exceptions log a warning but don't stop the cycle. Maintains backward compatibility for "unknown" failures.
- **STATS_REPORT_CRITICAL_ERRORS** is opt-in (default false) — uses `os.getenv` not config.py to avoid circular import risk; delegates to ProductionMonitor.send_alert() which handles Slack/Discord webhooks.
- **End-of-cycle summary log**: Always logs `cycle completed with N error(s)` at WARNING level when errors exist, so no cycle completes silently even with BENIGN errors.