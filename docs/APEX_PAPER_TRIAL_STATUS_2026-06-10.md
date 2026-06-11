# APEX Paper Trial — Bug Report & Recovery Plan

**Date:** 2026-06-10
**Author:** automated setup session
**Status:** paper trial wired but blocked by 2 bugs in APEX commit `547a451b`

## Current State

| Component | State |
|-----------|-------|
| `backend/strategies/apex_strategy.py` | present on main, auto-registered in `STRATEGY_REGISTRY` via `__init__.py` import |
| `backend/core/edge/scanners/{resolution_timing,order_book_stale,liquidity_gap}.py` | present |
| `backend/core/edge/{registry,signal_pipeline,exit_manager,calibration_tracker,...}.py` | present |
| `backend/core/risk/risk_manager.py::evaluate_apex_signal` | present |
| `backend/config.py` APEX_* settings | present (19 vars) |
| `StrategyConfig` DB row (mode=paper, enabled=true) | inserted |
| `ScheduledJob` row (paper_apex_120, 120s interval) | active (cycle 1 ran 22:25:55) |
| PM2 orchestrator (`polyedge-orchestrator`) | restarted, running clean |
| **APEX paper cycles** | **0 trades placed, 0 edges detected** |

## Bug #1: `calibration_tracker.refresh_from_db` raises `NameError: name 'Trade' is not defined`

**Symptom (log line):**
```
2026-06-10T22:25:55.846+07:00 WARNING  backend.core.edge.calibration_tracker:refresh_from_db:91 Calibration refresh failed: name 'Trade' is not defined
```

**Root cause:**
`backend/core/edge/calibration_tracker.py` lines 18-20 place the `Trade` import inside a `TYPE_CHECKING` guard. Under `from __future__ import annotations` (line 9), annotations are lazy — but `db.query(Trade)` is runtime code, and `Trade` is only a string in TYPE_CHECKING mode, so the symbol is undefined at the call site.

```python
# Lines 16-20 (current)
from backend.core.edge.edge_types import clamp

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from backend.models.database import Trade
```

**Fix (1-line):** move the `Trade` import out of TYPE_CHECKING and into the runtime import block:

```python
from backend.core.edge.edge_types import clamp
from backend.models.database import Trade

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
```

**Impact if not fixed:** every APEX cycle logs this warning and skips calibration. Pipeline still runs but without predicted-vs-realized feedback (no confidence adjustment, no probability calibration). Not fatal for the trial, but defeats one of APEX's core value props.

## Bug #2: APEX scanners don't match the `EdgeScannerABC` interface

**Symptom (log line):**
```
2026-06-10T22:25:55.846+07:00 WARNING  backend.core.edge.registry:run_all_scanner:135 [APEX] Scanner resolution_timing failed:
WARNING  backend.core.edge.registry:run_all_scanner:135 [APEX] Scanner order_book_stale failed:
WARNING  backend.core.edge.registry:run_all_scanner:135 [APEX] Scanner liquidity_gap failed:
```
Empty error message — the `run_all` method swallows the exception `str()` which is empty for some types.

**Root cause:**
- `EdgeScannerABC.detect(markets, ctx)` is the abstract method (registry.py:33)
- All three scanner implementations define `async def scan(self, ctx)` instead — no `detect` method
- `EdgeRegistry.run_all()` calls `scanner.detect(markets, ctx)` → `AttributeError`
- The empty `str()` is because the except handler formats `result = "" if scanner is None else ""` and the AttributeError message gets stripped by the wrapper

**Two possible fixes (pick one):**

**Fix 2a — update the scanners** to implement `detect(markets, ctx)` and accept the markets argument. This requires touching 3 files (~30 lines of signature changes) but is the architecturally correct path. Each scanner already fetches its own markets via Gamma API, so the `markets` argument is unused — add a leading parameter.

**Fix 2b — update the ABC + registry** to call `scan(ctx)` and drop the `markets` argument. Smaller diff (2 files, ~10 lines). Matches what the test file expects (see `test_apex_edge.py:297` `DummyScanner` defines `async def scan(self, ctx)`).

**Recommended: 2b.** Smaller blast radius, matches existing tests, doesn't require APEX strategy code to pass a markets list.

```python
# registry.py line 33
async def scan(self, ctx: Any) -> List[Edge]:   # was: detect(markets, ctx)
    raise NotImplementedError

# registry.py run_all
async def run_all(self, markets, ctx):  # signature unchanged
    for name, scanner in self._scanners.items():
        try:
            result = await scanner.scan(ctx)  # was: detect(markets, ctx)
            ...
```

