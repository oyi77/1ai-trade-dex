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

## Update — 2026-06-12: governance already disabled the worst offenders;
## also fixed a real `_get_bankroll()` masking bug (unrelated, pure correctness)

### Bug C (fixed): `_get_bankroll()` in `signal_pipeline.py` and
`apex_strategy.py` masked a real `$0.00` bankroll with a fallback default
via `state.paper_bankroll or <default>`. Since `0.0 or X == X` in Python,
a genuinely-bankrupt paper account silently reported `$100`/`$1000` instead
of `$0`. `signal_pipeline.py::_get_bankroll()` additionally used
`db.query(BotState).first()` with **no mode filter**, so it returned the
`live` row (`paper_bankroll=$100`) regardless of `ctx.mode` — this is the
exact source of the misleading `[apex:pipeline] ... (bankroll=$100.00)` log
line from the prior fix.

**Fix:** both functions now filter `BotState` by `ctx.mode` and use
`value if value is not None else <default>` (then floor at 0). Net effect
with the real `$0` paper bankroll: `signal_pipeline._size()` now correctly
sizes every edge to `$0` → `0.15*$0 < min_size_usd` → **0 signals** (instead
of 5 signals sized off a fake `$100`, then rejected downstream). This is the
*correct* behavior for a `$0` bankroll — it just makes Bug B's blockage
visible one stage earlier. Also removed now-dead imports
(`Edge`, `EdgeType`, `datetime`, `timezone`, `settings`) from
`apex_strategy.py` flagged by ruff. 54 apex tests + 21 bankroll/preflight
tests pass; ruff clean on both files.

### Re-investigated Bug B with `strategy_config` (not checked previously):

The 5 worst-performing strategies from the PnL table above were **already
auto-disabled** by governance on `2026-06-10 22:40:03` (before this
session started):

| strategy | enabled | mode | disabled_at |
|---|---|---|---|
| cross_platform_arb | false | paper | 2026-06-10 22:40:03 |
| crypto_oracle | false | paper | 2026-06-10 22:40:03 |
| arb_scanner | false | paper | 2026-06-10 22:40:03 |
| line_movement_detector | false | paper | 2026-06-10 22:40:03 |
| cex_pm_leadlag | false | paper | 2026-06-10 22:40:03 |
| **apex** | **true** | paper | — |
| **longshot_bias** | **true** | paper | — |

(Note: `crypto_oracle` is documented in `CLAUDE.md` as "Currently enabled in
PAPER mode" — that line is now stale; DB is authoritative per CLAUDE.md's
own strategy-governance rule.)

`unified_arb` (2830 trades, all `pnl==0.0`) has **no row** in
`strategy_config` at all — it appears to be a retired/renamed strategy that
can no longer place trades, so its `$0.00` total doesn't threaten a fresh
bankroll going forward (though the all-zero `pnl` on `result='loss'` rows
still looks like a settlement-recording bug worth a separate look someday).

**Net picture for Bug B**: the only two strategies currently enabled in
paper mode are `apex` (0 trades, two scanner bugs just fixed this session)
and `longshot_bias` (net **+$717.46 over 618 trades**, i.e. historically
profitable). The strategies that actually drained the $1000 → $0 are already
gated off. Resetting `paper_bankroll`/`bankroll` (mode='paper') to a fresh
value is therefore lower-risk than it looked on 2026-06-11.

### Resolution — 2026-06-12: paper bankroll reset to $1000

User chose to reset now. Applied directly to `BotState(mode='paper')` via a
single atomic `UPDATE`:

```sql
UPDATE bot_state
SET bankroll = 1000.00,
    paper_bankroll = 1000.00,
    paper_initial_bankroll = 4919.19
WHERE mode = 'paper';
```

`paper_pnl`/`total_pnl` (`-$3919.19`, the historical ledger total from 5360
`Trade` rows / `unified_arb`+`cross_platform_arb`+other now-disabled
strategies) were left **unchanged** — that history is preserved, not erased,
per the append-only `Trade` ledger rule.

`paper_initial_bankroll` was raised from `$1000` to `$4919.19` (i.e.
`$1000 - realized_pnl`, where `realized_pnl = -$3919.19` from
`SUM(Trade.pnl) WHERE settled AND trading_mode='paper'`, with `$0` open
exposure) so that `backend/scripts/reconcile_bot_state.py` — which derives
`paper_bankroll = paper_initial_bankroll + realized_pnl - open_exposure` —
recomputes the same `$1000` rather than re-clamping to `$0` on its next run.
This is effectively framed as "the paper account received a $3919.19
top-up to offset its historical losses, and now has $1000 in hand."

Verified: `SELECT bankroll, paper_bankroll, paper_initial_bankroll, paper_pnl,
total_pnl FROM bot_state WHERE mode='paper'` →
`1000.00 | 1000.00 | 4919.19 | -3919.19 | -3919.19` (consistent:
`paper_initial_bankroll + paper_pnl == paper_bankroll`).

Next: restart `polyedge-orchestrator` to pick up the Bug A
(`order_book_stale.py`) and Bug C (`_get_bankroll()`) fixes together with
the new `$1000` bankroll, then verify `[apex:pipeline]` produces signals
that pass `_preflight_checks` (no more `bankroll=$0.00` concentration
rejections).

## Update — 2026-06-12: Bug D investigated (not a bug), Bug E and Bug F fixed

### Bug D (not a bug) — "unsettled trade exists" rejections

After the bankroll reset, `[apex] Risk rejected <ticker>: unsettled trade
exists for <ticker>` started appearing for several markets every cycle.
Hypothesized this was orphaned positions from disabled strategies blocking
APEX via `apex_strategy._get_existing_positions()` lacking a strategy
filter.

A direct DB query disproved this: every blocked market's unsettled `Trade`
row is `strategy='apex'`'s **own** open position (IDs 25755, 25758-25761,
25764, $50 each, opened 2026-06-12 01:27-03:27). `risk_manager._has_unsettled_trade()`
(lines 1012-1043) is working exactly as designed — it prevents APEX from
doubling up on a market+direction it already holds. No code change.

This does mean APEX is effectively side-locked out of ~15 markets until
those positions exit, which made Bug E (below) critical: without working
exits, those positions can never close.

### Bug E (fixed) — `exit_manager` AttributeError on every open position

`backend/core/edge/exit_manager.py::check_position()` referenced
`trade.edge` at 4 call sites (PROFIT_TARGET, STOP_LOSS, TIME_DECAY,
EDGE_DECAY exit-signal construction). `Trade` has no `edge` column — only
`edge_at_entry`. Every call raised `AttributeError: 'Trade' object has no
attribute 'edge'`, which `check_all_positions()` caught per-trade, logged as
`[apex:exit] Error evaluating trade {id}: {e}`, and `continue`d — silently
skipping exit evaluation for **every open position, every cycle, for every
strategy**, since this code is shared (not APEX-specific).

Net effect: profit-target, stop-loss, time-decay, and edge-decay exits never
fired for any strategy. Combined with Bug D's side-lock, positions could only
ever be closed by manual intervention or eventual market settlement.

Fix: `trade.edge` → `trade.edge_at_entry` at all 4 sites.

Test fix: `test_apex_edge.py::TestExitManager._mock_trade` used an
unrestricted `MagicMock()` with **both** `t.edge = 5.0` and
`t.edge_at_entry = 5.0` set, so the bug was invisible to tests (MagicMock
auto-creates any attribute). Changed to `MagicMock(spec=Trade)` with only
`t.edge_at_entry` set — `spec=Trade` restricts attribute access to real
`Trade` columns, so a reintroduced `trade.edge` reference would now raise
`AttributeError` in tests too.

Verified: 30/30 tests pass in `test_apex_edge.py`; ruff clean. Live, after
restarting `polyedge-orchestrator` (pid 534342), `'Trade' object has no
attribute 'edge'` no longer appears across multiple cycles processing 15
open positions (previously ~10 occurrences/cycle).

### Bug F (fixed) — settlement session-poisoning + dead BotState update

Two related bugs in the paper-settlement path, both in
`backend/core/settlement/`:

**F1 — session poisoning on `OperationalError`.** Postgres is configured
with `idle_in_transaction_session_timeout=30000` (30s). `resolve_paper_trades()`
makes per-ticker HTTP calls to the Gamma API between DB statements on the
same session/transaction; if a cycle takes >30s, Postgres kills the
connection server-side, and the next statement raises
`psycopg2.OperationalError: server closed the connection unexpectedly`.
`settlement.py`'s `except Exception as e: logger.warning(...)` around
`resolve_paper_trades(db)` caught this but did **not** call `db.rollback()`,
leaving the session in an invalid-transaction state. The very next block
(paper bankroll auto-topup, `db.query(BotState)...` on the same session)
then immediately failed with `Can't reconnect until invalid transaction is
rolled back. Please rollback() fully before proceeding` — every settlement
cycle, recurring continuously from ~05:26 to 07:17+.

Fix: added `db.rollback()` to the except block (mirrors the existing
pattern at line 735 in the same file). This is a session-recovery addition,
not a relaxation/bypass of any risk or settlement check, so it does not
require a new ADR despite `settlement.py` being ADR-gated.

**F2 — dead BotState update in `resolve_paper_trades()`.** The block that
updates `BotState.paper_pnl/paper_trades/paper_wins` after a paper trade
resolves via Gamma outcome prices queried
`db.query(type("BotState", (object,), {}))` — a throwaway non-ORM class,
not the real `BotState` model. This always raised inside the `try`, was
caught and logged as `Failed to update paper bot_state`, and silently no-op'd.
Net effect: these counters never updated when paper trades settled via Gamma
outcomes (only via the CLOB-fill path). `settlement_helpers.py` is not in
CLAUDE.md's ADR-gated list (only `settlement.py` is), and this is a
correctness fix to dead code, not a change to settlement logic.

Fix: replaced with a real `from backend.models.database import BotState;
state = db.query(BotState).filter_by(mode="paper").first()`, queried once
before the loop (was previously attempted once per trade).

