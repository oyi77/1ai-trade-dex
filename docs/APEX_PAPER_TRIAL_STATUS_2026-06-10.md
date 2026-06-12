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
`confidence >= 0.50 / 1.10 ≈ 0.4546`. Of the 10 observed candidates
(`confidence` 0.41-0.48), **3/10** now clear the floor
(`bitcoin-above-60k-on-june-18-2026` 0.484→0.532,
`aligned-fdv-above-20m-one-day-after-launch` 0.473→0.521,
`will-nike-q4-greater-china-revenue-be-above-1pt0b` 0.472→0.519). The
remaining 7/10 (`confidence` 0.41-0.45, mostly markets priced < 1c) stay
below 0.4546 even after the boost and continue to be rejected — see
"Alternatives Considered" in ADR-015 for why the weight was not increased
further in this pass.

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
- Live verification (post-restart, expect ~3/10 `longshot_bias` decisions per
  cycle to clear the risk gate and appear as paper `Trade` rows) pending.

### Status

Bug L: fixed, tested (112 passed / 3 skipped), documented (ADR-015). Live
verification pending restart of `polyedge-orchestrator`.
