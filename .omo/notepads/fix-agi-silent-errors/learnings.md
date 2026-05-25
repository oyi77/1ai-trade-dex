## Learnings — Fix P0 Silent Error Swallowing in AGI Orchestrator

- **Date**: 2026-05-07
- **Error classification pattern**: TRANSIENT (network: TimeoutError, ConnectionError, OSError, httpx.TimeoutException, httpx.HTTPStatusError), PERMANENT (programming: TypeError, ValueError, ImportError, AttributeError, KeyError), BENIGN (everything else)
- **httpx is optional dependency**: Must lazy-import httpx exceptions to avoid hard dependency; use `_get_httpx_transient()` pattern
- **alert_engine.py has no `send_alert` function**: It's class-based (`AlertEngine`). Use `ProductionMonitor(db).send_alert()` from `backend.core.monitoring` instead
- **Existing circuit breaker**: The module already had `_consecutive_failures` + `_circuit_open` state for TRANSIENT tracking — the old code only used it for proposals/replacement/composition stages; feedback/meta/evolution/counterfactual had no classification at all
- **`_reset_circuit()`** now called on clean cycles (no errors) so the circuit can recover