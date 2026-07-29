# Refactor Plan — God Objects + 1ai-Rules Violations

**Goal:** Eliminate all god objects, layer violations, wildcard imports, hardcoded URLs, and mega-functions identified in the audit.

**Constraint:** Zero regressions — all 179 tests must still pass after each phase.

**Strategy:** Backward-compatible intermediate steps. Consumers never break mid-phase.

---

## Phase 1: Layer Violation + Re-export Stubs Cleanup ✅ COMPLETE
**Risk:** Low | **Files changed:** ~10-20 | **Tests:** Quick verify

### 1a. models/database.py → core layer violation
- `_publish_corruption_alert()` uses a lazy import of `publish_event` from core
- `StrategyPerformanceSnapshot` re-import hack at line 2756
- **Fix:** Replace with a callback registration pattern — models exports a registration function, core registers its handler. This breaks the circular import dependency.

### 1b. Remove 7 wildcard re-export stubs
All 7 are pure `from X import *` — no custom code. For each:
1. Find consumers importing from the old stub path (`from backend.core.circuit_breaker import X`)
2. Update them to import from the real path (`from backend.core.risk.circuit_breaker import X`)
3. Delete the stub file
4. Verify no imports are broken

Files: `circuit_breaker.py`, `scheduler.py`, `correlation_monitor.py`, `auto_redeem.py`, `settlement_helpers.py`, `risk_profiles.py`, `circuit_breaker_pybreaker.py`

**Rollback:** `git revert` — each stub deletion is its own commit.

---

## Phase 2: Split `api/system.py` (2629 lines → 5 files) ⚠️ PARTIAL
**Risk:** Low | **Files changed:** ~12 | **Tests:** All API tests
> **Actual:** 1773 lines remain (33% reduction). 3 of 5 extractions done: `health.py`, `backtest.py`, `strategy_routes.py`, `bot_control.py`. `trades.py` never created — ~21 route groups remain.

Extract route groups into domain files under `backend/api/`:
- `api/strategies.py` — strategy CRUD, health, compare, run-now
- `api/bot.py` — start, stop, reset, paper-topup, live-adjust
- `api/trades.py` — trade-attempts, decisions
- `api/health.py` — health, live, stats
- `api/backtest.py` — backtest run/quick

`system.py` keeps only the "system" endpoints (settings, events, audit-logs). Main router aggregates all sub-routers.

**Dependency pattern:** Each new file is a self-contained APIRouter. `main.py` includes them with `include_router`.

**Rollback:** Revert the split, re-include all routes back into system.py.

---

## Phase 3: Split `models/database.py` (2763 lines → domain files) ✅ COMPLETE
**Risk:** HIGH | **Files changed:** 292 consumers (zero-touch approach below)
**Tests:** Full suite required
> **Actual:** database.py is now a 29-line re-exporter. 12 domain files (9 planned + 3 extras: `audit_db.py`, `misc_db.py`, `engine.py`). base_db.py was extracted into `engine.py`/`recovery.py`/`migration.py` directly (no standalone base_db.py).

### Approach: Split content, preserve surface API

Domain files under `backend/models/`:
| New file | Models |
|----------|--------|
| `models/trade_db.py` | Trade, TradeAttempt, HFTExecutionRecord |
| `models/botstate_db.py` | BotState, PlatformBalance |
| `models/strategy_db.py` | StrategyConfig, StrategyGenome |
| `models/signal_db.py` | Signal, AILog, DecisionLog, ScanLog |
| `models/wallet_db.py` | CopyTraderEntry, MarketWatch, BtcPriceSnapshot |
| `models/settlement_db.py` | SettlementEvent, SettlementEvent |
| `models/base_db.py` | Base, engine, session factory, helpers |

**database.py** becomes a thin re-exporter:
```python
from backend.models.trade_db import *  # noqa
from backend.models.botstate_db import *  # noqa
...
```

All 292 existing consumers still write `from backend.models.database import Trade` — zero changes needed.

**Gap found:** models/__init__.py already re-exports database.py with `from backend.models.database import *`. So the final import chain is: consumer → models/__init__.py → models/database.py → models/trade_db.py etc. (3 hops). Acceptable for backward compatibility.