Added regression test `test_resolve_paper_trades_updates_botstate_counters`
in `test_settlement.py`, which mocks the Gamma response and asserts
`BotState(mode='paper').paper_pnl/paper_trades/paper_wins` update correctly
after `resolve_paper_trades()`. 25/25 tests pass in `test_settlement.py`.

**Live verification (F1):** at 07:50:54, a real
`server closed the connection unexpectedly` fired inside
`resolve_paper_trades()` (the very first query, before any trades were
processed). With the fix, the settlement job logged
`Job "settlement_job ..." executed successfully` immediately after — the
previously-constant cascading `Paper bankroll top-up failed: Can't
reconnect...` did **not** appear. F2 could not be live-verified in this same
cycle (the connection died before reaching any settled trades), but is
covered by the new unit test.

### Status

Bug D: not a bug (confirmed intentional). Bug E: fixed and verified live.
Bug F: fixed, F1 verified live, F2 verified by unit test. All changes
committed together with the existing bankroll-reset work from this trial.

## Update — 2026-06-12: Bug F3/G — second & third instances of the F1
## session-poisoning anti-pattern (settlement.py + scheduler.py)

While live-monitoring the F1/F2 fix, found the **same missing-`db.rollback()`
anti-pattern** recurring on nearly every settlement cycle (~every 2 min) for
4.5+ hours (10:09:58–14:41:58):

```
ERROR | backend.core.settlement.settlement:settle_pending_trades:812 -
Paper bankroll top-up failed: (psycopg2.OperationalError) server closed the
connection unexpectedly
```

**F3 — `settlement.py` auto-topup block (lines ~782-813).** The "Auto-topup
paper bankroll if depleted" block has two `db.commit()` calls: one for the
bankroll/`BotState` update (line 782) and a nested one for the audit-trail
`TransactionEvent` (line 806). Neither except handler called `db.rollback()`
on failure — identical to F1's root cause (Postgres
`idle_in_transaction_session_timeout=30000` killing the connection between
statements).

This is more severe than F1 because of what runs immediately after on the
**same `db` session**: the ADR-gated risk auto-disable check,
`check_risk_and_disable(db)` (`backend/core/strategy_gate.py:317`, "Risk
Layer — Auto-Disable... runs on every heartbeat" per `CLAUDE.md`). Confirmed
`check_risk_and_disable` exists and immediately calls `db.execute(text(...))`
— on a poisoned session this raises `PendingRollbackError`, caught silently
at settlement.py:829-830 as `logger.debug("Risk check failed (non-fatal)")`.
So for 4.5+ hours, the risk auto-disable check was very likely silently
no-op'ing every cycle it ran after a topup-block failure — a safety-relevant
silent failure, not just log noise.

Fix: added `db.rollback()` to both except blocks —
the outer `except Exception as e: logger.error(f"Paper bankroll top-up
failed: {e}")` (line ~812) and the inner
`except Exception as tee: logger.debug(f"TransactionEvent recording for
auto-topup failed: {tee}")` (line ~809) — mirroring the F1 fix. Same
reasoning as F1: this is session-recovery, not a relaxation of risk/settlement
logic, so no new ADR is required despite `settlement.py` being ADR-gated.

**F-G — `scheduler.py::_cleanup_stale_trades_job` (line ~941).** A related,
lower-frequency occurrence (seen twice: 13:48:14, 14:18:06):

```
WARNING | backend.core.scheduling.scheduler:_cleanup_stale_trades_job:971 -
[stale_trade_cleanup] Failed: (psycopg2.OperationalError) server closed the
connection unexpectedly
```

This job calls `await resolve_paper_trades(db)` (line 930, same Gamma-HTTP
function as F1) inside a `with get_db_session() as db:` block, caught by
`except Exception as e: logger.warning(f"[stale_trade_cleanup] Paper Gamma
resolution failed: {e}")` (line 941-942) — again, no `db.rollback()`. The
subsequent `stuck_paper` query (>5-day stuck paper trades, lines 947-969)
then raises `PendingRollbackError`, which propagates out of the
`get_db_session()` context manager (which itself rolls back and re-raises)
and surfaces as the line-971 `[stale_trade_cleanup] Failed` log — meaning the
5-day stuck-paper force-settle silently doesn't run for that cycle.

Fix: added `db.rollback()` to the line 941-942 except block, same pattern.

**Verification:** `test_settlement.py` (25/25) and the scheduler test suites
(`test_auto_redeem_scheduler.py`, `test_scheduler_agi_jobs.py`,
`test_scheduler_queue_mode.py`, 21/21) pass; `ruff check` on both files shows
only pre-existing unrelated `F841` unused-variable warnings (lines 111-112
of `settlement.py`, line 562 of `scheduler.py`, present before this change —
out of scope here). Live verification pending: restart
`polyedge-orchestrator` and confirm `Paper bankroll top-up failed` and
`[stale_trade_cleanup] Failed` no longer recur on subsequent cycles.

### Status

F3/F-G: fixed, pending live verification after restart.

**Live verification (F3/F-G):** after the 18:54:16 restart (pid 1973529,
clean startup), two settlement cycles ran (18:56:31–18:56:37 and
18:58:31–18:58:37), both logging `Job "settlement_job ..." executed
successfully` with no `Paper bankroll top-up failed` or
`[stale_trade_cleanup] Failed`. Both cycles completed in well under 1s
(19 Gamma calls in ~1.8s), far below the 30s
`idle_in_transaction_session_timeout` that triggers the underlying
`OperationalError` — so the specific triggering condition (a slow
settlement cycle) hasn't recurred yet. The fix is code-correct (identical
to the proven F1 pattern), tests pass, and `ruff` is clean; it will engage
the next time a cycle runs long, same as F1.

## Update — 2026-06-12: Bug H — `ActivityTracker failed to start: name 'os'
## is not defined` (missing `import os` in orchestrator.py)

Every orchestrator startup (confirmed across multiple restarts, including
2026-06-11 23:40:53, 2026-06-12 01:28:23, and 18:54:16) logs:

```
WARNING | backend.core.orchestrator:start:80 - ActivityTracker failed to
start: name 'os' is not defined
```

**Root cause:** `Orchestrator._register_activity_sources()`
(`backend/core/orchestrator.py:307`) reads
`os.environ.get("SKIP_ACTIVITY_SOURCES", "")` to optionally skip individual
activity sources, but `orchestrator.py` never imports the `os` module. The
`NameError` is raised on the first line of `_register_activity_sources()`,
before any activity source is registered, and is caught by the generic
`except Exception as e:` around the whole ActivityTracker startup block
(`orchestrator.py:79-81`) — so `self._activity_tracker` is set to `None` and
**no activity sources (Aster, Hyperliquid, Lighter, Polymarket, Azuro) are
ever registered**, meaning real-time fill/transfer tracking and
`ActivityHandler`'s bankroll/position updates have been silently disabled on
every run since this code path was added.

Fix: added `import os` to `orchestrator.py`'s import block (alongside
`asyncio`/`signal`). One-line fix; `SKIP_ACTIVITY_SOURCES` was a pre-existing
but previously-unreachable env var, now documented in `.env.example`.

**Verification:** `pytest backend/tests/test_orchestrator_wiring.py
backend/tests/test_activity_integration.py backend/tests/test_activity_live.py`
— 82/82 pass. `ruff check backend/core/orchestrator.py` — clean. Live
verification pending: restart `polyedge-orchestrator` and confirm
`ActivityTracker started` replaces the `name 'os' is not defined` warning.

**Live verification (Bug H):** after restarting `polyedge-orchestrator`
(pid 2000601, 19:05:23), `ActivityTracker failed to start: name 'os' is not
defined` (which had fired on every prior startup, e.g. 2026-06-11 23:40:53,
2026-06-12 01:28:23, 07:46:43, 18:54:16) no longer appears. Instead:
`ActivityTracker started`, and 7 sources registered successfully —
`polymarket`, `azuro`, `kalshi`, `ostium`, `myriad`, `sxbet`, `paper`.

This also surfaced 3 **pre-existing** issues that were previously invisible
(masked because no activity source ever attempted to register before):

1. `Aster activity source skipped: 'AsterProvider' object has no attribute
   'connect'` / same for Hyperliquid and Lighter — `_register_activity_sources()`
   calls `await <provider>.connect()`, but `AsterProvider`/`HyperliquidProvider`/
   `LighterProvider` (`BaseMarketProvider` subclasses) have no `connect()` and
   their `__init__` already does all needed setup synchronously. Additionally,
   the activity-source classes (`AsterActivitySource`, `HyperliquidActivitySource`,
   `LighterActivitySource`) expect client methods (`watch_balance`/`get_fills`/
   `watch_positions`, `subscribe_user_fills`/`subscribe_order_updates`,
   `subscribe`/`recv`/`get_balance`) that don't all exist on these provider
   classes either — a deeper interface mismatch than a one-line fix. Deferred:
   needs a scoped design pass per activity source, not attempted here.

2. `[polymarket] WS fills error, falling back to REST:
   PolymarketWebSocket.__init__() got an unexpected keyword argument
   'ws_config'. Did you mean 'config'?` — `polymarket_source.py:75` calls
   `PolymarketWebSocket(ws_config={"url": ..., "channel": ...})`, but the
   constructor takes a single positional `config: WebSocketConfig` dataclass
   (no `url` field — the endpoint is resolved internally from
   `ChannelType` via `PolymarketWebSocket.ENDPOINTS`). Separately,
   `PolymarketWebSocket.connect()` itself runs its own internal
   reconnect-until-exhausted loop and only returns when retries are
   exhausted, so `await ws.connect()` in `_connect_ws_fills()` would block
   rather than return after a successful connect — the "keep alive" loop
   below it is currently unreachable. REST fallback
   (`_rest_fills_loop`, using `self._clob.get_trader_trades()`) works and is
   what's actually running. Deferred: needs both the constructor-arg fix and
   a rework of how `_connect_ws_fills` awaits `connect()` (e.g. run as a
   background task), plus sourcing `condition_ids`/API creds for the
   authenticated USER channel.

