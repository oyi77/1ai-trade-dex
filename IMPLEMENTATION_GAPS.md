# Implementation Gaps — PolyEdge Trading Bot

**Last Updated:** 2026-05-20 (Full codebase rescan)
**Previous:** 2026-05-18 (301 findings catalogued)

This file is the single source of truth for what's built vs planned.

---

## CRITICAL — Fix Immediately

### 1. `.env` Injection
- **File:** `.env:188`
- **Issue:** `WEATHER_CITIES=nycINJECTED_KEY=evil` — corrupted weather config
- **Impact:** Weather scanner receives corrupted city list, weather trading produces wrong signals
- **Fix:** Remove `INJECTED_KEY=evil` from WEATHER_CITIES value

### 2. Weak Admin Key
- **File:** `.env:88`
- **Issue:** `ADMIN_API_KEY=BerkahKarya2026` — trivially guessable
- **Impact:** Anyone can access admin endpoints on a live trading system with $136.77
- **Fix:** Generate random 32+ char key

### 3. Silent Exception Swallowing (20+ instances)
- **Files:**
  - `core/decisions.py:82,93,104` — 3x `except Exception: pass` in DB write path
  - `core/risk/safety.py:100` — safety check silently fails
  - `core/risk/risk_manager.py:148` — risk check silently fails
  - `core/risk/crash_guardian.py:68` — crash guardian silent
  - `core/strategy_executor.py:444,589,1298,1510` — 4x trade execution errors swallowed
  - `core/settlement/settlement_helpers.py:187,420,595,685` — 4x settlement errors swallowed
- **Impact:** Trading path can fail silently — risk checks bypassed, settlement errors lost, decisions dropped
- **Fix:** Replace with `logger.exception("context")` in all 12 critical locations

### 4. Risk Manager Returns 0.0 on Error
- **Files:** `core/risk/risk_manager.py:737,986`
- **Issue:** `return 0.0` as error fallback — "zero risk" = "safe to trade"
- **Impact:** If risk calculation fails, trade proceeds with no risk check
- **Fix:** Raise exception or return sentinel value that callers explicitly check

### 5. Unmerged Alembic Heads (3)
- **Heads:** `20260519_merge_and_add_journal`, `wallet_recon_001`, `a1b2c3d4misc0`
- **Issue:** `alembic upgrade head` fails with "Multiple head revisions"
- **Impact:** New migrations cannot be applied cleanly
- **Fix:** Create merge migration combining all 3 heads

---

## HIGH — Fix Soon

### 6. Fake-Async Scheduler Jobs (11+)
- **File:** `core/scheduling/scheduling_strategies.py`
- **Functions:** `settlement_job`, `scan_and_trade_job`, `strategy_cycle_job`, `auto_trader_job`, `auto_redeem_job`, `heartbeat_job`, `verify_settlement_blockchain`, and more
- **Issue:** Declared `async def` but never `await` — synchronous work blocks event loop
- **Impact:** Prevents concurrent job execution, can cause missed timing windows
- **Fix:** Wrap sync DB calls in `asyncio.to_thread()` or register as sync jobs with APScheduler ThreadPoolExecutor

### 7. AGI Event Handlers Fake-Async (18 handlers)
- **File:** `core/agi_event_handlers.py:18-363`
- **Issue:** All 18 handlers (`on_trade_settled`, `on_strategy_killed`, etc.) are `async def` with zero `await` calls
- **Impact:** Event processing blocks event loop
- **Fix:** Same as #6 — wrap or convert to sync

### 8. API Endpoints Return Empty Arrays
- **File:** `api/markets.py:143,185,215,222,262,269,278`
- **Issue:** 7 endpoints return `[]` as fallback when fetch fails
- **Impact:** Dashboard shows "no markets" instead of error state — silent data starvation
- **Fix:** Return HTTP 503 with error message

### 9. Prediction Endpoint Stub
- **File:** `api/market_intel.py:153-156`
- **Issue:** `get_prediction()` passes hardcoded `{"volume": 0}` features — returns fake predictions
- **Impact:** Prediction API returns meaningless data
- **Fix:** Wire real market data features or return 501

### 10. Plaintext Secrets in `.env`
- **Files:** `.env:19,58,81,222,305`
- **Items:** Private key, Groq API key, Telegram bot token, Tavily API key, MiroFish API key
- **Impact:** Secrets exposed if `.env` file is leaked
- **Fix:** Use secrets manager or encrypt `.env` at rest

### 11. `sync_testnet_wallet` No-Op
- **File:** `core/scheduling/scheduling_strategies.py:1082-1085`
- **Issue:** Registered scheduler job does nothing (`logger.debug("skipped"); pass`)
- **Impact:** Testnet wallet never synced
- **Fix:** Remove from scheduler registration or implement

### 12. `llm_cost_tracker` Empty Class
- **File:** `core/llm_cost_tracker.py:122`
- **Issue:** Entire class body is `pass`
- **Impact:** LLM cost tracking not implemented
- **Fix:** Implement or remove

---

## MEDIUM — Fix When Convenient

### 13. Error Masking with Empty Returns (30+ instances)
- **Files:**
  - `core/safe_param_tuner.py:48,54,60,63,82` — 5x `return {}`
  - `core/strategy_performance_tracker.py:147,157,169` — 3x `return {}`
  - `core/knowledge_graph.py` — 20+ `return []` / `return {}`
  - `core/settlement/settlement_helpers.py:1379,1385,1436,1461,1476,1546` — 6x `return []`