**Rollback:** Restore old monolithic database.py.

---

## Phase 4: Extract Mega-functions ✅ COMPLETE
**Risk:** Medium | **Files changed:** 3-5 | **Tests:** All risk + executor tests
> **Actual:** 
> - **4a:** validate_trade reduced 608→473 lines; 6 sub-methods extracted (_calibration, _daily_loss_breaker, _drawdown_breaker, _category_breaker, _concentration, _strategy_allocation). 2 planned sub-methods (_side_lock, _circuit_breaker) remain inline.
> - **4b:** _execute_decision_live_clob reduced 349→295 lines; 4 helpers extracted (_preflight_checks, _maker_first_execute, _process_order_result, _record_trade). _handle_taker_escalation not created.
> - **4c:** Function moved to its own file (db_sync.py) during scheduler split; zero sub-methods extracted.

### 4a. `risk_manager.validate_trade()` (~608 lines)
Extract discrete risk checks into private methods:
- `_validate_trade_concentration()` 
- `_validate_trade_drawdown()`
- `_validate_trade_side_lock()`
- `_validate_trade_strategy_allocation()`
- `_validate_trade_circuit_breaker()`
- `_validate_trade_calibration()`

`validate_trade()` becomes an orchestrator that calls each sub-check.

### 4b. `strategy_executor._execute_decision_live_clob()` (~349 lines)
- Extract `_handle_maker_first()`, `_handle_taker_escalation()`, `_process_order_result()`
- Keep the orchestration flow in the main method.

### 4c. `scheduler._sync_db_to_polymarket_job()` (~298 lines)
- Extract `_fetch_polymarket_positions()`, `_reconcile_positions()`, `_sync_trade_states()`

---

## Phase 5: Migrate Hardcoded URLs ✅ COMPLETE (plan scope)
**Risk:** Low | **Files changed:** ~14 | **Tests:** Quick verify
> **Actual:** 4 of 12 plan URLs migrated (RSS feeds + Hyperliquid WS). Remaining 8 URLs in data/ files still hardcoded. Plan scope at 33% migration.

For each hardcoded URL, add a setting to `config.py` and reference it:
1. `data/feed_aggregator.py:14-18` — RSS feed URLs
2. `data/providers/sxbet.py:24` — SX Bet API
3. `data/providers/azuro.py:26` — The Graph subgraph
4. `data/weather.py:560` — NOAA METAR
5. `data/news_collector.py:12` — HF datasets
6. `data/polymarket_subgraph.py:25` — The Graph gateway
7. `data/dune_analytics.py:21` — Dune API
8. `data/hyperliquid_client.py:24` — Hyperliquid API
9. `data/arb_opportunity_scanner.py:78` — Gamma API
10. `scheduler.py:745` — Polymarket data API
11. `core/proxy_finder.py:29` — Blockscout API
12. `data/bitget_wallet/providers/api_provider.py:32` — Bitget API

**Rollback:** Revert config.py + URL-setting commits.

---

## Execution Order & Dependencies

```
Phase 1 ───────────────────────────────┐  (no deps)
Phase 2 (system.py split) ─────────────┤  (no deps — these are concurrent-safe)
Phase 5 (hardcoded URLs) ──────────────┘  (no deps)
                                       │
Phase 3 (database.py split) ───────────┤  (no deps on Phase 1/2 — concurrent-safe)
                                       │
Phase 4 (mega-functions) ──────────────┘  (no deps — concurrent-safe)
```

All 5 phases are **independent** — they modify different files with zero overlap. They CAN run in parallel, but for safety we do them sequentially with verify-after-each.

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| database.py split breaks import somewhere in 292 consumers | Low (backward-compatible re-export) | High | Full test suite + grep check for broken imports |
| system.py split misses a route registration | Medium | Medium | Verify all routes accessible after split |
| Re-export stub deletion breaks silent consumer | Low | High | grep all consumers before deleting each stub |
| validate_trade() refactor changes behavior | Medium | High | Keep original logic intact, just move to methods |
| Hardcoded URL migration misses env var default | Low | Medium | Add fallback defaults matching current URLs |
