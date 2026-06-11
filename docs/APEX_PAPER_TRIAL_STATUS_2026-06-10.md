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

---

## Resolution update — 2026-06-11 (part 2): edge_pp unit mismatch

After the part-1 fixes were deployed, live PM2 logs showed the APEX pipeline
filtering every edge to zero signals:

```
[apex:pipeline] 15 edges → 0 signals (bankroll=$100.00)
```

**Root cause:** `Edge.edge_pp` is documented and consumed as **percentage
points (0-100 scale)** — `APEX_MIN_EDGE_PP=2.0` and
`risk_manager.evaluate_apex_signal` both compare against the pp scale. Two
scanners computed `edge_pp` on the **0-1 probability scale** instead:

- `resolution_timing.py`: `edge_pp = round(raw_edge - 0.001, 4)` ≈ 0.01-0.03
- `order_book_stale.py`: `edge_pp = round(abs(fair_price - entry_price) - 0.002, 4)` ≈ 0.005-0.05

Both were therefore always `< APEX_MIN_EDGE_PP=2.0`, so the pipeline dropped
every edge regardless of how strong it actually was — APEX has been
producing zero trades since deployment.

**Fix:** both scanners now multiply the raw probability-scale edge by 100
(`edge_pp = round((raw_edge - fee) * 100, 2)`), and their internal minimum
thresholds were rescaled to match (`order_book_stale`: `0.005` → `0.5`).

A second, co-located bug in `resolution_timing.py`: the scanner always
bought `clobTokenIds[0]` (the YES token) regardless of which outcome
(`qualifying_index`) actually had the qualifying price, and flipped
`entry_price`/`fair_price` for "no"-direction outcomes in a way that no
longer matched the token actually purchased. Fixed to track
`qualifying_index` through to token selection (`_extract_token_id(market,
index=qualifying_index)`), and to buy the qualifying outcome's own token at
its own quoted price (`entry_price = qualifying_price`, `fair_price =
win_prob`).

Live verification (2026-06-11) after the fix:
- `order_book_stale`: 16 edges found, 16 passing `edge_pp >= 2.0`
- `resolution_timing`: 3 edges found, 1 passing `edge_pp >= 2.0`

## Dead-code sweep — 2026-06-11

Ran `ruff check --select F401,F811,F841` across `backend/core/edge/`,
`backend/core/arb_executor.py`, `backend/core/hft_executor.py`,
`backend/api/dashboard.py`, `backend/ai/ensemble.py`,
`backend/monitoring/trade_journal.py`, `backend/core/settlement/auto_redeem.py`,
`backend/clients/bnb_agent_client.py`, and `backend/data/gamma.py`. Removed
29 unused imports/variables, including a no-op `adjusted_z` computation in
`backend/core/edge/time_decay.py::BrownianBridge.probability_at_time`.

Two of these were real bugs, not just unused symbols:

- `backend/api/dashboard.py::_resolve_market_questions` had 35 lines of
  Gamma-API batch-resolve logic placed *after* an unconditional early
  `return result` — completely unreachable.
- `backend/core/hft_executor.py::HFTExecutor.execute_signal` had its
  risk-rejection block (`if not risk.get("allowed", False): ... return`)
  placed *after* an unconditional `return` inside the circuit-breaker
  check, with `risk = self._risk.validate_hft_trade(...)` computed
  afterwards but never gated on. This meant every `validate_hft_trade`
  rejection reason (confidence too low, max exposure reached, position
  limit reached, zero bankroll, window exposure cap reached) was silently
  ignored and `size = risk["size"]` (which can be `0.0` for disallowed
  trades) proceeded to execution regardless. Restructured so the risk check
  runs immediately after the circuit-breaker check and `allowed=False`
  short-circuits with a `"rejected"` execution result.

Full `backend/tests/` suite: 3371 tests, 0 failed, 0 errors after the fix
(one test, `test_integration_ensemble.py::test_combine_signals_with_all_components`,
passed unused `technical_conf`/`ai_confidence`/`orderbook_conf` kwargs that
`combine_signals` never read; updated the test call to match the trimmed
signature).

---

## Live verification — 2026-06-11/12: edge_pp fix confirmed, two new blockers found

After deploying the edge_pp pp-scale fix, PM2 logs confirmed it works:

