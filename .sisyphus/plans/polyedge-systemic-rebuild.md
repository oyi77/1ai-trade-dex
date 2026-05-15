# PolyEdge Systemic Rebuild Plan
**Date**: 2026-05-08
**Status**: DRAFT — awaiting approval
**Trigger**: User report — no trades 3+ days, AGI not running, frontend broken via domain

---

## Executive Summary

PolyEdge is **non-functional** despite PM2 showing all services "online":
- **0 trades** in 3 days (paper AND live)
- **AGI system never ran** — 512,704s stale heartbeat (6 days)
- **Frontend inaccessible** via domain — CF tunnel missing entries
- **68,222 BLOCKED + 287,976 REJECTED** trade attempts vs only 1,059 EXECUTED

Root causes: configuration gaps, broken signal pipeline, duplicate order dedup blocking everything, FK constraint preventing watchdog from logging, and architecture confusion between strategies and system modules.

---

## Findings (8 Critical Issues)

### F1. CF Tunnel Missing Polyedge Entries (INFRASTRUCTURE)
**Severity**: P0 — domain completely inaccessible
**Evidence**:
- `/home/openclaw/projects/cf-router/tunnel/config.yml` has NO `polyedge.aitradepulse.com` or `polyedge-api.aitradepulse.com` entries
- CF-router nginx has the site configs (`cf_polyedge_aitradepulse_com.conf`, `cf_polyedge-api_aitradepulse_com.conf`) → proxy to 5174/8100
- But tunnel never routes traffic to them → all domain traffic hits CF default 404
- Frontend works locally (localhost:5174 returns 200)
- Also missing: `polyedge-mirofish` and `polyedge-mirofish-api` entries

**Fix**: Add 4 entries to `config.yml`:
```yaml
- hostname: polyedge.aitradepulse.com
  service: http://localhost:6969
- hostname: polyedge-api.aitradepulse.com
  service: http://localhost:6969
- hostname: polyedge-mirofish.aitradepulse.com
  service: http://localhost:6969
- hostname: polyedge-mirofish-api.aitradepulse.com
  service: http://localhost:6969
```
Then restart cloudflared tunnel.

---

### F2. General Scanner Disabled — Fallback Signal Path Dead
**Severity**: P0 — no signal generation at all
**Evidence**:
- `strategy_config` table: `general_scanner` has `enabled=0`
- Every 10 seconds: `"BTC Oracle: no actionable signals"` → `"General Scanner disabled in config"`
- Previous "fix" to enable it did NOT persist — bot restart likely reset it, or the SQL update was never committed
- `btc_oracle` also `enabled=0` in strategy_config (though it runs via `scan_and_trade_job`, not through config dispatch)
- `universal_scanner` is `enabled=1` but doesn't seem to be the active fallback

**Fix**: 
1. `UPDATE strategy_config SET enabled=1 WHERE strategy_name='general_scanner'`
2. Verify the change persists across bot restart
3. Consider why `btc_oracle` is `enabled=0` — the `scan_and_trade_job` hardcodes it, so the config flag may be irrelevant, but this is confusing

---

### F3. AutoTrader Duplicate Order Filter Blocks 100% of Signals
**Severity**: P0 — auto_trader produces zero trades
**Evidence**:
- Every minute: `"AutoTrader cycle: executed=0 queued=0 skipped=100"`
- `"auto_trader processed 100 signals but created 0 trade attempts — check filters"`
- All 100 signals flagged as "Duplicate order detected" with SHA256 keys
- Dedup uses 5-minute time bucket: `bucket = int(time.time()) // 300`
- The dedup is in `polymarket_clob.py:place_limit_order()` — checks `idempotency_key`
- Problem: AutoTrader re-processes the same stale signals every cycle. Signals don't get cleared, so they keep hitting the same dedup window.

**Root cause analysis**: AutoTrader picks up signals from the DB that were already attempted. The `_check_and_claim_idempotency` prevents re-execution, but signals remain in queue. This creates an infinite loop of "duplicate" rejections.

**Fix**:
1. After processing, signals should be marked as consumed/archived so AutoTrader doesn't re-pick them
2. OR: Clear stale signals from the signal queue after each cycle
3. OR: AutoTrader should filter to only new/unprocessed signals

---