3. `Lighter REST balance error: 'AccountApi' object has no attribute
   'assets'` (`balance_aggregator.py:162`, **10,014 occurrences** in the log
   history, firing every ~15s) — `LighterClient.get_balance()` called
   `self._account_api.assets(...)`, but the installed `lighter` SDK's
   `AccountApi` has no `assets`/`order_books`/`positions`/
   `account_active_orders`/`info` methods (SDK version mismatch). FIXED here:
   rewrote `get_balance()` to use `account_api.account(by="index",
   value=str(account_index))` and extract the `USDC`-symbol entry's
   `.balance`, mirroring the already-correct, already-tested
   `LighterProvider.get_balance()` (`backend/markets/providers/lighter_provider.py:103-124`,
   covered by `test_lighter_provider.py::test_get_balance_list_format` /
   `test_get_balance_dict_format`). New test file
   `backend/tests/test_lighter_client.py` (3 tests) covers the USDC-found,
   USDC-missing, and empty-accounts cases. `LighterClient.get_markets()`
   (`order_books`), `get_positions()` (`positions`), `get_active_orders()`
   (`account_active_orders`), and `health_check()` (`info()`) have the same
   SDK-mismatch bug but are not in the active polling hot path causing log
   spam — deferred, same root cause, separate fix.

**Verification (Lighter `get_balance` fix):** `pytest
backend/tests/test_lighter_client.py backend/tests/test_lighter_provider.py`
— 15/15 pass. `ruff check backend/clients/lighter_client.py
backend/tests/test_lighter_client.py` — clean.

**Live verification:** after restarting `polyedge-orchestrator` (pid
2094015, 19:44:34), `ActivityTracker started` fires again with 7 sources
registered (Bug H still fixed). The `AttributeError: 'AccountApi' object has
no attribute 'assets'` is **gone** — `_ws_lighter` now reaches the real
`account_api.account(by="index", value=...)` HTTP call. However, that call
now returns `Lighter REST balance error: (403)` every ~15s (17 occurrences
in the first ~90s). This is a **new, different, pre-existing** issue: an
HTTP 403 from the Lighter API on the `account()` endpoint despite
`LIGHTER_PRIVATE_KEY`/`LIGHTER_ACCOUNT_INDEX`/`LIGHTER_API_KEY_INDEX` all
being set in `.env` — likely the unauthenticated `ApiClient`/`Configuration`
used by `_ensure_initialized()` doesn't attach the API-key auth headers that
`account()` requires (auth is currently only wired up in `_ensure_signer()`,
which is for trade-signing, not read endpoints). This affects
`LighterProvider.get_balance()` too (same SDK call) — i.e. Lighter balance
reads are likely 403'ing in the live trading path as well, not just this
poller. Deferred: needs investigation into the `lighter` SDK's expected auth
mechanism for read endpoints (API-key header vs query param vs signed
request).

### Status

F3/F-G: fixed and live-verified (no recurrence observed, see above). Bug H:
fixed and live-verified (`ActivityTracker started`, 7 sources registered,
both restarts). Bug I (`AccountApi.assets` AttributeError): fixed and
live-verified — error message changed from the AttributeError to a 403,
confirming the SDK call path is now correct; the 403 itself is a new,
separate, pre-existing auth-configuration gap (see above). Four pre-existing
gaps discovered and documented above (Lighter API 403/auth for read
endpoints; Aster/Hyperliquid/Lighter activity-source interface mismatch;
Polymarket WS `ws_config`/blocking-connect bug; remaining `LighterClient`
SDK-mismatch methods) — all deferred as out-of-scope for this session.

## Update — 2026-06-12: Bug J — `order_book_stale` scanner's edge thesis was
## inverted, root cause of `apex`'s 16.7% WR / -$20.64 (all 34 paper trades)

After re-enabling `apex` (paper) ~2h ago, all 34 trades placed so far came
from a single edge type — `order_book_stale` — and every one of them had
`confidence` exactly `0.70` (6 settled: 1 win, 5 losses, -$20.64, 16.7% WR).
Confidence being pinned at *exactly* the same value across wildly different
categories (esports, weather, politics, commodities) for 100% of trades was
the tell.

**Root cause (`backend/core/edge/scanners/order_book_stale.py`):** the
scanner compares the CLOB's live `/last-trade-price` to the current
order-book mid-price and, if they diverge by `>= min_divergence_pp` (2pp),
treats the *last trade price* as "fair value" and the *current mid-price* as
the stale, not-yet-caught-up entry price — i.e. it bets the market will
revert toward whatever price the last fill happened at.

`/last-trade-price` carries no timestamp, and the constructor already
defined (but never used) `min_volume` and `max_age_seconds` config knobs —
strong evidence the original intent was "only treat this as *order-book*
staleness if the *last trade* was recent and the market is liquid enough
that a fresh fill is meaningful." Without that check, the scanner fires on
*any* market where trading has been infrequent: the "last trade" can be
hours/days old while the current bid/ask mid is the actually-current,
informed price. In that case the thesis is backwards — there is no reason
for price to revert toward an old fill, and `confidence = min(divergence /
0.10, 0.7)` was saturating at its 0.7 cap on essentially every signal,
because real "the order book hasn't updated yet" gaps are small (a few pp)
while "the last trade is just old" gaps are large (we observed 13.5pp and
18.5pp divergences on top-100-by-volume markets — decision_log
`will-the-democratic-party-win-the-ny-21-house-seat` edge=13.30%,
`will-valve-add-first-cs2-operation-by-june-30-2026-962` edge=18.30%, both
conf=0.70). The high, saturated confidence meant `min_confidence` filters
(0.3 in the pipeline, 0.5 in `apex_strategy`) never screened these out.

**Fix:** wired in the previously-dead `min_volume` filter (`APEX_STALE_MIN_VOLUME`,
default 500 — thin markets trade rarely, so a stale "last trade" is the norm,
not a signal) and added a new upper bound `max_divergence_pp`
(`APEX_STALE_MAX_DIVERGENCE_PP`, default 0.06): divergences above this are
now skipped rather than treated as high-confidence edges, since a gap that
large almost always means the *last trade* — not the order book — is the
stale data point. This also means confidence (`min(divergence/0.10, 0.7)`)
can no longer reach its 0.7 cap, restoring it as a meaningful filter signal.
Both new config vars documented in `.env.example`.

**Verification:** `pytest backend/tests/test_apex_edge_detectors.py` — 20/20
pass (added `test_skips_excessive_divergence` and `test_skips_low_volume` for
`OrderBookStaleScanner`; updated `test_detects_stale_divergence` and
`test_no_direction_uses_no_token_scale` to use realistic in-bounds
divergences). Full apex/edge suite (`test_apex_edge.py`,
`test_apex_strategy.py`, `test_apex_calibration.py`,
`core/edge/tests/test_time_decay.py`, plus all `apex|edge|stale`-matching
tests across `backend/tests/`) — 321/321 pass.

**Expected live effect:** `order_book_stale` found 20-21 "edges" every ~2min
cycle pre-fix (out of ~24 total across all 3 scanners); post-fix this should
drop sharply (most of those 20 had >6pp divergence on markets that, while
in the top-100-by-volume, may still trade infrequently). `apex` will lean
more on `resolution_timing` (4 edges/cycle, same structural thesis as
`bond_scanner` which has a 70.4% WR / +$1065.73 track record over 358 paper
trades) and `liquidity_gap` (0 edges/cycle so far). To be confirmed after
restart by watching `[apex:order_book_stale] Found N stale order book edges`
and whether any new `apex` trades still show `conf=0.70` exactly.

### Status

Bug J: fixed, tested (321/321), documented, **live-verified**. After
restarting `polyedge-orchestrator`, `[apex:order_book_stale] Found 7 stale
order book edges` (down from 20-21 pre-fix). The two new `order_book_stale`
decisions post-restart are `conf=0.55` (edge=5.30%,
`will-the-democratic-party-win-the-ny-21-house-seat`) and `conf=0.58`
(edge=5.60%, `donald-trump-of-truth-social-posts-june-9-june-16-100-119`,
which executed as a $50 paper trade) — both within the new ≤6pp divergence
bound and no longer pinned at the 0.7 cap. `resolution_timing` decisions
(`conf=0.90`, `conf=0.94`) are unaffected. Remaining `conf=0.70` rows in
`decision_log` are pre-fix history.

## Update — 2026-06-12: Bug K — `longshot_bias` candidate-direction bug,
## 100% `GUARD blocked`, zero decisions every cycle since re-enable

### Root cause

`longshot_bias` (`backend/strategies/longshot_bias.py`) was re-enabled in the
DB on 2026-06-10 (300s interval, PAPER mode), with a track record of 618
historical trades / 97.9% WR / +$717.46. Since re-enable it produced **zero**
decisions every cycle — every candidate hit `[longshot_bias] GUARD blocked:
{slug} no_price={no_price:.3f} > max={max_entry_price:.3f}`.

The candidate filter selected `0 < yes_price < max_price (0.25)`, which
implies `no_price > 0.75` for every candidate. The very next guard rejected
any candidate with `no_price > max_entry_price (0.30)` — a condition that is
**always true** given the candidate filter (`no_price > 0.75 > 0.30`
unconditionally). This is a self-contradictory pair of filters: nothing could
ever pass.