```
[apex:pipeline] 18 edges → 5 signals (bankroll=$100.00)
```

(previously `15 edges → 0 signals`). All 5 signals were then rejected by
`_preflight_checks`, revealing two further issues:

### Bug A (fixed): `order_book_stale.py` had the same yes/no scale bug as
`resolution_timing.py`'s part-2 fix, just not yet applied here.

For `direction == "no"` edges, `entry_price`/`fair_price` were left in the
**YES token's** price scale (`mid_price`/`last_price`), while `token_id`
defaulted to the YES token. `risk_manager.check_edge` then computed
`edge_pp = (fair_price - entry_price) * 100` — mixing scales — producing
large, wrong-signed values:

```
[apex] Risk rejected will-adobe-q2-total-arr-be-above-27pt0b: Edge filter: edge_pp=-21.00 < MIN_EDGE_PP=0.0001
[apex] Risk rejected us-enacts-ai-safety-bill-before-2027: Edge filter: edge_pp=-14.50 < MIN_EDGE_PP=0.0001
```

**Fix:** for `direction == "no"`, convert to the NO token's own scale
(`entry_price = 1 - mid_price`, `fair_price = 1 - last_price`) and select
`clobTokenIds[1]` (the NO token) via new `_extract_no_token_id()`. The
scanner's own `edge_pp = round((abs(fair_price - entry_price) - 0.002) * 100, 2)`
is unchanged (abs() is invariant to the conversion). Added
`test_no_direction_uses_no_token_scale` to `test_apex_edge_detectors.py`.

### Bug B (NOT FIXED — needs a decision): paper bankroll is $0, blocking
**all** paper-mode strategies, not just APEX.

The other 3 of 5 APEX signals were rejected with:

```
[apex] Risk rejected <market>: concentration: event exposure $0.00 + $X > 100% of bankroll ($0.00)
```

`BotState(mode='paper')`: `paper_initial_bankroll=$1000`, but
`paper_bankroll=$0.00` and `bankroll=$0.00` today. `paper_pnl=-$3919.19`
across 2703 settled paper trades (5360 `Trade` rows total) spanning
2026-05-26 → 2026-06-10, i.e. the paper account lost ~4x its starting
bankroll and is floored at $0 — **this blocks every strategy in paper mode**
(100% concentration check rejects any size > $0 of $0 bankroll), which in
turn blocks the entire PAPER(≥20 trades)→FRONTTEST→SHADOW→LIVE gate.

PnL by strategy (paper, settled):

| strategy | trades | total pnl | avg pnl |
|---|---|---|---|
| cross_platform_arb | 100 | -2493.22 | -24.93 |
| crypto_oracle | 666 | -1619.22 | -2.43 |
| arb_scanner | 250 | -1247.50 | -4.99 |
| line_movement_detector | 249 | -426.60 | -1.71 |
| unified_arb | 2830 | 0.00 | 0.00 |
| news_frontrun | 7 | -2.64 | -0.38 |
| cex_pm_leadlag | 210 | -6.01 | -0.03 |
| weather_emos | 22 | +197.81 | +8.99 |
| longshot_bias | 618 | +717.46 | +1.16 |
| bond_scanner | 358 | +960.73 | +3.03 |
| (null strategy, bulk-settled) | 50 | NULL | — |

Two anomalies worth investigating before any bankroll reset, since a reset
without a root-cause fix would likely just drain again:
- `unified_arb`: 2830 trades, **every one** with `pnl == 0.0` exactly —
  looks like settlement never computes real PnL for this strategy rather
  than 2830 genuinely break-even trades.
- `cross_platform_arb`: avg **-$24.93/trade** over 100 trades — far larger
  than any other strategy's per-trade loss, for a strategy whose name
  implies low-risk arbitrage.
- 50 `Trade` rows have `strategy=NULL`, `pnl=NULL`, `size=NULL`,
  `result='loss'`, `settled=True`, all with the identical timestamp
  `2026-06-10 06:18:51` — looks like a bulk/orphan-cleanup operation, not
  organic trading.

This is a financial-state + risk/settlement question (`risk_manager.py` and
`settlement.py` are ADR-gated per `CLAUDE.md`) and needs a decision before
any fix: reset `paper_bankroll`, investigate the settlement anomalies above
first, and/or disable the worst-performing strategies per the strategy
governance table before re-funding paper.