### F4. BTC Oracle Confidence Too Low — All Signals Rejected
**Severity**: P1 — even when BTC Oracle fires, trades are rejected
**Evidence**:
- `trade_attempts` shows: `btc_oracle → REJECTED → "confidence 0.06 below 0.5"`
- BTC Oracle generates BUY signals but confidence is only 0.06
- RiskManager rejects anything below 0.5 confidence
- The BTC Oracle confidence formula: `confidence_score = min(1.0, abs(edge + min_edge) / min_edge)` — with `min_edge=0.05` and edge near 0, confidence stays near 0

**Fix**:
1. Investigate why BTC Oracle edge is consistently near zero (market prices converge to oracle price?)
2. Consider whether `min_edge=0.05` is too high for current market conditions
3. This is a signal quality issue, not a code bug

---

### F5. AGI Improvement Cycle Never Runs
**Severity**: P1 — autonomous improvement dead
**Evidence**:
- `AGI_IMPROVEMENT_CYCLE_ENABLED=True`, scheduler adds the job
- But ZERO log entries for `agi_improvement_cycle` ever executing
- `agi_orchestrator` heartbeat stale 512,704 seconds (6 days)
- Possible causes:
  a. Job scheduled with 4-hour interval but bot keeps restarting before first execution (36 restarts!)
  b. Import error at scheduler startup causing scheduler init to abort before reaching AGI job registration
  c. Exception in `agi_improvement_cycle_job` silently kills the job

**Fix**:
1. Check bot startup logs for import errors in the AGI module chain
2. Add explicit try/except logging around AGI job scheduling
3. Manually trigger AGI cycle to see what happens

---

### F6. FOREIGN KEY Constraint on decision_log
**Severity**: P1 — watchdog alerts silently fail
**Evidence**:
- `decision_log` has FK: `strategy → strategy_config.strategy_name`
- Watchdog tries to INSERT with `strategy='watchdog'` — but `watchdog` is NOT in `strategy_config`
- Result: `sqlite3.IntegrityError: FOREIGN KEY constraint failed`
- Strategies in `decision_log` that DON'T exist in `strategy_config`: `watchdog`, `btc_oracle`, `general_scanner`
- This means watchdog alerts are silently lost, and BTC Oracle decisions can't be logged

**Fix**:
1. Add missing strategy_config rows: `watchdog`, or change FK to allow system-level loggers
2. Alternatively: drop the FK constraint on decision_log (it's an append-only log, FK doesn't add value)

---

### F7. Strategy Heartbeats All Stale
**Severity**: P1 — no strategy is actually running
**Evidence**:
- `whale_frontrun`: stale 13,176s (3.6h)
- `weather_emos`: stale 13,213s
- `kalshi_arb`: stale 13,214s
- `whale_pnl_tracker`: stale 13,196s
- All these are `enabled=1` in strategy_config
- But they're not scheduled as individual jobs in `start_scheduler()` — only special-cased strategies get individual jobs
- The scheduler only runs: `scan_and_trade_job` (BTC Oracle + general scanner), `weather_scan_and_trade_job`, `auto_trader_job`, `heartbeat`, `settlement`, `wallet_sync`
- Other "enabled" strategies (`whale_frontrun`, `kalshi_arb`, `cross_market_arb`, `line_movement_detector`, etc.) have no scheduler job

**Root cause**: The scheduler's strategy-to-job mapping is incomplete. Many enabled strategies have no APScheduler job registered. The `start_scheduler()` function hardcodes specific jobs and doesn't dynamically schedule all enabled strategies.