This also contradicted the strategy's own docstring/description ("buy NO
tokens on markets priced below 30c where empirical EV is +23%") and the
`compute_longshot_bias_from_trades(price_threshold=max_price, ...)` call,
which only matches settled `Trade.entry_price < max_price` — i.e. it assumes
`entry_price` (= `no_price` for this strategy's BUY decisions) is itself
`< max_price`. The candidate filter selecting `yes_price < max_price` (giving
`no_price > 0.75`) could never produce such trades.

A second, latent issue was found in the same pass: `true_win_prob = 1.0 -
yes_price * bias_ratio` (used for Kelly sizing and, after this fix, for the
`min_model_prob`/`min_edge` guards via `model_prob = yes_price`) only stays
positive while `bias_ratio < 1 / yes_price`. The fallback `bias_ratio = 0.59`
is safe, but once `compute_longshot_bias_from_trades()` starts returning a
ratio computed from real settled trades — `bias = win_rate / avg(entry_price)`,
and `avg(entry_price) < 0.25` by construction for this strategy — `bias_ratio`
will very likely exceed `1.0`, driving `true_win_prob` negative for
`yes_price` close to 1 and silently zeroing out the strategy again (via the
`true_win_prob <= 0: continue` guard) once enough trades settle.

### Fix

`backend/strategies/longshot_bias.py`:
- `market_filter()` and the `candidates = [...]` comprehension now select
  `0 < no_price < max_price` (was `yes_price`) — matching the docstring
  ("buy NO tokens... priced below 30c") and the bias-detector's
  `price_threshold` semantics.
- `model_prob` (used by the `min_model_prob` and `min_edge` guards) changed
  from `1.0 - yes_price` to `yes_price` — under the corrected candidate
  direction (`no_price < max_price` → `yes_price > 1 - max_price`),
  `model_prob = yes_price` represents "market-implied confidence in the
  favorite", which is `>= min_model_prob (0.75)` for in-range candidates and
  makes `edge = model_prob - no_price` a genuine (large, positive) lopsidedness
  measure rather than ~0 for complementary prices.
- `bias_ratio` is now clamped to `[0.1, 0.95]` after the
  `compute_longshot_bias_from_trades()` call, so `true_win_prob = 1 -
  yes_price * bias_ratio` stays positive for any `yes_price` up to 1.0 —
  preventing the latent future-shutdown described above.

### Verification

- `pytest backend/tests/test_longshot_bias.py
  backend/tests/test_bankroll_allocator_longshot.py
  backend/tests/test_strategy_executor.py backend/tests/test_strategy_gate.py
  backend/tests/test_bankroll_allocator.py`: 62 passed, 3 skipped.
- Dry-run of `run_cycle()` against live Gamma data (paper mode, $1000
  bankroll, no DB): **5 decisions** produced (previously 0), e.g.
  `will-the-democratic-party-win-the-pa-03-house-seat` BUY NO @ 0.055,
  edge=0.89, confidence=0.4425, size=$10 (capped at `max_position_usd`).
  All 5 candidates had `no_price` in [0.004, 0.175], `yes_price >= 0.825 >=
  min_model_prob (0.75)`, and `edge >= 0.65 >= min_edge (0.15)`.
- Live verification (post-restart `decision_log`/`trades` check) pending.

### Status

Bug K: fixed, tested (62 passed / 3 skipped), documented, and **live-verified**.
After `pm2 restart polyedge-orchestrator`, the first cycle logged `Found 10
markets below 15c (bias=0.5900)` and produced 10 BUY-NO decisions/cycle
(`decisions=10` vs. 0 before the fix) — e.g.
`bitcoin-above-60k-on-june-18-2026 NO @ 12.50c | edge: 75.0% | EV: 35.4% |
Kelly: 6.2% | $6.15`. The candidate-direction bug is resolved.

However, all 10 decisions were then rejected by
`strategy_executor._preflight_checks` →
`risk_manager.validate_trade()` with `"Risk rejected {slug}: confidence
0.41-0.47 < min threshold 0.50"`, so **zero trades were placed** even in
paper mode. This is a *separate* bug — see Bug L below — now fixed.

## Update — 2026-06-12: Bug L — `LONGSHOT_NO_BIAS_WEIGHT` dead since
## introduction; `longshot_bias` 100% risk-rejected on `confidence < 0.50`

### Root cause

After the Bug K fix, `longshot_bias` produced 10 BUY-NO decisions/cycle, each
with `confidence = true_win_prob = 1 - yes_price * bias_ratio` in the
**0.41-0.48** range (e.g. `confidence=0.41` for a NO @ 0.45c with
`yes_price=0.9955`, `bias_ratio=0.59`). `_preflight_checks` →
`risk_manager.validate_trade()` rejects any trade with `confidence <
min_confidence` (`PAPER_AUTO_APPROVE_MIN_CONFIDENCE = 0.50`). All 10/10
decisions were rejected with `"confidence 0.4X < min threshold 0.50"` —
`PARALLEL: executed 0 trades in paper mode (input decisions: 10)`.

This is **by design** for `longshot_bias` — it bets on the longshot (NO) at
5-15c where `P(NO wins)` is genuinely < 0.50; the edge comes from payout odds
(`edge = model_prob - no_price` = 65-99%, `EV` = 35-41%), not from
`P(win) > 0.5`. The 0.50 confidence floor is a sanity check appropriate for
favorite-betting strategies but structurally excludes any true longshot
strategy.

`risk_manager.py` already has a mechanism for exactly this:
`LONGSHOT_NO_BIAS_WEIGHT` (default 0.10, added in commit `a23a8b31`, "NO-bias
weighting") boosts `confidence` for `direction == "NO"` trades by
`confidence * (1 + bias_weight)` before evaluation. But since that commit it
has been applied **after** the `confidence < min_confidence` rejection
(`backend/core/risk/risk_manager.py` — the check at the old line ~426 ran
before the adjustment at the old line ~440) — every NO trade was rejected
before the boost could run. `LONGSHOT_NO_BIAS_WEIGHT` has been dead code for
its intended purpose since it was introduced.

### Fix

`backend/core/risk/risk_manager.py::validate_trade()`: moved the
`LONGSHOT_NO_BIAS_WEIGHT` / category-direction adjustment block to run
**before** the `confidence < min_confidence` floor check, so the adjustment
actually affects the gating decision. No other risk check (MIN_TRADE_EV,
check_edge, drawdown, exposure, concentration, category edge) was changed —
all continue to run as before. Documented in
`docs/architecture/adr-015-longshot-no-bias-confidence-ordering.md` per the
ADR-gating rule for `risk_manager.py`.

With the default `bias_weight=0.10`, a NO trade now passes the floor if
`confidence >= 0.50 / 1.10 ≈ 0.4546`. Of the 10 candidates observed
pre-restart (`confidence` 0.41-0.48), an estimated **3/10** would clear the
floor (`bitcoin-above-60k-on-june-18-2026` 0.484→0.532,
`aligned-fdv-above-20m-one-day-after-launch` 0.473→0.521,
`will-nike-q4-greater-china-revenue-be-above-1pt0b` 0.472→0.519). This
estimate is superseded by the live results below — the market set shifted to
12 candidates by the time of the actual post-restart cycle.

### Verification

- New tests in `backend/tests/test_risk_manager.py`
  (`TestLongshotNoBiasOrdering`, 3 tests): a NO trade at `confidence=0.46`
  is rejected with `bias_weight=0.0` and allowed with `bias_weight=0.10`
  (boosted to 0.506); a YES trade at `confidence=0.52` is correctly rejected
  once the symmetric penalty (`*0.95 = 0.494`) is applied before the floor.
- `pytest backend/tests/test_risk_manager.py
  backend/tests/test_risk_profiles.py backend/tests/test_strategy_executor.py
  backend/tests/test_strategy_gate.py backend/tests/test_longshot_bias.py
  backend/tests/test_bankroll_allocator.py
  backend/tests/test_bankroll_allocator_longshot.py`: 112 passed, 3 skipped.
- **Live verification** (`pm2 restart polyedge-orchestrator`, pid `2549192`,
  restart #12): the first post-fix cycle (22:43-22:43:54) found 12 candidates
  (market set shifted vs. the pre-restart 10). One candidate —
  `aligned-fdv-above-20m-one-day-after-launch` NO @ 10.20c, raw
  `confidence=0.4702`, `edge=79.6%` — was boosted via
  `"[risk_manager] Applied NO-bias: no -> 0.47 -> 0.52"` (0.4702 × 1.10 =
  0.5172), cleared the 0.50 floor, and was **executed as a paper trade**:
  `trades.id=25796`, `direction=no`, `entry_price=fill_price=0.0973` (after
  4.59% slippage from the 0.102 quote), `size=$6.15`, `fee=$0.0018`,
  `trading_mode=paper`, `settled=false`. Log:
  `"[longshot_bias] PARALLEL: executed 1 trades in paper mode (input
  decisions: 12)"` — **the first confirmed paper-trade execution by
  `longshot_bias` since Bug K was fixed**.
- Of the other 11 candidates, the risk-gate outcome was directly observed for
  5: `will-spacex-raise-between-70b-and-80b-in-its-ipo` (0.41→0.45),
  `isl1-kef-haf-2026-06-14-total-0pt5` (0.44→0.48),
  `dota2-nawedw-the-2026-06-11-game-handicap-home-1pt5` (0.41→0.45),
  `nathan-ngoy-20260609173850418` (0.45→0.49), and
  `marquinhos-20260609165807832` (0.42→0.46) — all still rejected
  (`confidence < 0.50` after boosting), consistent with the "candidates below
  ~0.4546 stay rejected" expectation.
- The next cycle (22:44:03-22:44:54) re-evaluated the same 12 candidates:
  `aligned-fdv-above-20m-one-day-after-launch` was again boosted to 0.52
  (clears the floor) but correctly rejected by the pre-existing
  duplicate-position guard (`"Risk rejected
  aligned-fdv-above-20m-one-day-after-launch: unsettled trade exists for
  aligned-fdv-above-20m-one-day-after-launch"`), since `trades.id=25796` was
  still open. `"PARALLEL: executed 0 trades in paper mode (input decisions:
  12)"` — confirms the fix does not cause repeat-buys of the same market
  every cycle.

### Status

Bug L: fixed, tested (112 passed / 3 skipped), documented (ADR-015), and
**live-verified**. `longshot_bias` placed its first paper trade in this
investigation (`trades.id=25796`, NO `aligned-fdv-above-20m-one-day-after-launch`
@ 9.73c fill, $6.15, `confidence` 0.47→0.52 after the NO-bias boost,
`edge=79.6%`). Combined with the Bug K fix, `longshot_bias` is now confirmed
working end-to-end in paper mode: candidate selection → risk-gate pass →
paper execution → duplicate-entry guard on subsequent cycles. PnL/win-rate
validation requires these positions to settle (multi-day/week horizon for
most of these markets) — not yet measurable.

## Update — 2026-06-13: Bug M — `force_closed_unresolved` paper trades
## record `pnl=0.0` despite `result="loss"`, hiding ~$14k of real losses

### Root cause

Investigating `unified_arb` (paper, DISABLED): all 2,830 settled trades have
`result='loss'`, `settlement_source='force_closed_unresolved'`, and
**`pnl=0.0` for every single row** (`sum(pnl)=0.00`). These are YES
positions at avg `entry_price≈0.4950`, `size=10` shares — total cost basis
**$14,009.18** — that should be recorded as a loss of roughly that amount,
not $0.

`backend/core/scheduling/scheduler.py::_cleanup_stale_trades_job`
force-settles paper trades stuck at `settled=True, pnl=NULL` for >5 days
(Gamma never resolved them — these `KXMVESPORTSMULTIGAMEEXTENDED-*` tickers
look like malformed/foreign market identifiers Gamma can't match). Since
commit `e0bd9e1aa` (2026-06-03, "force-settle paper trades >5d old with
PnL=0 (neutral)"), this block hardcodes `t.pnl = 0.0` while also setting
`t.result = "loss"` — a self-contradiction: a "loss" with zero PnL impact.

Same bug also affects `bond_scanner` (paper, ACTIVE, the strategy whose
"+$18,711 / 39.6% WR" is the headline profitability number in
`backend/strategies/AGENTS.md`): 66 of its settled trades hit this path with
`pnl=0.0`, representing ~$42.30 of unrecorded loss.

### Fix

`backend/core/settlement/settlement_helpers.py`: added
`total_loss_settlement_value(direction)` — returns the `settlement_value`
that makes `calculate_pnl()` return `-cost_basis` for a given direction
(`0.0` for yes/up/buy, `1.0` for no/down/sell — the value that makes *that*
side of the bet worthless, not the value that happens to equal 0).

`backend/core/scheduling/scheduler.py::_cleanup_stale_trades_job`: replaced
`t.pnl = 0.0` with
`t.pnl = calculate_pnl(t, total_loss_settlement_value(t.direction))`, so
`force_closed_unresolved` trades now record a real negative PnL consistent
with `result="loss"`. Documented in
`docs/architecture/adr-016-force-closed-unresolved-pnl.md` per the
ADR-gating rule for settlement logic.

Historical backfill of the existing 2,830 (`unified_arb`) + 66
(`bond_scanner`) zero-pnl rows is deferred (ADR-016, Alternative 3) — this
fix stops the bleeding for newly force-closed trades but does not retroactively
correct the ~$14,051 already missing from historical paper PnL totals.

### Verification

- New tests in `backend/tests/test_settlement.py`
  (`TestForceClosedUnresolvedPnl`, 4 tests): `total_loss_settlement_value`
  returns 0.0 for yes/up/buy and 1.0 for no/down/sell; a YES position at
  entry 0.4944/size 10 force-closed as loss now yields `pnl≈-4.94` (not 0);
  a NO position at entry 0.0658/size 5 yields `pnl≈-0.33` (not 0).
- `pytest backend/tests/test_settlement.py backend/tests/test_integration_settlement_fills.py`:
  43 passed. `pytest backend/tests/test_scheduler_agi_jobs.py
  backend/tests/test_scheduler_queue_mode.py
  backend/tests/test_auto_redeem_scheduler.py`: 21 passed.

### Status

Bug M: fixed (forward-going), tested, documented (ADR-016). Historical
backfill of the ~$14,051 already-recorded-as-$0 losses (`unified_arb`
$14,009.18 + `bond_scanner` $42.30) is a deferred follow-up — see ADR-016
Alternative 3. Live verification requires waiting for the next paper trade
to hit the 5-day `force_closed_unresolved` path (not immediately observable).

## Update — 2026-06-13: Bug N — APEX (and other strategies) double-bet on
## markets stuck in the `settled=True, pnl IS NULL` limbo window

### Root cause

`_cleanup_stale_trades_job`'s `stale_paper` branch (scheduler.py:899-922)
marks any paper trade unsettled for >12h as `settled=True, pnl=None,
result="pending"` and immediately attempts `resolve_paper_trades(db)`. When
Gamma hasn't resolved the market yet (common — most markets take days), the
trade stays in this `settled=True, pnl IS NULL` limbo for up to 5 days,
until Bug M's `stuck_paper` branch force-closes it.

Every "is this position still open" guard in the codebase checked only
`Trade.settled.is_(False)`, so during this limbo window the position looked
"closed" to:

- `apex_strategy.py::_get_existing_positions` — which was *also* completely
  unwired (never called from `run_cycle`), so even fully-open positions
  weren't being checked.
- `strategy_executor.py`'s cross-strategy "Duplicate execution block"
  (~line 1308) — `Trade.settled.is_(False)` filter let a second strategy
  open a position in the same market while the first strategy's position
  was still financially live.

Net effect, confirmed via `GROUP BY market_ticker HAVING count(*) > 1` on
apex's paper trades: 11 markets had duplicate apex trades (43 total trades
across ~22 unique markets), one of which
(`wti-closes-above-87-on-june-11-2026`) is a legitimate already-resolved
re-entry — the other ~9-10 are apex silently doubling its exposure (and
breaking its Kelly sizing assumptions) on markets it already held, directly
violating the `backend/core/AGENTS.md` "Stale positions block orders"
invariant.

### Fix

`backend/strategies/apex_strategy.py`:
- `_get_existing_positions` now filters
  `Trade.strategy == self.name, Trade.trading_mode == ctx.mode,
  or_(Trade.settled.is_(False), Trade.pnl.is_(None))` — treating ADR-016
  limbo trades as still-open.
- Wired into `run_cycle` Phase 4: signals whose `market_id` is already held
  are skipped before `_signal_to_decision`, so apex no longer generates a
  second BUY decision for a market it's already in.

`backend/core/strategy_executor.py`: `_preflight_checks` has TWO
near-duplicate cross-strategy guards on the same `market_ticker`: check #2
("Duplicate execution block", ~line 1311, scoped by `event_slug` when
present) and check #11 ("Per-market position cap", ~line 1611, no
`event_slug` scoping — the fallback for `event_slug` mismatches/NULLs).
Both changed from `Trade.settled.is_(False)` to
`or_(Trade.settled.is_(False), Trade.pnl.is_(None))` (added `or_` to the
sqlalchemy import), so the `BLOCKED_DUPLICATE_OPEN_POSITION` /
`REJECTED_POSITION_CAP` guards now cover the limbo window for every
strategy, not just apex.

### Verification

New tests in `backend/tests/test_apex_strategy.py`:
`test_get_existing_positions_includes_unresolved_settled` (asserts a
`settled=True, pnl=None` trade counts as held, a fully-resolved
`settled=True, pnl=5.0` trade does not, and other strategies'/other modes'
trades are excluded) and `test_run_cycle_skips_existing_positions` (a full
`run_cycle` with mocked scanners/pipeline confirms a signal for an
already-held market is dropped while a signal for a new market proceeds).

New tests in `backend/tests/test_strategy_executor.py`
(`TestDuplicateExecutionBlock`, 3 tests): a `settled=True, pnl=None` trade by
another strategy now blocks (`BLOCKED_DUPLICATE_OPEN_POSITION`); a fully
resolved (`settled=True, pnl=5.0`) trade by another strategy does not block;
a limbo trade with an `event_slug` mismatch (bypasses check #2) is caught by
check #11 (`REJECTED_POSITION_CAP`).

`pytest backend/tests/test_strategy_executor.py backend/tests/test_apex_strategy.py
backend/tests/test_settlement.py`: 57 passed, 3 skipped.

### Status

Bug N: fixed, tested. No historical backfill needed — the ~9-10 existing
duplicate positions will resolve normally (each leg settles independently
against its own entry price); this fix only prevents *new* duplicates going
forward. Live verification requires observing that apex's next cycle does
not re-enter any of its currently-held (including limbo) markets.

## Update — 2026-06-13: Bug O — APEX's own exits (profit target / stop loss /
## time decay) never closed a position; `pnl_pct` was direction-inverted

### Root cause

`apex_strategy.py::run_cycle` Phase 1 calls `_check_exits`, which uses
`ExitManager.check_all_positions` to evaluate every open `apex` position
against `profit_target_pct=2.5%`, `stop_loss_pct=4%`,
`max_hold_seconds=7200`, and edge decay. When a signal fired, Phase 1 only
appended a `{"market_ticker":..., "decision": "SELL", "exit_reason":...}`
dict to `result.decisions` — no `token_id` key. Both consumers of
`decisions` drop dicts shaped like this:
`scheduling_strategies.py`'s buy-decision filter (`decision in ("BUY",
"QUOTE")`) and the shadow-runner loop (`decision.get("token_id")`). **No
position was ever closed by APEX's own exit logic.** A grep across
`strategy_executor.py` confirmed there is no `decision.get("side") ==
"SELL"` / close handling anywhere; the only other "SELL"-producing path
(`position_monitor.py::sell_signal_monitor_job`) opens a new *opposite*
position (a hedge) rather than closing the original, and its
`STOP_LOSS_DROP_PP=0.15` (15 percentage points) threshold is far looser than
apex's actual losses anyway (-16% to -50% `pnl_pct`, i.e. 0.02-0.05
probability points). Net effect: every APEX position ran to full Gamma
settlement regardless of profit-target/stop-loss — APEX had no working risk
exit in either paper or (would-be) live mode.

Separately, `ExitManager.check_position`'s `pnl_pct` branched on
`trade.direction`:

```python
if direction in ("yes", "up"):
    pnl_pct = (current_price - entry_price) / entry_price
else:
    pnl_pct = (entry_price - current_price) / entry_price
```

All three APEX scanners record `entry_price` as the price of the *held
token* (`trade.token_id`) at entry, and `_get_current_price` fetches the mid
price of that same token — both prices are already in held-token terms, so
the `else` branch inverted `pnl_pct` for every `no`/`down` position (a
losing NO position read as a gain, and vice versa), corrupting both the
profit-target and stop-loss checks for non-YES positions.

### Fix

- `backend/core/edge/exit_manager.py`: removed the `direction` branch —
  `pnl_pct = (current_price - entry_price) / entry_price` unconditionally
  (direction-independent by construction, per the entry-price convention
  above).
- `backend/core/settlement/settlement_helpers.py`: new
  `calculate_exit_pnl(trade, exit_price) -> (pnl, fee)` — a **partial**
  realization at a continuous price (`pnl = shares * (exit_price -
  entry_price) - entry_fee - exit_fee`), distinct from `calculate_pnl`'s
  binary `settlement_value ∈ {0.0, 1.0}`. Adds a new exit-leg taker fee (an
  early exit requires a real CLOB sell order, unlike binary redemption).
- `backend/strategies/apex_strategy.py`:
  - `_check_exits` now uses the ADR-016
    `or_(Trade.settled.is_(False), Trade.pnl.is_(None))` filter (previously
    `settled.is_(False)` only), so limbo-window positions are still eligible
    for an APEX exit.
  - New `_close_position(sig, ctx)`: settles the `Trade` in place via
    `calculate_exit_pnl` — sets `settled=True`, `pnl`, `result`
    (`win`/`loss`/`push`), `settlement_time=utcnow()`,
    `settlement_source=f"early_exit_{sig.reason.value}"`. Guards against
    re-closing an already-fully-settled trade.
  - New `_place_exit_order(trade, exit_price, ctx)`: live-mode CLOB SELL,
    gated by `StrategyGate.can_execute_live("apex", db)` — dormant while
    apex is paper-only. On rejection/error returns `None` and the position
    stays open for retry next cycle.
  - Phase 1 now calls `_close_position` for each exit signal.
- `backend/core/paper_pnl_audit.py`: `_settlement_value_for_trade` returns
  `None` for `settlement_source` starting with `early_exit_` to avoid
  false-positive mismatches (different pnl model than binary settlement).

Documented in `docs/architecture/adr-017-apex-early-exit-settlement.md` per
the ADR-gating rule for settlement logic.

### Verification

New tests:
- `backend/tests/test_apex_edge.py::TestExitManager`:
  `test_pnl_pct_direction_independent` (a `no` position and a `yes` position
  at the same entry/current prices produce the same `PROFIT_TARGET` signal
  and `pnl_pct`), `test_stop_loss_no_direction`.
- `backend/tests/test_settlement.py::TestCalculateExitPnl` (5 tests):
  profit exit, loss exit, direction-independence, `fill_price`/`filled_size`
  precedence, stored `trade.fee` precedence.
- `backend/tests/test_apex_strategy.py::TestAPEXClosePosition` (5 tests):
  profit-target close (paper), stop-loss close (paper), no-op on
  already-fully-settled trade, end-to-end `run_cycle` Phase 1 closing a
  profit-target position via a mocked CLOB mid-price, and a live-mode close
  blocked by the strategy gate (position stays open, no CLOB call made).

`pytest backend/tests/test_apex_edge.py backend/tests/test_settlement.py
backend/tests/test_apex_strategy.py backend/tests/test_paper_pnl_audit.py`:
83 passed.

### Status

Bug O: fixed, tested, documented (ADR-017). Paper-mode exits are live as of
this fix — the next time an open apex position's mid-price moves ±2.5%/4%
from entry or it's held >2h, `_close_position` will settle it with a real
partial pnl instead of waiting for Gamma. Live-mode `_place_exit_order` is
gated by `StrategyGate.can_execute_live` and dormant (apex is paper-only),
untested per the `SHADOW_MODE=true` live-trading-test restriction.

### Immediate backlog Bug O should clear on the next 1-2 `apex` cycles

As of 2026-06-13 ~03:00 UTC, apex has **36 stuck paper positions** ($1505.42
total cost basis) that this fix directly targets — all 36 are already past
`APEX_MAX_HOLD_SECONDS=7200` (2h), so `_check_exits` should generate at least
a `TIME_DECAY` (or `PROFIT_TARGET`/`STOP_LOSS` if price has moved enough)
signal for every one of them on the next `run_cycle`:

- 21 positions `settled=false, pnl=NULL`, ages 4.1-10.9h (genuinely open,
  always were eligible for `_check_exits`).
- 15 positions `settled=true, pnl=NULL`, ages 19.1-25.5h — the ADR-016 limbo
  state (`_cleanup_stale_trades_job`'s 12h `stale_paper` branch already fired
  and Gamma resolution didn't return a value). Before this fix these were
  invisible to `_check_exits` (`Trade.settled.is_(False)` only) and would have
  sat for up to 5 days before `force_closed_unresolved` hardcoded them to
  `pnl = -cost_basis` (100% loss). The new `or_(Trade.settled.is_(False),
  Trade.pnl.is_(None))` filter (point 3 of the Fix above) now includes them —
  they'll get a real partial-pnl early exit at current mid price instead.

**Verification for next session**: re-run the settled-trade query from
Bug O's investigation —

```sql
SELECT strategy, settlement_source, result, count(*), round(sum(pnl)::numeric,2)
FROM trades WHERE strategy='apex' AND settled=true AND pnl IS NOT NULL
GROUP BY strategy, settlement_source, result ORDER BY settlement_source, result;
```

Expect new `early_exit_time_decay` / `early_exit_profit_target` /
`early_exit_stop_loss` rows (in addition to the existing 7
`market_resolution` rows: 6 loss/-52.46, 1 win/+13.23), and the apex open-
position count/cost-basis to drop from 36/$1505.42 toward 0. If 36 positions
are STILL stuck with the SAME ages after apex has cycled multiple times,
check whether `ctx.clob.get_mid_price(token_id)` is failing for these
specific (likely old/thin) markets — `_get_current_price` returns `None` on
CLOB error, which makes `check_position` a no-op (`current_price is None →
return None`), silently leaving the position open with no exit signal and no
error surfaced.

### VERIFIED 2026-06-13 03:09 WIB — Bug O fix deployed and confirmed live

**Root cause of the "0 cycles cleared" symptom**: `pm2` showed
`polyedge-orchestrator` had been running since 2026-06-12 22:42:04 — over 4
hours BEFORE commit `6d5baf7a` (Bug O) was made at 02:43:12. Python doesn't
hot-reload, so the live bot was executing the pre-fix `apex_strategy.py` the
entire time; the fix was correct but **inert** until the process restarted.
Ran `pm2 restart polyedge-orchestrator` (clean restart, no startup errors,
8 paper strategies registered).

**Result — first post-restart apex cycle (03:09:41-43 WIB)** closed **32 of
the 36** stuck positions in a single pass via `_close_position`:

| exit reason | result | count | sum(pnl) |
|---|---|---|---|
| profit_target | win | 10 | +40.65 |
| stop_loss | loss | 9 | -44.60 |
| time_decay | loss/push/win | 10 (5/1/4) | +0.65 |
| edge_decay | loss | 3 | -0.62 |

A second cycle 340s later closed 2 more (1 more profit_target win, 1 more
stop_loss loss), leaving **2 open positions / $37.00 cost basis** (down from
36/$1505.42). Net realized pnl across all 34 early exits: **-$5.19** —
losses that were previously running to full Gamma settlement (-100% of cost
basis) are now capped at `stop_loss_pct=4%`. Biggest example: trade #25761
(`fifwc-aut-jor-2026-06-17-goals-romano-schmid-gte3`) closed at
`stop_loss exit_price=0.0250 pnl=-17.85` instead of riding to -100%.

**Operational note for future fixes**: a code commit to a strategy module
has **zero runtime effect** until `pm2 restart polyedge-orchestrator` is run
— `git log` time is not a proxy for "deployed". Any future fix to
`backend/strategies/`, `backend/core/edge/`, or `backend/core/scheduling/`
should be followed by a restart + log/DB verification, as done here.

**Status**: Bug O CLOSED. apex's open-position backlog is cleared; going
forward `_check_exits` runs every `ORCHESTRATOR_STRATEGY_INTERVAL_SECONDS`
(300s) and should keep the open-position count near `max_concurrent` rather
than accumulating.

## Update — 2026-06-13: Bug P — `bond_scanner` LIVE trades record
## `result="loss"` with positive `pnl`, understating win rate

### Root cause

ADR-016 (Bug M, above) fixed `force_closed_unresolved`'s hardcoded
`calculate_pnl(trade, 0.0)` but explicitly deferred four other settlement
branches that had the *identical* pattern, reasoning live trading was
disabled. `bond_scanner` has since been re-enabled for **live** trading
(`rehab_allocation_pct=0.25`, since 2026-06-12 07:30:40), making this no
longer theoretical.

`calculate_pnl(trade, 0.0)` means "settlement_value=0.0" — a WIN for
`direction="no"/"down"` positions (positive pnl via the WIN formula), but
these branches all hardcode `result="loss"`. Found 11 `bond_scanner` trades
(10 distinct positions) with `result="loss"` and **positive** `pnl`, total
**+$29.09**, all `direction="no"`, settled via `closed_unresolved` or
`expired_unresolved`:

```
id     market                                                  entry  size     pnl   result  source
25753  will-matheus-cunha-score-a-goal-...-world-cup            0.230  5.000    3.85  loss    closed_unresolved
25700  will-luke-kornet-score-40-points-...                     0.908  5.776    0.53  loss    closed_unresolved
25699  (same market as 25700)                                   0.908  5.776    0.53  loss    closed_unresolved
25694  over-500m-committed-to-the-align-public-sale             0.988  5.050    0.06  loss    closed_unresolved
25693  will-morgan-stanley-fail-by-june-30-2026                 0.989  5.050    0.06  loss    closed_unresolved
25440  highest-temperature-in-denver-on-june-8-2026-92-93f      0.039  5.000    4.81  loss    expired_unresolved
25328  highest-temperature-in-guangzhou-on-june-8-2026-35corh.  0.010  5.000    4.95  loss    expired_unresolved
25265  highest-temperature-in-houston-on-june-7-2026-82-83f     0.016  5.000    4.92  loss    expired_unresolved
25087  highest-temperature-in-dallas-on-june-7-2026-94-95f      0.114  5.000    4.43  loss    expired_unresolved
24156  highest-temperature-in-atlanta-on-june-7-2026-76-77f     0.010  5.000    4.95  loss    expired_unresolved
```

This inflates `bond_scanner`'s reported loss count (and understates its win
rate), which directly feeds CLAUDE.md's "Auto-kill at <30% win rate"
governance rule — relevant since `bond_scanner` is currently on live-trading
probation.

A fourth branch, `_settle_btc_5min_trade`'s 24h-unresolved timeout, has the
same hardcode plus two compounding bugs: (1) it sets
`result="expired_unresolved"`, which `botstate_ledger.py::is_push` treats as
a full-credit-back push (ignoring `pnl`) — inconsistent with the other three
branches' `result="loss"`; (2) it compares a tz-aware `now` against
`trade.timestamp` (naive UTC per `c2e92f5e`), which raises
`TypeError: can't compare offset-naive and offset-aware datetimes` —
aborting the *entire* settlement batch (all strategies) the first time any
`btc-updown-5m-*` trade goes unresolved for 24h, violating "Settlement is
Sacred — stale positions block orders."

### Fix

`backend/core/settlement/settlement.py`: applied
`total_loss_settlement_value(trade.direction)` (from ADR-016) to all four
deferred branches — `closed_unresolved`, `expired_unresolved`,
`stale_expired`, and `_settle_btc_5min_trade`'s `btc_5min_unresolved` —
replacing the hardcoded `calculate_pnl(trade, 0.0)` /
`settlement_value=0.0`. Also changed `_settle_btc_5min_trade`'s `result`
from `"expired_unresolved"` to `"loss"` (matching the other three branches,
so `is_push`/`is_loss` bankroll treatment stays consistent with the now-real
negative `pnl`), and normalized `trade.timestamp` to tz-aware UTC before the
24h-timeout comparison, matching the existing pattern at
`settlement.py:589-590`/`:634-635`. Documented in
`docs/architecture/adr-018-unresolved-loss-branches-pnl.md` per the
ADR-gating rule for settlement logic; `backend/core/AGENTS.md`'s "Settlement
is Sacred" section now lists all five `result="loss"` force-settle branches
that must use `total_loss_settlement_value`.

Per CLAUDE.md's append-only rule (and ADR-016 Alternative 3), the 11
historical `bond_scanner` rows (+$29.09 mislabeled as losses) are **not**
backfilled — this is a forward-going fix only.

### Verification

- New tests in `backend/tests/test_settlement.py`
  (`TestUnresolvedLossConsistency`, 2 tests): an `expired_unresolved` NO
  position now settles with `result="loss"`, `settlement_value=1.0`,
  `pnl<0` (previously `pnl>0`); a `btc_5min_unresolved` DOWN position past
  24h now settles with `result="loss"`, `settlement_value=1.0`, `pnl<0`
  (previously `result="expired_unresolved"`, `pnl>0`, and would have raised
  `TypeError` on the naive/aware comparison).
- `pytest backend/tests/test_settlement.py`: 36 passed.

### Status

Bug P: fixed (forward-going), tested, documented (ADR-018). Historical
backfill of the +$29.09 mislabeled `bond_scanner` rows is a deferred
follow-up, same as Bug M's ~$14,051. Live verification requires waiting for
the next `bond_scanner`/BTC-5min trade to hit one of these four branches
(not immediately observable — will check settlement logs after restart for
clean execution with no new `TypeError`).

## Update — 2026-06-13: Bug Q — Alembic `alembic_version` desynced from
## `backend/alembic`'s graph; `transaction_events` rows unreadable via ORM

### Root cause

`cd backend && alembic current` failed with `Can't locate revision
identified by 'arb_exec_status_001'` — the canonical migration tool
(`backend/alembic/`, per `docs/alembic-dirs.md`) was completely broken,
directly blocking CLAUDE.md's "Database schema changes require an Alembic
migration" workflow.

Cause: the root `alembic.ini`/`alembic/env.py` (legacy, 50 migrations, head
`arb_exec_status_001`) points at the SAME `settings.DATABASE_URL` as
`backend/alembic/` (canonical, 8 migrations, head `add_arb_bundle_tracking`)
— two disconnected revision graphs sharing one `alembic_version` row.
Commit `5c0a7801` (2026-06-11) added a migration to the legacy
`alembic/versions/` (against `docs/alembic-dirs.md`'s guidance) that added
`decision_log.execution_status` + an index, and `alembic upgrade head` was
run from the repo root — applying that column to prod and setting
`alembic_version='arb_exec_status_001'`, a revision ID `backend/alembic`'s
graph has never heard of.

Separately, this surfaced a second bug while investigating: querying
`transaction_events` via the ORM (`db.query(TransactionEvent)...`) raises
`LookupError: 'ledger_wallet_sync' is not among the defined enum values`.
`BotStateLedger._apply` (`backend/core/wallet/botstate_ledger.py`) wrote
`TransactionEvent.type = f"ledger_{operation}"` — e.g. `"ledger_wallet_sync"`
for `sync_to_absolute`'s reconciliation writes. SQLite/Postgres accept this
on INSERT (no enum enforcement at the driver level), but
`transaction_event_type`'s enum (`deposit`, `settlement_win`,
`settlement_loss`, `reconciliation_adjustment`, `allocation`, `fee`,
`withdrawal`) doesn't include any `ledger_*` value, so every SELECT of a
row with that `type` crashes. 989 of 55,596 rows (all `wallet_sync`, the
most frequent reconciliation op) were affected — any future ledger/
transaction-history endpoint touching this table would crash.

### Fix

1. `alembic stamp --purge add_arb_bundle_tracking` — confirmed the DB schema
   already matches every column/table `backend/alembic`'s 8 canonical
   migrations would create, then re-pointed `alembic_version` at that head
   (metadata-only, no schema change).
2. `backend/alembic/versions/20260613_add_decision_execution_status.py` —
   new canonical migration, `down_revision=add_arb_bundle_tracking`, that
   idempotently adds `decision_log.execution_status` + its index (no-ops
   here since the stray legacy migration already added them; applies
   cleanly on a fresh DB).
3. `backend/core/wallet/botstate_ledger.py::_apply` — replaced the
   `f"ledger_{operation}"` type with a mapping to valid enum members
   (`deposit`/`withdrawal`/`allocation`/`fee`/`settlement_win`/
   `settlement_loss`/`reconciliation_adjustment` pass through,
   `fill_debit`→`fee`, everything else incl. `wallet_sync`→
   `reconciliation_adjustment`).
4. `backend/alembic/versions/20260613_fix_ledger_wallet_sync_event_type.py`
   — data migration backfilling the 989 existing `type='ledger_wallet_sync'`
   rows to `'reconciliation_adjustment'` (amount/balance_after/context/note
   untouched — only the schema-invalid discriminator is corrected).
5. `alembic/env.py` (legacy root dir) now raises immediately on import,
   so `alembic upgrade head` can never again be run from the repo root
   against the shared DB. `docs/alembic-dirs.md` and
   `backend/alembic/AGENTS.md` document the incident and the guard.

### Verification

- `cd backend && alembic current` → `add_decision_execution_status` then
  `fix_ledger_wallet_sync_type (head)` after `alembic upgrade head` — both
  ran without error.
- `transaction_events` group-by-`type` after the backfill: no more
  `ledger_wallet_sync` rows; `reconciliation_adjustment` count rose from
  20,270 → 21,272 (the 989 backfilled + ~13 new from the restart);
  `db.query(TransactionEvent).count()` (full ORM SELECT) now succeeds.
- New regression test
  `test_wallet_sync_transaction_event_type_is_valid_enum` in
  `backend/tests/test_balance_ledger_regression.py`: `sync_to_absolute`
  now records `type="reconciliation_adjustment"`. 9/9 pass in that file.
- `pm2 restart polyedge-orchestrator`: online, no new tracebacks.

### Status

Bug Q CLOSED. Canonical Alembic workflow (`cd backend && alembic upgrade
head`) works again; root `alembic/` can no longer silently corrupt
`alembic_version`; `transaction_events` is fully ORM-readable.

## Update — 2026-06-13: Bug R — `_row_to_profile` drops preset-specific
fields; risk-tier selection has no effect on longshot bias / loss floors /
scheduler interval

### Root cause

`RiskProfileRow` (the `risk_profiles` DB table) has no columns for
`longshot_no_bias_weight`, `daily_loss_floor_pct`, `weekly_loss_floor_pct`,
or `orchestrator_interval_seconds`. `_row_to_profile()` — the function
`get_profile()`, `list_profiles()`, and `update_profile()` all funnel
through whenever a `RiskProfileRow` exists (i.e. after `seed_presets()` has
run, which is the normal case) — built `RiskProfile(...)` without passing
these 4 fields at all, so they silently fell back to the dataclass's generic
defaults (`longshot_no_bias_weight=0.10`, `daily_loss_floor_pct=-0.10`,
`weekly_loss_floor_pct=-0.20`, `orchestrator_interval_seconds=300`)
regardless of which tier (`safe` ... `crazy`) was actually selected.
`apply_profile()` then copies these into `settings.LONGSHOT_NO_BIAS_WEIGHT`
/ `DAILY_LOSS_FLOOR_PCT` / `WEEKLY_LOSS_FLOOR_PCT` /
`ORCHESTRATOR_STRATEGY_INTERVAL_SECONDS` — e.g. selecting `"crazy"`
(longshot bias 0.20, loss floors -0.80/-0.95, 30s polling) actually ran with
`"normal"`'s generic values (0.10/-0.10/-0.20/300s) once the DB-backed
profile existed.

### Fix

`_row_to_profile()` (`backend/core/risk/risk_profiles.py`) now looks up
`PRESETS.get(row.name)` and copies the 4 fields from the matching preset,
falling back to the previous generic defaults only when `row.name` isn't a
known preset (i.e. a user-created custom profile).

### Verification

- New test `test_row_to_profile_preserves_preset_specific_fields` in
  `backend/tests/test_risk_profiles.py`: after `seed_presets(db=db)`,
  `get_profile("extreme", db=db)` and `get_profile("crazy", db=db)` now
  match `PRESETS["extreme"]` / `PRESETS["crazy"]` for all 4 fields (before
  the fix, both returned the generic 0.10/-0.10/-0.20/300 regardless of
  tier).
- `pytest backend/tests/test_risk_profiles.py`: 20/20 pass.

### Status

Bug R CLOSED.

## Update — 2026-06-13: Bug S — `check_risk_and_disable` raises
`ZeroDivisionError` on every heartbeat when `live_initial_bankroll == 0.0`

### Root cause

`bot_state.live_initial_bankroll is not None` treats `0.0` — a valid float a
fresh `BotState` row can have before the first deposit is recorded — as
"set", so `initial = 0.0`. The next line,
`drawdown_pct = abs(min(0, total_pnl)) / initial * 100`, then raises
`ZeroDivisionError`. `check_risk_and_disable` is the "Risk Layer —
Auto-Disable" check that CLAUDE.md says runs on every heartbeat; a crash
here means the total-drawdown auto-disable circuit silently never runs.

### Fix

`backend/core/strategy_gate.py::check_risk_and_disable` now guards both the
`live_initial_bankroll` and `paper_initial_bankroll` branches with `> 0` in
addition to `is not None`, falling through to the existing `initial = 100.0`
default when both are zero or unset.

### Verification

- New test `test_zero_initial_bankroll_does_not_raise_zero_division` in
  `backend/tests/test_strategy_gate.py`: `live_initial_bankroll=0.0` and
  `paper_initial_bankroll=0.0` no longer raise `ZeroDivisionError`.
- `pytest backend/tests/test_strategy_gate.py`: 18/18 pass.

### Status

Bug S CLOSED. `strategy_gate.py` is not in the ADR-gated list
(`risk_manager.py`/`circuit_breaker.py`/`settlement.py`), so no new ADR is
required.

## Update — 2026-06-13: Bug T — `PUT /api/v1/strategies/{name}` always
(un)schedules the "paper" job, ignoring the strategy's `trading_mode`

### Root cause

`update_strategy()` (`backend/api/system.py`) called
`schedule_strategy(name, interval)` / `unschedule_strategy(name)` without
`mode=...`; both default to `mode="paper"`. `scheduler.py` job IDs are
`f"{mode}_{strategy_name}_{interval_seconds}"`, so for any strategy
configured with `trading_mode="live"` or `"testnet"`, toggling it via this
endpoint scheduled/unscheduled `paper_{name}_{interval}` instead of its real
`live_{name}_{interval}` (or `testnet_...`) job. Disabling a live strategy
through this endpoint therefore did not stop it from running — a
strategy-governance/safety gap.

### Fix

`update_strategy()` now passes `mode=cfg.trading_mode or "paper"` to both
`schedule_strategy` and `unschedule_strategy`.

### Verification

- New test `test_update_strategy_schedules_with_trading_mode` in
  `backend/tests/test_api_strategies.py`: `PUT .../strategies/{name}` with
  `trading_mode="live"` now calls `schedule_strategy(name, 30, mode="live")`
  on enable and `unschedule_strategy(name, mode="live")` on disable.
- `pytest backend/tests/test_api_strategies.py`: 9/9 pass.

### Status

Bug T CLOSED. Pre-existing, separate gap noted but not fixed here:
`unschedule_strategy`'s default `interval_seconds=60` is not passed
`cfg.interval_seconds`, so if a strategy's interval was changed from 60
after scheduling, unschedule still won't match its job_id — out of scope
for this fix.

## Update — 2026-06-13: Bug U — 15 historical trades mislabeled
`result="loss"` despite positive `pnl` (pre-ADR-016/018 stale data)

### Root cause

Before ADR-016 (Bug M, commit `f3cd8302`) and ADR-018 (Bug P, commit
`1e1cdb85`), the `expired_unresolved`/`closed_unresolved` force-close
branches in `settlement.py` hardcoded `trade.result = "loss"` and computed
`pnl = calculate_pnl(trade, settlement_value=0.0)` regardless of
`trade.direction`. For `direction="no"` trades, `settlement_value=0.0`
is the **win** formula (`pnl = shares * (1 - entry_price) - fee`, positive)
— so these trades got a positive `pnl` but a `"loss"` label.

Found via DB query while investigating the Stop-hook's demand for
evidence-based profitability data: 15 settled trades (all `direction="no"`,
`settlement_value=0.0`, settled 2026-06-10 through 2026-06-12, i.e. before
both fixes landed on 2026-06-13) have `result="loss"` AND `pnl > 0`:

- 6 × `trading_mode="paper"`, `strategy="bond_scanner"`,
  `settlement_source="expired_unresolved"`, sum `pnl=+$29.01`
- 5 × `trading_mode="live"`, `strategy="bond_scanner"`,
  `settlement_source="closed_unresolved"`, sum `pnl=+$5.03`
- 4 × `trading_mode="live"`, `strategy="position_sync"`,
  `settlement_source="closed_unresolved"`, sum `pnl=+$58.03`

`BotStateLedger.credit_on_settlement`'s `is_loss` branch applies
`bankroll_delta = size + pnl` / `pnl_delta = pnl` — the same formula as the
`is_win` branch — so `paper_bankroll`/`paper_pnl`/`bankroll`/`total_pnl`
**already include these correct positive amounts** (no money is missing or
miscounted). The only things wrong were: (1) the `result` label itself, and
(2) `paper_wins`/`winning_trades` were not incremented because `is_win` was
`False` at settlement time. This directly distorts `StrategyGate`'s
`result == "win"` win-rate computation used by the Strategy Gating Pipeline
(`_check_fronttest`/`_check_shadow`), and skews any win-rate stat read from
`Trade.result`.

The forward-going code (post Bug M/P, using `total_loss_settlement_value`)
is already correct — for `direction="no"`,
`total_loss_settlement_value("no") == 1.0`, and
`calculate_pnl(direction="no", settlement_value=1.0)` is the **loss**
formula (negative `pnl`), matching `result="loss"`. This is a pure
historical-data backfill for rows created by the old, already-fixed code.

### Fix

New Alembic data migration
`backend/alembic/versions/20260613_fix_stale_loss_label_positive_pnl.py`
(`fix_stale_loss_positive_pnl`, head, depends on `fix_ledger_wallet_sync_type`
from Bug Q):

- `UPDATE trades SET result = 'win' WHERE id IN (<15 ids>) AND result = 'loss' AND pnl > 0`
- `UPDATE bot_state SET paper_wins = paper_wins + 6 WHERE mode = 'paper'`
- `UPDATE bot_state SET winning_trades = winning_trades + 9 WHERE mode = 'live'`

No `bankroll`/`pnl`/`total_pnl` columns are touched — those were already
correct.

### Verification

- `alembic upgrade head` applied cleanly; `alembic current` →
  `fix_stale_loss_positive_pnl (head)`.
- Post-migration: 0/15 rows remain with `result='loss' AND pnl>0`; all 15
  now `result='win'`. `bot_state.paper_wins` 1564→1571 (+6 from this
  migration, +1 from a trade that settled in the interim);
  `bot_state.winning_trades` (live) 73→82 (+9, exact match, no live
  settlements in the interim).
- `pytest backend/tests/test_settlement.py backend/tests/test_strategy_gate.py backend/tests/test_balance_ledger_regression.py`:
  63/63 pass.
- **Current realized P&L evidence** (post-fix, per the Stop hook's request
  for actual, not theoretical, numbers):
  - paper bankroll=$793.42, total_pnl=-$3904.67 (lifetime; dominated by the
    still-deferred ADR-016 Alternative 3 backfill, ~2,830 `unified_arb`
    pnl=0.0 rows ≈ -$14,051 unrecorded, see Bug M)
  - paper 24h: 611 settled, 34 wins (5.6% WR), pnl=-$87.12
  - paper 7d: 3055 settled, 92 wins (3.0% WR), pnl=+$152.85
  - live bankroll=$27.48, total_pnl=-$439.74 (lifetime)
  - live 24h: 22 settled, 3 wins (13.6% WR), pnl=-$14.33
  - live 7d: 73 settled, 16 wins (21.9% WR), pnl=+$46.95

### Status

Bug U CLOSED. Both paper and live are net **profitable over the trailing
7 days** (+$152.85 / +$46.95) but net **negative over the trailing 24h**
(-$87.12 / -$14.33) — consistent with the longshot-heavy strategy mix
(rare large wins offsetting frequent small losses). The remaining lever for
durable profitability is the still-deferred ADR-016 Alternative 3 backfill
(~$14,051 of `unified_arb`/`bond_scanner` pnl=0.0 rows that represent real
historical losses never reflected in `paper_pnl`/`paper_bankroll`) — see
Bug M for why this was deferred (append-only Trade guidance, needs its own
ADR before touching `paper_bankroll`/`paper_pnl`/`total_pnl`).
