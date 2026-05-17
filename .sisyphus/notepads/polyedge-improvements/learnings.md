- **SignalLog Performance Tuning**:
  - Implemented composite indexes to cover primary query patterns (strategy+mid for calibration, market+timestamp for time-series).
  - Added a partial index in the migration for Postgres: `WHERE filled IS TRUE AND pnl IS NULL` to optimize the settlement worker's scan.
  - Built `QueryTimer` directly into the repository layer to facilitate latency profiling without external instrumentation dependencies.

## T16 — RED phase test_maker_first.py (2026-05-14)
- PolymarketCLOB constructor signature: `PolymarketCLOB(private_key=None, ...)` — does NOT accept a `paper=` kwarg. Implementation derives paper mode from `private_key is None` or settings. Fixture deferred; tests fail RED-style at fixture setup which is expected (no method exists yet).
- Sibling RED test reference: `backend/tests/test_token_bucket.py` — minimal, imports the not-yet-existing class at top of file.
- pytest config in `pytest.ini` defaults `asyncio_mode=auto` (no `@pytest.mark.asyncio` decorators are stripped).
- Existing maker-first impl lives in `backend/core/strategy_executor._maker_first_execute` (workflow-level); plan T13 still expects a CLOB-level helper `place_maker_first_order` plus `record_maker_fill_rate()` module-level metric.

## T18 — APScheduler position_monitor_job (2026-05-14)
- scheduler.py imports `position_monitor_job` from scheduling_strategies, NOT directly from position_monitor.py
- scheduling_strategies.py re-exports `position_monitor_job` via: `from backend.core.position_monitor import position_monitor_job`
- Must add `position_monitor_job` to `__all__` in scheduling_strategies.py to silence F401 ruff warning
- JOB_FUNCTION_REGISTRY in scheduler.py must have `"position_monitor_job": position_monitor_job` entry
- APScheduler job registered via `_persist_and_add_job(scheduler, position_monitor_job, IntervalTrigger(minutes=30), id="position_monitor", ...)`

## T9 — btc_oracle Kelly wiring (2026-05-14)
- `get_bucket_win_rate(market_mid, "btc_oracle")` returns `float | None` — use `or 0` default
- `kelly_fraction(win_rate, market_mid)` signature: `kelly_fraction(win_prob: float, price: float, kelly_multiplier: float = 1.0, cap: float = 0.25) -> float`
- Kelly returns 0 for no-edge (win_rate <= market price), >0 otherwise
- btc_oracle has 3 call sites for `calculate_dynamic_size`: on_market_event (line ~300), run_cycle market loop (line ~475), run_cycle keyword loop (line ~602)
- All 3 replaced with: `kelly = kelly_fraction(get_bucket_win_rate(market_mid, "btc_oracle") or 0, market_mid)` then `if kelly > 0: use kelly-sized cap else fallback to calculate_dynamic_size`
- `settings.INITIAL_BANKROLL = 100.0` used as bankroll for Kelly computation (no live bankroll in strategy context)
- Fixed F841 in risk_manager.py: unused `side_no` variable in check_side_lock (line 548) — removed it
- `__all__` trick to silence F401 for re-exported symbols in scheduling_strategies.py