- **Impact:** Callers can't distinguish "no data" from "error occurred"
- **Fix:** Return None/raise on errors, empty only for genuine "no results"

### 14. `ensure_schema()` vs Alembic Dual-Path
- **File:** `models/database.py:1972`
- **Issue:** Runtime `ensure_schema()` auto-creates columns bypassing alembic — makes `alembic downgrade` impossible
- **Impact:** Migration chain unreliable for rollback
- **Fix:** Choose one path — either alembic-only or ensure_schema-only

### 15. Missing Provider Environment Variables
- **Providers:** Kalshi (`KALSHI_API_KEY`), Azuro (`AZURO_GRAPH_URL`), SXBet (`SXBET_API_URL`), Limitless (`LIMITLESS_API_URL`)
- **Impact:** Providers don't load at startup, smaller market universe
- **Fix:** Set env vars or remove unused providers

### 16. Empty API Keys
- **Files:** `.env:62` (ANTHROPIC_API_KEY), `.env:223` (EXA_API_KEY), `.env:224` (SERPER_API_KEY)
- **Impact:** Fallback providers fail silently when primary is down
- **Fix:** Set keys or remove fallback paths

### 17. `ValidationStage.record()` Stub
- **File:** `core/execution_pipeline/stages/validate.py:49`
- **Issue:** `record()` is `pass` — validation events never recorded
- **Impact:** No audit trail for validation decisions
- **Fix:** Implement or remove

### 18. `NotifyStage.record()` Stub
- **File:** `core/execution_pipeline/stages/notify.py:51`
- **Issue:** `record()` is `pass` — notification events never recorded
- **Impact:** No audit trail for notifications
- **Fix:** Implement or remove

---

## FEATURE FLAGS (Design Decisions)

| Flag | Default | .env | Impact |
|------|---------|------|--------|
| `AGI_AUTO_PROMOTE` | `False` | `true` | AGI can't promote strategies — overridden in prod |
| `AGI_AUTO_ENABLE` | `False` | `true` | AGI can't re-enable — overridden in prod |
| `AGI_BANKROLL_ALLOCATION_ENABLED` | `False` | `true` | Bankroll allocation disabled — overridden |
| `EVOLUTION_ENGINE_ENABLED` | `False` | `true` | DEAP evolution disabled — overridden |
| `LONGSHOT_BIAS_ENABLED` | `False` | not set | Longshot strategy disabled |
| `KALSHI_ENABLED` | `False` | `true` | Kalshi disabled — overridden |
| `REDIS_ENABLED` | `False` | not set | Redis caching disabled |
| `AUTO_REDEEM_ENABLED` | not checked | not set | Auto-redeem disabled |
| `POLYMARKET_USER_WS_ENABLED` | `False` | not set | WebSocket disabled |

---

## FIXED THIS SESSION (2026-05-20)

| Gap | Fix | Commit |
|-----|-----|--------|
| Risk manager drawdown bug (treated gains as losses) | Added `strat_dd < 0` guard | `0e808e4` |
| wallet_reconciler coroutine warning | Use `await` instead of `to_thread` | `098f85f` |
| wallet_reconciler equity.total type error | Returns float, not object | `a619be0` |
| AGI self-tuner disabled by SHADOW_MODE | Added `AGI_SELF_TUNE_IN_PAPER` flag | `6ae8454` |
| Evolution loop not scheduled | Added to scheduler every 4h | `6ae8454` |
| `_find_experiment` bug | Query DB instead of running experiment | `6ae8454` |
| Backtest gate auto-passes | Fails on no data | `6ae8454` |
| CognitiveCore uses MockCore | OneAIHubCore with DegradedCore fallback | `6ae8454` |
| Graduated rehab missing | 25%→50%→75%→100% allocation | `6ae8454` |
| Live trades not verified on-chain | CLOB verification + activity API | `6ae8454` |
| Imported data polluting aggregates | Source filter in ranker + registry | `6ae8454` |
| Wallet reconciliation disabled | Async wrapper, 5min scheduler job | `f2d9a93` |
| WR kill threshold 5% | New WinRateMonitor with 50% threshold | `f2d9a93` |
| No process lock | fcntl lock in __main__.py | `f2d9a93` |
| Scheduler last_run never updated | APScheduler event listener | `f2d9a93` |
| Vilona report stale data | Uses fetch_pm_total_equity() | `f2d9a93` |

---

## RECOMMENDED FIX ORDER

| Phase | Fix | Risk | Effort |
|-------|-----|------|--------|
| 1 | `.env` injection (#1) | Critical | 1 min |
| 1 | Rotate admin key (#2) | Critical | 1 min |
| 1 | Merge alembic heads (#5) | Critical | 10 min |
| 2 | `except: pass` → `logger.exception()` (#3) | High | 30 min |
| 2 | Risk manager error sentinel (#4) | High | 15 min |
| 3 | API error states (#8) | Medium | 20 min |
| 3 | Prediction endpoint (#9) | Medium | 15 min |
| 4 | Scheduler async wrapping (#6, #7) | Medium | 1h |
| 5 | Error masking cleanup (#13) | Low | 2h |