**Impact if not fixed:** APEX produces 0 edges per cycle. No trades are ever placed. The "trial" is producing zero data.

## Bug #3 (cosmetic): `apex_strategy._signal_to_decision` returns Signal fields the downstream executor may not parse

Not blocking the trial (no signals even reach this point). Defer until bug #2 is fixed and we can see actual signal flow.

## Bug #4 (low-priority): APEX runs in BOTH live + paper modes despite StrategyConfig.mode=paper

**Symptom (log line):**
```
2026-06-10T22:25:55.846+07:00 INFO scheduler strategy_cycle_job dispatching effective_mode=live, will execute in BOTH live+paper modes strategy=apex
```

The `effective_mode` logic in `scheduling_strategies.py` falls through to "BOTH" when `ctx.mode` doesn't match the row's `mode` field. With the orchestrator running in `live` mode, APEX (configured `mode=paper`) is being asked to run live+paper.

**Impact:** for paper trading, this means APEX decisions are evaluated by the live risk manager path. The risk_manager's `evaluate_apex_signal` should still gate to paper (no live bankroll touches), but it adds noise. Fix the strategy_cycle_job dispatch to respect `StrategyConfig.trading_mode` and `mode` columns as a hard filter, not a "preferred" tag.

## What is working

- `STRATEGY_REGISTRY` contains APEX (confirmed via enable_apex_paper.py output)
- `ScheduledJob` row exists for `paper_apex_120` (confirmed via scheduler log)
- Cycle fires every 120s (confirmed via pm2 logs at 22:25:55, 22:27:55, ...)
- `cycle_result.decisions_recorded == 0` because scanners fail (bug #2)
- No trades placed, no errors that break the bot

## Recovery steps (for next session)

1. Apply fix 2b to `backend/core/edge/registry.py` (~3 line edits)
2. Apply fix #1 to `backend/core/edge/calibration_tracker.py` (1 line move)
3. Run: `python -c "from backend.strategies.apex_strategy import APEXStrategy; print(APEXStrategy)"` to verify imports
4. `pm2 restart polyedge-orchestrator`
5. Watch `pm2 logs polyedge-orchestrator` — look for `[apex] Cycle complete: X edges, Y decisions` instead of `Scanner X failed:`
6. After 24-48h, query trade stats:
   ```sql
   SELECT strategy, COUNT(*), AVG(pnl), SUM(pnl)
   FROM trades WHERE strategy='apex' AND trading_mode='paper'
   GROUP BY strategy;
   ```
7. **DO NOT enable live trading** until paper shows >= 50 trades with positive Sharpe

## Files touched in this session

- `backend/strategies/__init__.py` — added `APEXStrategy` import (so it auto-registers)
- `scripts/enable_apex_paper.py` — created (idempotent DB enable script)
- DB: `StrategyConfig` row for apex (id auto, mode=paper, interval=120, enabled=true)

## Files NOT modified (per session constraint)

- `backend/core/edge/calibration_tracker.py` — bug #1 fix deferred
- `backend/core/edge/registry.py` — bug #2 fix deferred
- `backend/core/edge/scanners/*.py` — bug #2 fix deferred
- `backend/strategies/apex_strategy.py` — bug #3 deferred
- `backend/core/scheduling/scheduling_strategies.py` — bug #4 deferred

---

## Resolution update — 2026-06-11

All four bugs above are fixed and deployed (orchestrator restarted):

| Bug | Fix | Commit |
|-----|-----|--------|
| #1 calibration `Trade` import | moved out of TYPE_CHECKING | `746a00e0` |
| #2 scanner/ABC interface mismatch | registry calls `scan(ctx)` | `746a00e0` |
| #4 paper strategy ran in live+paper | dispatch respects `StrategyConfig.mode` | `746a00e0` |
| order_book_stale never ran | ctx.clob was always None; scanner used dict API on OrderBook and wrong Gamma field (`clobTokenIds`) | `e464d7da` |
| ExitManager exits never fired | phantom `get_midpoint` / `trade.created_at`; now async `get_mid_price` + `trade.timestamp` | `e464d7da` |

Live verification (2026-06-11): `order_book_stale` standalone run against
real CLOB found **14 edges**. APEX paper cycles now have a working scanner →
pipeline → decision path; next checkpoint is trade accumulation per the
gating pipeline (PAPER ≥ 20 verified trades).