**Fix**:
1. Map every `strategy_config.enabled=1` strategy to an actual scheduled job
2. Or: acknowledge these strategies are dead code and disable them in config
3. Remove false positives from heartbeat monitoring (don't alert on strategies with no scheduled job)

---

### F8. Architecture — Strategies vs System Modules Mixed
**Severity**: P2 — code clarity and maintainability
**Current state**:
- `backend/strategies/` — 19 files including BOTH real strategies (btc_oracle, market_maker) AND system modules (arb_executor, order_executor, wallet_sync)
- `backend/core/` — 100+ files including BOTH system modules (scheduler, risk_manager, orchestrator) AND strategy-like modules (auto_trader, trade_forensics)
- `backend/modules/` — meant for infra modules, but most things live in `core/`
- DB `strategy_config` treats `auto_trader`, `copy_trader`, `weather_emos`, `agi_orchestrator` as "strategies" but they're system modules

**Proposed separation**:
```
backend/
  strategies/          # Alpha-generating strategies ONLY
    btc_oracle.py
    btc_momentum.py
    general_market_scanner.py
    market_maker.py
    whale_frontrun.py
    cross_market_arb.py
    probability_arb.py
    etc.

  core/                # Trading system infrastructure
    orchestrator.py
    scheduler.py
    risk_manager.py
    auto_trader.py     # Signal router (NOT a strategy)
    trade_forensics.py
    agi_orchestrator.py
    etc.

  modules/             # Infrastructure helpers
    data_feeds/
    execution/         # order_executor, arb_executor
    scanners/
    arbitrage/
```

**Fix**: This is a medium-term refactor. Don't do it now — fix the functional issues first.

---

## Priority Execution Order

### Phase 1: Get Trading Working Again (P0 — Immediate)

| # | Task | Impact | Effort |
|---|------|--------|--------|
| 1.1 | Add polyedge entries to CF tunnel config.yml + restart tunnel | Frontend accessible | 5 min |
| 1.2 | Enable general_scanner in DB + verify persistence | Signal generation resumes | 5 min |
| 1.3 | Fix AutoTrader duplicate signal loop — clear consumed signals after processing | AutoTrader can execute again | 30 min |
| 1.4 | Restart bot, verify first trade appears | End-to-end validation | 10 min |

### Phase 2: Fix AGI & Monitoring (P1 — Same Day)

| # | Task | Impact | Effort |
|---|------|--------|--------|
| 2.1 | Drop FK constraint on decision_log (or add missing strategy_config rows) | Watchdog alerts work | 15 min |
| 2.2 | Investigate why AGI improvement cycle never fires — add startup logging | AGI can run | 30 min |
| 2.3 | Audit scheduler strategy-to-job mapping — disable strategies with no jobs or add jobs | No false heartbeat alerts | 1 hr |
| 2.4 | Investigate BTC Oracle low confidence — is min_edge appropriate? | Better signal quality | 30 min |

### Phase 3: Architecture Cleanup (P2 — Next Sprint)

| # | Task | Impact | Effort |
|---|------|--------|--------|
| 3.1 | Move non-strategy files out of `backend/strategies/` (arb_executor, order_executor, wallet_sync) | Code clarity | 2 hr |
| 3.2 | Move strategy-like modules out of `backend/core/` or clearly document their role | Code clarity | 2 hr |
| 3.3 | Unify strategy config vs scheduler job registration | No orphan strategies | 3 hr |

---

## Frontend Audit Findings (F9-F12)

### F9. Market IDs Shown Instead of Titles (UI)
**Severity**: P1 — unreadable trade history
**Evidence**:
- Backend `Trade` model has `market_ticker` (e.g., `2180598` or `0x3675ea...`) and `event_slug` but NO `market_title` or `question` field
- Backend `_serialize_trade_response()` in `dashboard.py` only returns `market_ticker` and `event_slug`
- Frontend `Trade` type only has `market_ticker` and `event_slug` — no `question`/`title`
- Frontend displays `market_ticker` directly: `TradesTab.tsx:90`, `WinningTradesPreview.tsx:75-76`, `SignalsTab.tsx:88-89`, `ControlRoomTab.tsx:40`, `DecisionsTab.tsx:68-69`
- Some places try `event_slug` as fallback: `TradesTable.tsx:200-201`, `SignalsTable.tsx:69`
- But `event_slug` is often null or also contains IDs like `btc-updown-5m-2180598`
- The `Signal` type DOES have `market_title` field, but `Trade` doesn't — trades lose the title once recorded

**Root cause**: Trade recording only stores `market_ticker`, not the human-readable question. The backend doesn't resolve market_ticker → question on the dashboard API response.

**Fix**:
1. Add `market_question` column to `trades` table, populated when trade is created
2. In dashboard API, resolve `market_ticker` → question from market cache/DB
3. Frontend already truncates long strings — just needs the right data
4. Quick alternative: enrich dashboard response by joining with market data

### F10. Mode Switching Only Filters Client-Side (Not a Real Mode Switch)
**Severity**: P1 — mode switch is cosmetic only
**Evidence**:
- `ModeSelector.tsx` — calls `setSelectedMode(key)` which updates `localStorage`
- `ModeFilterContext.tsx` — pure React state + localStorage, no API interaction
- `Dashboard.tsx` — `fetchDashboard` call has NO mode parameter, always fetches ALL data
- Components like `OverviewTab.tsx`, `PerformanceTab.tsx`, `TradesTab.tsx` just filter client-side:
  ```tsx
  const filtered = selectedMode === 'all' ? data : data.filter(t => t.trading_mode === selectedMode)
  ```
- The API endpoint `/api/v1/dashboard` returns all modes at once (paper + live stats combined)
- StatsCards shows mode-specific stats from the combined response: `stats.paperStats`, `stats.liveStats`
- This means switching mode doesn't change WHAT data is fetched, only how it's displayed locally

**This is actually partially correct** — the dashboard API returns all modes' stats in one response (paperStats, liveStats, testnetStats). The mode selector just picks which to display. But the user expects switching mode to change the active trading mode, not just filter the view.

**Fix**:
1. Clarify in UI that mode selector is a "view filter" not "mode switch"
2. OR: Add a separate "Active Trading Mode" control that actually changes backend behavior
3. Some pages (Landing, Activity, MarketIntel) don't respect mode filter at all

### F11. Hardcoded/Static Content in Landing Page
**Severity**: P2 — cosmetic, not functional
**Evidence**:
- `Landing.tsx` — all content is hardcoded in arrays (not fetched from API)
- Text pillars, breakthrough claims, allocation sections are all static
- This is intentional for a landing page, but some values (stats, strategy counts) may be outdated

### F12. No Page Updates After Mode Change on Some Pages
**Severity**: P1 — stale data display
**Evidence**:
- `Activity.tsx`, `MarketIntel.tsx`, `Backtest.tsx`, `EdgeTracker.tsx`, `Settlements.tsx` (standalone pages) — don't import `useModeFilter`
- These pages either show all data regardless of mode, or have their own hardcoded mode logic
- The Dashboard tabs use `useModeFilter` correctly, but standalone pages don't
- If user changes mode in Dashboard then navigates to Activity, the mode is ignored

**Fix**: Apply `useModeFilter` consistently to all pages that display mode-specific data

---

## Revised Priority Execution Order

### Phase 1: Get System Functional (P0 — Immediate)

| # | Task | Impact | Effort |
|---|------|--------|--------|
| 1.1 | Add polyedge entries to CF tunnel config.yml + restart tunnel | Frontend accessible | 5 min |
| 1.2 | Enable general_scanner in DB + verify persistence | Signal generation resumes | 5 min |
| 1.3 | Fix AutoTrader duplicate signal loop — clear consumed signals after processing | AutoTrader can execute again | 30 min |
| 1.4 | Restart bot, verify first trade appears | End-to-end validation | 10 min |

### Phase 2: Fix Monitoring & Display (P1 — Same Day)

| # | Task | Impact | Effort |
|---|------|--------|--------|
| 2.1 | Drop FK constraint on decision_log (or add missing strategy_config rows) | Watchdog alerts work | 15 min |
| 2.2 | Backend: Add market_question resolution to dashboard API (trade_ticker → question) | Trades show readable names | 1 hr |
| 2.3 | Frontend: Display market question instead of ticker in all tables | Trades readable in UI | 30 min |
| 2.4 | Investigate why AGI improvement cycle never fires | AGI can run | 30 min |
| 2.5 | Fix BTC Oracle low confidence — adjust edge calculation or lower threshold | Better signal quality | 30 min |
| 2.6 | Disable strategies with no scheduler jobs in strategy_config | No false heartbeat alerts | 15 min |
| 2.7 | Apply useModeFilter to all standalone pages consistently | Mode filter works everywhere | 30 min |

### Phase 3: Architecture Cleanup (P2 — Next Sprint)

| # | Task | Impact | Effort |
|---|------|--------|--------|
| 3.1 | Move non-strategy files out of `backend/strategies/` | Code clarity | 2 hr |
| 3.2 | Unify strategy config vs scheduler job registration | No orphan strategies | 3 hr |
| 3.3 | Add "Active Trading Mode" backend control vs "View Filter" UI clarity | User clarity | 2 hr |

---

## Questions for User

1. **Phase 1 approval**: Fix P0 issues immediately?
2. **AutoTrader fix approach**: For F3 (duplicate signal loop), should I (a) archive signals after processing, or (b) clear the signal queue each cycle?
3. **BTC Oracle**: Confidence consistently 0.06 vs 0.5 threshold. Lower threshold temporarily, or fix edge calculation first?
4. **Enabled strategies without jobs**: Disable in config until wired up, or add scheduler jobs?
5. **Market title fix**: Add `market_question` column to trades table (migration), or do runtime resolution from market cache?
