# Implementation Gaps — PolyEdge Trading Bot

**Last Updated:** 2026-05-08 (Round 11 — SQLite concurrency PRAGMAs and BotState mutex; Known Gaps section below remains active)

This file is the single source of truth for what's built vs planned. Every future agent must
read this before proposing work — avoid re-litigating already-completed items.

Format: 
- **Fixed** (YYYY-MM-DD): one-line of what was built and which files changed.
- **Known Gaps**: items not yet implemented.
- **Intentionally De-Scoped**: items we consciously chose not to do (with reason).

---

## Fixed

~~**SSE/WebSocket auth bypass when token omitted**~~ → **Fixed** (2026-05-07): Realtime auth now requires either a valid admin cookie session or legacy `token=ADMIN_API_KEY`. Added centralized `authorize_realtime_access()` in `backend/api/auth.py`; wired into `backend/api/events/sse_router.py` and all secured WS routes in `backend/api/websockets_routes.py`.

~~**Cookie auth incompatible with realtime query-token contract**~~ → **Fixed** (2026-05-07): Frontend realtime clients now use cookie-authenticated connections (`EventSource(..., { withCredentials: true })`) and no longer append auth tokens to SSE/WS URLs in `frontend/src/hooks/useTradeEvents.ts`, `frontend/src/hooks/useSSEEvents.ts`, `frontend/src/hooks/useStats.ts`, and `frontend/src/api.ts`.

~~**Queue backend contract mismatch (RedisQueue sync methods vs async worker)**~~ → **Fixed** (2026-05-07): `RedisQueue` methods are now async and compatible with `Worker` awaits; `scheduler.py` now uses `create_queue()` and skips local worker loop for Redis/arq mode while preserving APScheduler execution.

~~**Health endpoint duplicated Redis/CLOB/heartbeat checks**~~ → **Fixed** (2026-05-07): De-duplicated `/api/v1/health` in `backend/api/main.py` to perform single-pass dependency checks.

~~**Market scanner hard-coded `max_pages=5`**~~ → **Fixed** (2026-05-07): Scanner pagination now derives from `SCANNER_PAGE_SIZE` + `SCANNER_MAX_MARKETS`/`limit` in `backend/core/market_scanner.py`.

~~**Email notifications throw NotImplementedError at runtime**~~ → **Fixed** (2026-05-07): `notification_router._send_email()` now logs explicit de-scoped warning and safely drops message without raising.

~~**SQLite BotState race condition — concurrent read-modify-write lost updates**~~ → **Fixed** (2026-05-08): Added `botstate_mutex = asyncio.Lock()` in `backend/models/database.py` exported alongside `for_update()`. `strategy_executor.py` now re-reads fresh BotState inside the mutex before bankroll mutation. `settlement.py:update_bot_state_with_settlements()` fully wrapped in mutex. Also added performance PRAGMAs: `cache_size=-64000` (64MB), `mmap_size=268435456` (256MB), `wal_autocheckpoint=1000`, `temp_store=MEMORY`, `foreign_keys=ON`. Addresses the BotState race from THREAD_ASYNC_SAFETY_AUDIT.md P0 finding.

~~**Duplicate SSE endpoint definitions in two routers**~~ → **Fixed** (2026-05-07): Removed fallback SSE endpoint from `backend/api/websockets_routes.py`; channel-aware SSE router remains canonical source.

~~**Kalshi arbitrage scaffold registered despite non-functional run_cycle**~~ → **Fixed** (2026-05-07): Removed `backend.modules.arbitrage.kalshi_arb` from auto-loading registry until implementation is production-ready.

~~**No autonomous experiment lifecycle** — strategies existed as code but had no automated promotion/demotion pipeline; paper→live required manual intervention every time; no retirement mechanism for losing strategies.~~ → **Fixed** (2026-05-03): Added full autonomy loop: `backend/core/autonomous_promoter.py` implements DRAFT→SHADOW→PAPER→LIVE_PROMOTED→RETIRED lifecycle with promotion thresholds and health-based kill checks; `backend/core/bankroll_allocator.py` computes daily capital allocation via `StrategyRanker.auto_allocate()` and persists to `BotState.misc_data`; `backend/core/trade_forensics.py` analyzes losing trades for root causes; `backend/core/strategy_health.py` (`StrategyHealthMonitor.assess`) computes win rate, Sharpe, drawdown, Brier, PSI and auto-disables killed strategies. Wired into `backend/core/scheduler.py` as `autonomous_promotion_job` (every 6h) and `bankroll_allocation_job` (daily). Integration tests in `backend/tests/test_autonomy_loop_integration.py` validate complete pipeline.

~~**Promoter missing LIVE_PROMOTED evaluation** — after promotion to live, experiments were never checked for kill/retirement, causing live strategies to run forever even if health deteriorated.~~ → **Fixed** (2026-05-03): Added LIVE evaluation block in `autonomous_promoter.py:215-230`. `StrategyHealthMonitor.assess()` now runs on `LIVE_PROMOTED` experiments; `status="killed"` → `RETIRED`.

~~**TradeForensics referenced non-existent column** — `analyze_losing_trade()` used `trade.exit_price` which doesn't exist in Trade schema (uses `settlement_value`).~~ → **Fixed** (2026-05-03): `backend/core/trade_forensics.py:61-74` replaced `exit_price` with `settlement_value` context; used safe `getattr(trade, "strategy", None)` for optional fields.

~~**Tests used stale Trade schema** — integration tests created `Trade` with `exit_price`, `exchange`, `strategy`, `order_id` columns not present.~~ → **Fixed** (2026-05-03): `backend/tests/test_autonomy_loop_integration.py` corrected: Trade creation uses actual columns (`settled`, `settlement_value`, `pnl`, `result`); tests marked `@pytest.mark.asyncio`; assertions aligned with actual return return dict keys; `BankrollAllocator` calls `run_once()` not `allocate_daily_capital()`.

~~**Timezone handling bugs in promoter** — naive datetime subtraction raised errors in `_check_shadow_criteria` and paper retirement age calculation.~~ → **Fixed** (2026-05-03): Added `.replace(tzinfo=timezone.utc)` guards before naive-aware subtraction.

~~**Registry import typo** — promoter imported `_registry` instead of `STRATEGY_REGISTRY`.~~ → **Fixed** (2026-05-03): `from backend.strategies.registry import STRATEGY_REGISTRY`.

~~**StrategyPerformanceRegistry missing** — No centralized `StrategyReport` store with per-strategy metrics updated after each settlement.~~ → **Fixed** (2026-05-03): `backend/core/strategy_performance_registry.py` implements `StrategyPerformanceRegistry` singleton with `StrategyReport` dataclass, DB persistence via `StrategyPerformanceSnapshot` ORM, wired into `settlement_helpers.py`. Tests in `backend/tests/test_strategy_performance_registry.py`.

~~**TransactionEvent model missing** — No ledger for deposits/withdrawals/settlements across paper/live/testnet modes.~~ → **Fixed** (2026-05-03): Added `TransactionEvent` model to `backend/models/database.py` with emission hooks in `settlement_helpers.py` (settlement events) and `bankroll_reconciliation.py` (reconciliation adjustments).

~~**Experiment FK missing** — `Experiment.strategy_name` had no foreign key to `StrategyConfig`.~~ → **Fixed** (2026-05-03): Added `ForeignKey("strategy_config.strategy_name", ondelete="CASCADE")`.

~~**Auto-enable strategy scheduling unverified** — `_enable_strategy()` may have fired `schedule_strategy()` before DB commit.~~ → **Fixed** (2026-05-03): Verified `db.commit()` happens BEFORE `schedule_strategy()` call; integration test asserts scheduling invocation.

~~**Risk Profile not implemented** — ADR-005 defined safe/normal/aggressive/extreme profiles but no code existed; `RISK_PROFILE` not in config.~~ → **Fixed** (2026-05-03): `backend/core/risk_profiles.py` implements four static profiles as preset overlays for runtime settings; `apply_profile()` mutates settings and persists to `.env`; API endpoints `GET/PUT /api/v1/settings/risk/profile`; tests in `backend/tests/test_risk_profiles.py`.

~~**Bankroll allocation not enforced** — `BankrollAllocator` computed per-strategy budgets but `RiskManager.validate_trade` didn't use them.~~ → **Fixed** (2026-05-03): Added `strategy_name` param to `validate_trade()`; new `_strategy_allocation_cap()` method fetches allocation from `BotState.misc_data` and caps trade size to remaining budget; `strategy_executor.py` passes `strategy_name`; tests in `backend/tests/test_allocation_enforcement.py`.

~~**TradeForensics missing timedelta import** — `analyze_recent_losses()` crashed with `NameError` on `timedelta` reference.~~ → **Fixed** (2026-05-03): Added `timedelta` to datetime import in `backend/core/trade_forensics.py:10`.

~~**Promoter operator precedence crash** — `(datetime.now() - exp.promoted_at or exp.created_at).days` evaluated as `(datetime.now() - None)` when `promoted_at` is null → `TypeError`.~~ → **Fixed** (2026-05-03): Added None guard with `ref_time` extraction in `autonomous_promoter.py` shadow/paper/live evaluation loops.

~~**ExperimentRecord missing strategy_name FK** — Promoter used `exp.name` (free-text) as strategy identifier for health checks and `_enable_strategy`, causing mismatches.~~ → **Fixed** (2026-05-03): Added `strategy_name = Column(String, ForeignKey(...))` to `ExperimentRecord` in `kg_models.py`; promoter uses `exp.strategy_name or exp.name`.

~~**StrategyOutcome table never populated** — `strategy_health.py:assess()` queries `StrategyOutcome` for kill/warn decisions, but no code path wrote rows to it.~~ → **Fixed** (2026-05-03): Added `StrategyOutcome` emission hook in `settlement_helpers.py` after each settlement (guarded by `if trade.strategy`).

~~**StrategyPerformanceRegistry PSI from empty table** — `compute_psi(strategy, session)` queried empty `StrategyOutcome` so PSI was always 0.0.~~ → **Fixed** (2026-05-03): Replaced with inline PSI computation from Trade data (recent 30 vs previous 30) in `strategy_performance_registry.py:261-289`.

~~**Settlement double-processing** — `process_settled_trade` had no idempotency guard; crash+restart could cause duplicate StrategyOutcome rows, double-counted PnL, duplicate broadcasts.~~ → **Fixed** (2026-05-03): Added early return if `trade.settled and trade.pnl is not None` in `settlement_helpers.py:957`.

~~**auto_disable_losing_strategies mixed trading modes** — Queried trades without `trading_mode` filter; paper losses could disable live strategies and vice versa.~~ → **Fixed** (2026-05-03): Added `Trade.trading_mode == current_mode` filter in `scheduler.py:auto_disable_losing_strategies`.

~~**AGI_STRATEGY_HEALTH_ENABLED never enforced** — Config flag existed but no production code checked it; health monitoring always ran.~~ → **Fixed** (2026-05-03): Promoter now checks `getattr(settings, "AGI_STRATEGY_HEALTH_ENABLED", True)` before creating `StrategyHealthMonitor`; returns benign defaults when disabled.

~~**auto_allocate doesn't redistribute capped excess** — When a strategy hit the 50% cap, the excess was lost rather than redistributed to other strategies.~~ → **Fixed** (2026-05-03): `strategy_ranker.py:auto_allocate` now redistributes excess from capped strategies proportionally to uncapped ones in a second pass.

~~**Bankroll allocator didn't filter BotState by mode** — Queried `BotState.first()` without mode filter, potentially using wrong mode's bankroll for allocation.~~ → **Fixed** (2026-05-03): `bankroll_allocator.py` now queries `BotState.filter_by(mode=settings.TRADING_MODE).first()` with fallback to `.first()`.

~~**Rejection learner treated JSON string as dict** — `cfg.params` is a Text/JSON column stored as string; rejection_learner accessed `.get()` directly on it, which would raise `AttributeError` at runtime.~~ → **Fixed** (2026-05-03): Added `json.loads()` parsing in `rejection_learner.py:157` with fallback to empty dict.

~~**StrategyRanker.disable_underperformers didn't pass trading_mode** — Same pattern as auto_disable_losing_strategies; could disable strategies based on wrong mode's data.~~ → **Fixed** (2026-05-03): Added `trading_mode` parameter to `disable_underperformers()`, passed from `strategy_ranking_job` via `settings.TRADING_MODE`.

~~**OnlineLearner bypassed AGI_STRATEGY_HEALTH_ENABLED flag** — `online_learner.py` called `_health_monitor.assess()` unconditionally on every settlement, killing strategies even when the feature flag was disabled.~~ → **Fixed** (2026-05-03): Added `_health_enabled()` helper that checks `settings.AGI_STRATEGY_HEALTH_ENABLED`; health assess calls in `on_trade_settled()` and `run_cycle()` now gated by this check.

~~**Duplicate StrategyOutcome rows per settlement** — Both `OnlineLearner.on_trade_settled()` → `record_outcome()` AND `settlement_helpers.py` direct emission created StrategyOutcome rows for the same trade, doubling health metrics.~~ → **Fixed** (2026-05-03): Removed direct StrategyOutcome emission from `settlement_helpers.py`; `record_outcome()` via `OnlineLearner` is the single source of truth for outcome recording.

~~**self_review.py treated StrategyConfig.params JSON string as dict** — `_generate_proposals_for_bleeders` called `.items()` on `cfg.params` without parsing JSON, causing AttributeError on proposal generation.~~ → **Fixed** (2026-05-03): Added `json.loads()` with fallback for string-typed params.

~~**GET /api/learning/health endpoints disabled strategies as side effect** — `StrategyHealthMonitor.assess()` both computes metrics AND disables killed strategies. GET endpoints triggered this on every dashboard health check.~~ → **Fixed** (2026-05-03): Added `readonly` parameter to `assess()`; API endpoints now pass `readonly=True` to compute metrics without side effects.

~~**trade_forensics.py loss streak query used wrong direction** — `Trade.timestamp >= trade.timestamp` counted future (non-existent) losses instead of preceding losses. Loss streak detection was non-functional.~~ → **Fixed** (2026-05-03): Changed to `<=` with 24-hour lookback window for correct streak detection.

~~**No HistoricalDataCollector** — No collector for BTC candles, weather history, market outcomes. Backtest used unit-test data only.~~ → **Fixed** (2026-05-03): Added `backend/core/historical_data_collector.py` with `HistoricalDataCollector` class that collects BTC candles from Binance, settled market outcomes from Gamma API, and weather snapshots from Open-Meteo. ORM models in `backend/models/historical_data.py` (`HistoricalCandle`, `MarketOutcome`, `WeatherSnapshot`). Scheduled as `historical_data_collection_job` every 6h.

~~**No Fronttest validation** — Parameter changes went to live without a paper-trial gate.~~ → **Fixed** (2026-05-03): Added `backend/core/fronttest_validator.py` with `FronttestValidator` class. Validates that executed proposals survive a 14-day paper-trial period with minimum 10 trades and ≥40% win rate before allowing live deployment. Config: `AGI_FRONTTEST_DAYS`, `AGI_FRONTTEST_MIN_TRADES`.

~~**No AGI health check** — No scheduled job validating strategy health, data freshness, budget exhaustion, orphaned positions, scheduler liveness.~~ → **Fixed** (2026-05-03): Added `backend/core/agi_health_check.py` with `AGIHealthChecker` running 5 checks: strategy staleness, data freshness (<24h), budget status, scheduler liveness, orphaned positions (>7d unsettled). Scheduled as `agi_health_check_job` every 15 minutes.

~~**No nightly review** — No daily markdown log writer; no base rate calibration or improvement plan.~~ → **Fixed** (2026-05-03): Added `backend/core/nightly_review.py` with `NightlyReviewWriter` generating `docs/agi-log/YYYY-MM-DD.md` containing daily summary, strategy performance (7-day), model calibration, and improvement plan with pending proposals + disabled strategies. Scheduled as `nightly_review_job` at configurable hour.

~~**No strategy rehabilitation** — No automated pipeline to re-enable suspended strategies after validation.~~ → **Fixed** (2026-05-03): Added `backend/core/strategy_rehabilitator.py` with `StrategyRehabilitator`. Re-enables disabled strategies after 7-day cooldown if recent trades show ≥50% win rate and positive PnL. Scheduled as `strategy_rehabilitation_job` daily.

~~**TradeForensics not integrated into AGI improvement** — Forensics ran on losses but didn't feed patterns back into proposals.~~ → **Fixed** (2026-05-03): Added `backend/core/forensics_integration.py` with `generate_forensics_proposals()`. Groups losses by strategy over 7 days, creates `StrategyProposal` entries for strategies with ≥5 losses. Scheduled as `forensics_integration_job` daily.

~~**.env.example missing RISK_PROFILE and AGI flags** — New config fields not documented.~~ → **Fixed** (2026-05-03): Added `RISK_PROFILE`, `AGI_HEALTH_CHECK_*`, `AGI_NIGHTLY_REVIEW_*`, `AGI_REHABILITATION_ENABLED`, `AGI_FRONTTEST_*`, `HISTORICAL_DATA_COLLECTOR_*` sections to `.env.example`.

~~**Hardcoded API base URLs across 30+ backend files** — Polymarket Gamma, Data, CLOB, Kalshi, Goldsky, Binance, Coinbase, Kraken, Bybit, CoinGecko, Open-Meteo, NWS URLs were hardcoded string constants.~~ → **Fixed** (2026-05-03): Added 20+ config fields to `backend/config.py` (`GAMMA_API_URL`, `DATA_API_URL`, `CLOB_API_URL`, `POLYMARKET_BASE_URL`, `KALSHI_API_URL`, `GOLDSKY_API_URL`, `BINANCE_API_URL`, `COINBASE_API_URL`, `KRAKEN_API_URL`, `BYBIT_API_URL`, `COINGECKO_API_URL`, `OPEN_METEO_API_URL`, `OPEN_METEO_ARCHIVE_URL`, `NWS_API_URL`, `NWS_BASE_URL`, `BINANCE_KLINES_URL`, `RESEARCH_RSS_FEEDS`). All 30+ files updated to read from settings. Commit `cf46a76`.

~~**Hardcoded frontend polling intervals** — 55 `refetchInterval` values across 35 .tsx files were hardcoded milliseconds.~~ → **Fixed** (2026-05-03): Created `frontend/src/polling.ts` with `POLL.FAST` (2s), `POLL.NORMAL` (10s), `POLL.SLOW` (30s), `POLL.VERY_SLOW` (60s) constants configurable via `VITE_POLL_*_MS` env vars. All 35 files updated. MiroFish hardcoded ports (5001/3200) now read from `VITE_MIROFISH_*` env vars. Commit `cf46a76`.

~~**Remaining hardcoded URLs in 17+ backend files** — First pass missed wallet_reconciliation, bankroll_reconciliation, auto_redeem, position_valuation, whale_discovery, WebSocket clients (5 files), weather geocoding/ensemble, web search providers, mirofish_client, CLOB book/midpoint URLs, historical_data_collector, heartbeat Telegram URL.~~ → **Fixed** (2026-05-03): Added 16 more config fields to `backend/config.py` (`POLYMARKET_RELAYER_URL`, `POLYMARKET_WS_CLOB_URL`, `POLYMARKET_WS_USER_URL`, `POLYMARKET_WS_RTDS_URL`, `POLYMARKET_WS_WHALE_URL`, `POLYMARKET_WS_ORDERBOOK_URL`, `QUICKNODE_RPC_URL`, `OPEN_METEO_ENSEMBLE_URL`, `OPEN_METEO_GEOCODING_URL`, `TELEGRAM_API_BASE`, `MIROFISH_API_URL`, `TAVILY_API_URL`, `EXA_API_URL`, `SERPER_API_URL`, `DDG_HTML_URL`, `POLYMARKET_WS_RTDS_URL`). All 22 files updated. Commit `78c1a3a`.

~~**Hardcoded trading parameter: MIN_ORDER_USDC = 5.0** — Critical business logic constant embedded in `polymarket_clob.py`.~~ → **Fixed** (2026-05-03): Added `MIN_ORDER_USDC` and `PAPER_MIN_ORDER_USDC` to config, converted `polymarket_clob.py` and `strategy_executor.py` to use `_cfg()` pattern. Commit `1c6dd32`.

~~**Hardcoded safe_param_tuner thresholds** — `MAX_CHANGE_PCT`, `MIN_TRADES_FOR_TUNING`, `REVERT_SIGMA_THRESHOLD` were constants.~~ → **Fixed** (2026-05-03): Added `SAFE_TUNER_MAX_CHANGE_PCT`, `SAFE_TUNER_MIN_TRADES_FOR_TUNING`, `SAFE_TUNER_REVERT_SIGMA_THRESHOLD` to config, converted `safe_param_tuner.py` to read from settings. Commit `1c6dd32`.

~~**Hardcoded HFT risk limits: POSITION_SIZE_PCT and MAX_POSITION_USD** — HFT risk manager had hardcoded position size percentage and max position cap.~~ → **Fixed** (2026-05-03): Added `HFT_POSITION_SIZE_PCT` and `HFT_MAX_POSITION_USD` to config, converted `risk_manager_hft.py` to use `_cfg()` pattern. Commit `1c6dd32`.

---

## Known Gaps

**Catalogued Gaps**: 85 gaps documented. **~72 Fixed/Verified** (2026-05-04), **~13 De-Scoped** (require schema migrations / architectural refactors).

### AGI Autonomous Strategy Lifecycle — 8 Critical Gaps

These gaps directly block the vision of unlimited paper experimentation → continuous learning → temporary live trial → auto-demotion/promotion. Read in order — they form a dependency chain.

**Audit Reports** (saved in project root for reference):
- `SECURITY_AUDIT_REPORT.md` — Secrets exposure analysis (10 secrets in 2 files)
- `ERROR_HANDLING_GAPS.md` — 82 locations with bare except: pass (60 production files)
- `THREAD_ASYNC_SAFETY_AUDIT.md` — 2 P0 race conditions, 2 P1, 3 P2
- `NETWORK_RESILIENCE_AUDIT.md` — 3 critical (sync timeout, 2× WebSocket pings), 18 medium (AsyncClient timeout consistency), 6 unprotected APIs
- `N1_QUERY_AUDIT.md` — N+1 query patterns across API layer
- `PERFORMANCE_AUDIT_SUMMARY.md` — Cache, concurrency, and DB performance gaps
- `README_AUDIT.md` — Root README documentation gaps and outdated sections
- **New (this session):**
  - **WebSocket Keep-Alive Audit** — 2 critical heartbeat gaps (polygon_listener.py:33, polymarket_websocket.py:207)
  - **Global Mutable State Inventory** — 5 HIGH-severity race conditions in scheduler, auto_improve, calibration, heartbeat
  - **Database Schema Constraints Map** — 10 missing strategy FKs, 0 CHECK constraints, missing composite indexes
  - **Prometheus Metrics Coverage Inventory** — 12 critical blind spots (trade execution, risk, settlement, circuit breaker state, DB queries)
  - **API Endpoint Security Audit** — 2 CRITICAL unauthenticated endpoints, 12 HIGH admin gaps, 0 per-endpoint rate limits
  - **CircuitBreaker Usage Verification** — 6 of 7 data-layer HTTP calls unprotected (14% coverage)
- **Database Session Management Audit** — 108/189 (57.7%) SessionLocal() instantiations unchecked; 1 returned without close; risk of connection pool exhaustion
  - **DB Session Management Audit** — 108/189 (57.7%) SessionLocal() instantiations unchecked, risk of connection leaks
  - **AGI Lifecycle Audit** — 8 critical gaps mapped end-to-end: missing time_horizon/risk_tier classification, no LIVE_TRIAL phase, broken demotion→improvement loop, stub strategy synthesis, fake shadow results, silent error swallowing in AGI cycle, forensics dead-end for broken strategies, single-param rollback bottleneck
  - **Strategy Implementation Audit** — 13 bugs across 24 strategy files: unimplemented strategies, negative-EV strategies registered, race conditions in copy_trader/realtime_scanner/whale_frontrun, silent failures in whale_pnl_tracker, unpersisted weather calibration, inventory validation gaps, semaphore leaks
  - **AI/ML Pipeline Audit** — 4 gaps: probability bounds unenforced, online learner feedback loop read-only, calibration drift without retraining, knowledge graph write-only
  - **Data Pipeline Audit** — 4 gaps: WebSocket reconnection without state recovery, stale cache without freshness check, scanner pagination hard-coded at 5 pages, Polygon listener permanent failure
  - **Scheduler/Job Queue Audit** — 7 gaps: stale job recovery missing, SQLite queue race condition, NULL idempotency bypass, no poison message handling, in-memory job store crash loss, worker memory leak, undifferentiated handler exceptions
  - **API/Frontend Security Audit** — 4 gaps: CORS wildcard methods, API key in localStorage, error details in 500s, WebSocket no rate limit
  - **Config Validation Audit** — 2 gaps: hardcoded admin API key default, no upper bound on AI_SIGNAL_WEIGHT/KELLY_FRACTION

---

**[AGI-1] No strategy time_horizon or risk_tier classification — single generic `category` column** — `StrategyConfig` model (`backend/models/database.py:463`) has only `category = Column(String, nullable=True)` with no schema enforcement. User requires two orthogonal dimensions: (a) time_horizon = short/mid/long, (b) risk_tier = safe/conservative/moderate/aggressive/extreme/crazy. Without these, bankroll allocation cannot be tier-aware (aggressive strategies should get smaller allocation), paper experiments cannot be unlimited for crazy-tier (currently fronttest gate applies uniformly to all), and risk_profiles.py presets (safe/normal/aggressive/extreme) are global only — not per-strategy. The `risk_profiles.py` PRESETS dict (line 76-109) has 4 tiers but user wants 6 (add conservative, crazy). Needs: (1) Add `time_horizon` and `risk_tier` columns to StrategyConfig, (2) Add "conservative" and "crazy" risk profile presets, (3) BankrollAllocator must read risk_tier to scale allocation (crazy=1% bankroll max, safe=up to 50%), (4) Fronttest gate relaxed for crazy-tier paper experiments. Severity: **CRITICAL** — blocks tiered experimentation. Affects: `backend/models/database.py:463`, `backend/core/risk_profiles.py:76-109`, `backend/core/bankroll_allocator.py`, `backend/core/fronttest_validator.py`.

**[AGI-2] No temporary live trial phase — promoter jumps PAPER→LIVE_PROMOTED directly** — `autonomous_promoter.py` lifecycle is DRAFT→SHADOW→PAPER→LIVE_PROMOTED→RETIRED. There is no LIVE_TRIAL phase between PAPER and LIVE_PROMOTED. User's vision requires: paper-proven strategy → temporary live trial (e.g., 7 days with 1% bankroll) → measure live-vs-paper performance gap → if degraded, demote back to paper for improvement; if good, promote to permanent live with full allocation. Currently, `experiment_runner.py:153-178` promotes shadow→paper only; the autonomous_promoter's `_check_paper_criteria` jumps straight to LIVE_PROMOTED. Needs: (1) Add `LIVE_TRIAL` to ExperimentStatus enum in `agi_types.py`, (2) Add `LIVE_TRIAL_BANKROLL_PCT` config (default 0.01), (3) Promoter demotes LIVE_TRIAL→PAPER on degradation instead of RETIRED, (4) Only promote LIVE_TRIAL→LIVE_PROMOTED after trial period passes. Severity: **CRITICAL** — blocks safe live testing. Affects: `backend/core/autonomous_promoter.py`, `backend/core/experiment_runner.py`, `backend/core/agi_types.py`.

**[AGI-3] No live degradation detection with demotion-to-paper — killed strategies go to RETIRED, never rehabilitated via learning** — `strategy_health.py:StrategyHealthMonitor.assess()` issues `status="killed"` which `autonomous_promoter.py` translates to RETIRED (line 215-230). `strategy_rehabilitator.py` only re-enables after cooldown if win_rate ≥50% — but it re-enables at the SAME config that failed, with no improvement loop. User's vision: degraded live strategy → demote to paper → forensics analysis → parameter tuning → re-validate on paper → re-trial on live. The pieces exist separately (forensics_integration.py creates proposals, auto_improve.py tunes params, fronttest_validator.py validates) but they are NOT connected in a demotion→improvement→re-promotion pipeline. Needs: (1) `autonomous_promoter.py` should demote killed LIVE_PROMOTED→PAPER (not RETIRED), (2) Demotion triggers forensics_integration + auto_improve, (3) Improved config gets new ExperimentRecord at DRAFT→SHADOW→PAPER cycle, (4) Only RETIRE if improvement fails after N attempts. Severity: **CRITICAL** — broken learning loop. Affects: `backend/core/autonomous_promoter.py:215-230`, `backend/core/strategy_health.py`, `backend/core/strategy_rehabilitator.py`, `backend/core/forensics_integration.py`.

**[AGI-4] StrategySynthesizer generates stub code — run() returns empty list** — `strategy_synthesizer.py:84-90` generates strategy code with `return []` as the signal generation body. The "strategy" is just a template with a description comment, no actual signal logic. For true AGI self-improvement, the synthesizer needs to: (1) use LLM to generate actual signal logic from the description, (2) validate via backtest before paper deployment, (3) incorporate knowledge graph context (passed as `kg_context` param but never used at line 71). Currently generates non-functional strategies that waste experiment slots. Severity: **HIGH** — AGI cannot create new profitable strategies. Affects: `backend/core/strategy_synthesizer.py:70-102`.

**[AGI-5] ExperimentRunner.run_shadow_experiment fakes results** — `experiment_runner.py:92-94` computes `trades = duration_days * 10` and `win_rate = 0.50` with `pnl = trades * 5.0` — all hardcoded, no actual shadow execution. The shadow phase is supposed to generate real signals without executing, but ExperimentRunner never connects to the strategy runner. This means shadow→paper promotion in `evaluate_experiment()` (line 109-151) validates against fake data. Severity: **HIGH** — shadow validation is non-functional. Affects: `backend/core/experiment_runner.py:75-107`.

**[AGI-6] AGI improvement cycle (agi_improvement_cycle_job) has 7 try/except blocks that swallow all errors** — `agi_orchestrator.py:297-398` runs feedback measurement, meta-learning, evolution, proposals, replacement, composition, and counterfactual scoring — but each stage is wrapped in bare `except Exception as e: stats["errors"].append(...)` with no re-raise. If any stage fails silently (e.g., feedback_tracker import error), downstream stages proceed with stale/missing data. The entire improvement cycle can complete with 0 real actions taken while reporting success. Severity: **HIGH** — silent AGI loop failure. Affects: `backend/core/agi_orchestrator.py:297-398`.

**[AGI-7] Forensics→improvement pipeline loses fundamentally-broken strategies** — `forensics_integration.py:66-73` marks strategies with 0% win rate over 30+ trades as `fundamentally_broken = True` and sets `auto_promotable = False`. These strategies get a proposal with "FUNDAMENTALLY BROKEN (staying killed)" but no follow-up action. They are permanently excluded from the improvement loop. User's vision requires even broken strategies to get a second chance via parameter overhaul. The check at line 98 `_has_active_experiment()` prevents creating new experiments for strategies that already have one — but retired experiments from broken strategies persist, blocking re-experimentation. Severity: **MEDIUM** — limits AGI learning scope. Affects: `backend/core/forensics_integration.py:66-73,98`.

**[AGI-8] Auto-improve rollback only tracks ONE parameter change at a time** — `auto_improve.py:42` stores `_last_param_change` as a single dict, not a list. If a second parameter change is applied while the first is still being evaluated, line 282-285 skips the apply entirely ("pending change awaiting rollback review"). This serializes improvements: only one param change per rollback window (ROLLBACK_TRADE_WINDOW=10 trades). For multi-strategy systems with independent params, this artificially limits improvement throughput. Severity: **MEDIUM** — slows AGI learning velocity. Affects: `backend/core/auto_improve.py:42,282-285`.

### Strategy Implementation Bugs — 13 Gaps

**[STRAT-1] Kalshi arbitrage strategy registered but not implemented** — `backend/strategies/kalshi_arb.py:58-64` run_cycle() immediately returns `{"error": "Kalshi API integration not yet implemented"}`. Strategy is registered in the registry and receives scheduler cycles but produces zero signals and wastes compute. Either implement the Kalshi cross-platform arb logic or remove from registry. Severity: **MEDIUM** — dead code wasting cycles. Affects: `backend/strategies/kalshi_arb.py:58-64`, `backend/strategies/registry.py`.

**[STRAT-2] BTC Momentum negative EV (-49.5% ROI) still registered and enableable** — `backend/strategies/btc_momentum.py:4-5` documents 4 wins / 11 losses (-49.5% ROI) but the strategy remains in the registry. It can be accidentally enabled via dashboard or config change. Registry.create_strategy() has no minimum performance gate. Severity: **HIGH** — known money-losing strategy can be activated. Affects: `backend/strategies/btc_momentum.py:4-5`, `backend/strategies/registry.py:54-65`.

**[STRAT-3] Copy trader race condition in position tracking** — `backend/strategies/copy_trader.py:75-96` modifies `_tracked` list (append/remove) without asyncio.Lock protection. Multiple concurrent run_cycle() invocations can corrupt the tracked positions list, leading to duplicate trades or missed exits. Leaderboard refresh at line 95-96 has the same race. Severity: **HIGH** — data corruption in concurrent execution. Affects: `backend/strategies/copy_trader.py:75-96,200-240`.

**[STRAT-4] Whale PNL tracker silent failures** — `backend/strategies/whale_pnl_tracker.py:51-82` `_fetch_token_id()` and `_fetch_market_prob()` return None and 0.50 respectively on any error, with no logging. Cascading failures produce signals with zero information value but the strategy continues generating them. Severity: **MEDIUM** — invisible failures produce garbage signals. Affects: `backend/strategies/whale_pnl_tracker.py:51-82,84-107`.

**[STRAT-5] Realtime scanner race condition in PriceHistory deque** — `backend/strategies/realtime_scanner.py:42-88` PriceHistory.prices deque is modified by WebSocket message handlers without locks. Multiple concurrent messages can corrupt velocity calculations. Signal cooldown at line 51-52 is tracked but not enforced (checked but action continues anyway). Severity: **HIGH** — corrupted price data → bad signals. Affects: `backend/strategies/realtime_scanner.py:42-88`.

**[STRAT-6] Weather EMOS CalibrationState not persisted** — `backend/strategies/weather_emos.py:77-98` CalibrationState is in-memory only. Requires 10+ observations to calibrate, but state resets on every bot restart. In practice, the model never reaches calibration minimum. Severity: **HIGH** — weather strategy cannot calibrate. Affects: `backend/strategies/weather_emos.py:77-98`.

**[STRAT-7] General market scanner AI check happens after API calls** — `backend/strategies/general_market_scanner.py:266-271` checks `client.is_enabled` AFTER fetching markets and making API calls. If AI is disabled, all the API work was wasted. Should check at the start of run_cycle(). Also, disabled strategies still generate signals at line 22 because only client-level check exists, not strategy-level enabled check. Severity: **MEDIUM** — wasted API quota. Affects: `backend/strategies/general_market_scanner.py:22,266-271`.

**[STRAT-8] Market maker no inventory validation** — `backend/strategies/market_maker.py:45-85` calculate_spread() doesn't validate inventory_pct range. Can produce negative spreads or invalid prices. quote_size at line 69 not validated > 0. Severity: **HIGH** — can create money-losing quotes. Affects: `backend/strategies/market_maker.py:45-85`.

**[STRAT-9] Bond scanner concurrent position limit not enforced** — `backend/strategies/bond_scanner.py:94-110` reads max_concurrent_bonds param but never checks current open positions against it. Can open unlimited positions, depleting bankroll. Days to resolution at line 63-64 stored as floats instead of timedelta. Severity: **MEDIUM** — position limit bypass. Affects: `backend/strategies/bond_scanner.py:63-64,94-110`.

**[STRAT-10] Probability arb semaphore not released on exception** — `backend/strategies/probability_arb.py:23,95` execution breaker semaphore acquired but not released in exception path. After an error, the semaphore remains locked, blocking all future arbitrage execution. Size hardcoded at line 101, 110 instead of using Kelly or config. Severity: **HIGH** — deadlocks arbitrage execution. Affects: `backend/strategies/probability_arb.py:23,95,101,110`.

**[STRAT-11] Cross-market arb circuit breakers defined but never used** — `backend/strategies/cross_market_arb.py:28-29` defines circuit breaker thresholds (CIRCUIT_BREAKER_THRESHOLD=5, CIRCUIT_BREAKER_TIMEOUT=60.0) but never checks them in execution. Consecutive failures accumulate without triggering protection. Severity: **MEDIUM** — unprotected cascade risk. Affects: `backend/strategies/cross_market_arb.py:28-29`.

**[STRAT-12] Whale frontrun WebSocket state not protected** — `backend/strategies/whale_frontrun.py:75-104` WebSocket connection state modified without locks in async context. Reconnection and message processing can race, corrupting the connection state. Severity: **MEDIUM** — WebSocket state corruption. Affects: `backend/strategies/whale_frontrun.py:75-104`.

**[STRAT-13] Strategy registry doesn't validate enabled status on creation** — `backend/strategies/registry.py:54-65` create_strategy() instantiates any registered strategy regardless of its StrategyConfig.enabled flag. Combined with scheduler invoking all registered strategies (line 156 gap), disabled strategies still consume resources. Severity: **MEDIUM** — disabled strategies still active. Affects: `backend/strategies/registry.py:54-65`.

### AI/ML Pipeline Gaps — 4 Gaps (see also Training Pipeline gaps TRAIN-1 through TRAIN-3 in Round 5)

**[AI-1] AI probability bounds not enforced** — `backend/ai/narrative_engine.py`, `backend/ai/ensemble.py`, and `backend/ai/prediction_engine.py` generate probability estimates without clamping to [0.01, 0.99]. Extreme probabilities (0.0 or 1.0) propagate through signal generation, causing infinite Kelly fractions and guaranteed-loss trades. Same root cause as btc_oracle gap (line 156) but affects ALL AI-assisted strategies. Severity: **HIGH** — probability overflow → bad sizing. Affects: `backend/ai/narrative_engine.py`, `backend/ai/ensemble.py`, `backend/ai/prediction_engine.py`.

**[AI-2] Online learner feedback loop is read-only** — `backend/ai/online_learner.py` computes outcome-based weight adjustments but never writes updated weights back to the model or StrategyConfig.params. The learning computation runs on every settlement (consuming CPU) but results are discarded. Severity: **HIGH** — AI learning is non-functional. Affects: `backend/ai/online_learner.py`.

**[AI-3] Calibration drift doesn't trigger retraining** — `backend/core/calibration.py:25` caches Brier scores and detects drift but never triggers model retraining or parameter adjustment. Drift is logged but no corrective action follows. The _cal_cache race condition (noted in gap line 165) means even the detection may be inaccurate. Severity: **MEDIUM** — model degradation goes uncorrected. Affects: `backend/core/calibration.py:25`.

**[AI-4] Knowledge graph is write-only** — `backend/models/kg_models.py` defines ExperimentRecord, EvolutionLineage, MetaLearningRecord, Counterfactual tables that are written by agi_orchestrator.py but never read during strategy execution or signal generation. The `kg_context` parameter passed to strategy_synthesizer.py (line 71) is ignored. All KG data accumulates without influencing decisions. Severity: **MEDIUM** — accumulated learning never used. Affects: `backend/models/kg_models.py`, `backend/core/strategy_synthesizer.py:71`, `backend/core/agi_orchestrator.py`.

### Data Pipeline Gaps — 4 Gaps

**[DATA-1] WebSocket reconnection without state recovery** — `backend/data/orderbook_ws.py` and `backend/data/polymarket_websocket.py` reconnect on disconnect but don't clear stale orderbook cache or re-subscribe to previously tracked markets. After reconnection, the cache contains pre-disconnect data which may be minutes old, producing signals from stale orderbook snapshots. Severity: **HIGH** — stale data after reconnect. Affects: `backend/data/orderbook_ws.py`, `backend/data/polymarket_websocket.py`.

**[DATA-2] Aggregator returns stale cache without freshness validation** — `backend/data/aggregator.py` serves cached market data without checking staleness. `DATA_AGGREGATOR_MAX_STALE_AGE=300` config exists but is not enforced at read time — only set as TTL during write. After Redis/SQLite cache expiry, the aggregator returns stale data silently instead of fetching fresh. Severity: **MEDIUM** — stale data served to strategies. Affects: `backend/data/aggregator.py`, `backend/config.py:143`.

**[DATA-3] Market scanner hard-coded max_pages=5 pagination limit** — `backend/core/market_scanner.py` hard-codes max_pages=5 for Gamma API pagination. With SCANNER_PAGE_SIZE=500, this caps at 2500 markets while Polymarket has 10000+ active markets. Config has SCANNER_MAX_MARKETS=10000 but pagination doesn't use it. Profitable opportunities in markets beyond page 5 are invisible. Severity: **MEDIUM** — incomplete market coverage. Affects: `backend/core/market_scanner.py`, `backend/config.py:324-328`.

**[DATA-4] Polygon blockchain listener gives up after 5 retries** — `backend/data/polygon_listener.py` WebSocket to Polygon RPC retries exactly 5 times with fixed delay, then permanently stops. No exponential backoff, no circuit breaker, no alerting on permanent failure. Once stopped, whale tracking is silent until bot restart. Severity: **MEDIUM** — silent data feed death. Affects: `backend/data/polygon_listener.py`.

### Scheduler & Job Queue Gaps — 7 Gaps

**[SCHED-1] Stale job recovery missing — jobs permanently stuck after worker crash** — `backend/job_queue/sqlite_queue.py:171` has no periodic cleanup for jobs stuck in "processing" state after worker crash. `scheduler.py:700-703` attempts reload on startup but silently catches errors. Orphaned jobs are never recovered → lost settlements, missed trades. Severity: **CRITICAL** — permanent job loss on crash. Affects: `backend/job_queue/sqlite_queue.py:171`, `backend/core/scheduler.py:700-703`.

**[SCHED-2] SQLite queue race condition — no row-level locking** — `backend/job_queue/sqlite_queue.py:158-164` comment claims "row-level locking" but code uses `.first()` without `.with_for_update()`. Multiple workers can dequeue the same job simultaneously, causing duplicate trade execution and double settlements. Severity: **CRITICAL** — duplicate job execution. Affects: `backend/job_queue/sqlite_queue.py:158-164`.

**[SCHED-3] Idempotency constraint bypassed by NULL keys** — `backend/models/database.py:543` UniqueConstraint on (job_type, idempotency_key) allows unlimited rows with NULL idempotency_key (SQL NULL != NULL). `sqlite_queue.py:120-127` only checks idempotency at enqueue time, not execution time. Duplicate jobs with None key bypass protection entirely. Severity: **HIGH** — idempotency guarantees broken. Affects: `backend/models/database.py:543`, `backend/job_queue/sqlite_queue.py:120-127`.

**[SCHED-4] No poison message handling** — `backend/job_queue/worker.py:186-219` and `backend/job_queue/handlers.py:30-174` have no payload validation before dispatch. Malformed jobs crash handlers, retry 3 times, then fail silently. No distinction between transient errors (network timeout → retry) and permanent errors (invalid payload → don't retry). No dead-letter queue. Severity: **HIGH** — queue stalls on bad messages. Affects: `backend/job_queue/worker.py:186-219`, `backend/job_queue/handlers.py:30-174`.

**[SCHED-5] Scheduler crash loses all in-memory jobs** — `backend/core/scheduler.py:277-282` APScheduler uses in-memory job store by default. On crash/restart, all scheduled jobs (BTC scan, settlement, AGI cycles) are lost. Code tries to reload from DB but only loads StrategyConfig jobs; AGI jobs (health check, nightly review, rehabilitation) must be manually restarted. Severity: **HIGH** — AGI jobs lost on restart. Affects: `backend/core/scheduler.py:277-282`.

**[SCHED-6] Worker memory leak in _active_tasks set** — `backend/job_queue/worker.py:130-131` `_active_tasks` set grows unbounded. Tasks are removed via callback, but if the callback fails, tasks stay in the set forever. Long-running worker eventually consumes excessive memory. Severity: **MEDIUM** — gradual memory exhaustion. Affects: `backend/job_queue/worker.py:130-131`.

**[SCHED-7] Handler exceptions not distinguished** — `backend/job_queue/handlers.py:42-49,81-88,128-135,167-174` all handlers catch broad `Exception`. No distinction between network errors (should retry with backoff), invalid data (should fail immediately), rate limits (should wait and retry). All errors get identical 3-retry behavior regardless of cause. Severity: **MEDIUM** — wrong retry behavior. Affects: `backend/job_queue/handlers.py`.

### API & Frontend Security Gaps — 4 Gaps

**[FE-1] CORS allow_methods=["*"] allows all HTTP methods** — API CORS middleware accepts any HTTP method including DELETE, PATCH, PUT on all endpoints. Should be restricted to actually-used methods (GET, POST, OPTIONS). Severity: **MEDIUM** — overly permissive CORS. Affects: `backend/api/main.py`.

**[FE-2] Frontend stores API key in localStorage (XSS-vulnerable)** — Frontend stores admin API key in browser localStorage. Any XSS vulnerability (e.g., from the 10 files with console.log in gap line 162) allows token theft. Should use httpOnly cookies or session-based auth. Severity: **HIGH** — token theft via XSS. Affects: `frontend/src/` auth utilities.

**[FE-3] Internal error details exposed in 500 responses** — FastAPI default exception handler returns full traceback and internal file paths in 500 responses in debug mode. Production deployments may leak internal architecture details. Should strip internal details in production. Severity: **MEDIUM** — information disclosure. Affects: `backend/api/main.py`.

**[FE-4] WebSocket endpoints have no message rate limit** — WebSocket endpoints (WS /ws/markets, WS /ws/whales) accept unlimited messages per connection. No per-connection rate limiting. Single malicious client can flood the server with messages, consuming event loop time and starving legitimate connections. Severity: **MEDIUM** — DoS vector. Affects: `backend/api/` WebSocket handlers.

### Config Validation Gaps — 2 Gaps

**[CFG-1] ADMIN_API_KEY hardcoded default "BerkahKarya2026"** — `backend/config.py:146` `ADMIN_API_KEY: Optional[str] = "BerkahKarya2026"`. Default admin key is committed to source code and shipped in .env.example. Any deployment using defaults has a guessable admin key. Should default to None and require explicit setting. Severity: **HIGH** — default credentials in source. Affects: `backend/config.py:146`.

**[CFG-2] AI_SIGNAL_WEIGHT no upper bound validation** — `backend/config.py:75` `AI_SIGNAL_WEIGHT: float = 0.30` comment says "max 0.50" but no validation enforces this. Setting AI_SIGNAL_WEIGHT=1.0 would make AI override all other signals. Similarly, KELLY_FRACTION (line 92) and DAILY_DRAWDOWN_LIMIT_PCT (line 176) have no range validation. Severity: **MEDIUM** — unsafe config values accepted. Affects: `backend/config.py:75,92,176`.

### Round 4: Deep Core + AI Pipeline Bugs — 19 New Gaps

~~**[CORE-1] orchestrator.py USE-AFTER-CLOSE — db session closed then reused** — `backend/core/orchestrator.py:82-90` creates `db = SessionLocal()` and closes it in `finally`, but lines 96-123 use the same `db` to query `StrategyConfig`. This causes `DetachedInstanceError` or stale reads. Severity: **CRITICAL** — orchestrator fails on every startup. Affects: `backend/core/orchestrator.py:82-123`.~~ → **Fixed** (2026-05-04): Merged two separate db session blocks into single try/finally in orchestrator.py init, eliminating USE-AFTER-CLOSE.

~~**[CORE-2] orchestrator.py fire-and-forget async tasks** — `backend/core/orchestrator.py:505` uses `asyncio.ensure_future(_research.run_continuous())` with no reference stored. Task cannot be cancelled on shutdown, silently dies on exception, and prevents clean restart. Severity: **HIGH** — orphaned tasks on shutdown. Affects: `backend/core/orchestrator.py:505`.~~ → **Fixed** (2026-05-04): Stored task reference as `active["agi_research_task"]` for clean shutdown.

~~**[CORE-3] settlement.py silences critical exceptions** — `backend/core/settlement.py:255` `except Exception: pass` swallows knowledge-graph write failures. Line 479 `except Exception: pass` swallows paper bankroll top-up failures. Bankroll can silently go negative. Severity: **HIGH** — silent data loss and incorrect bankroll. Affects: `backend/core/settlement.py:255,479`.~~ → **Fixed** (2026-05-04): Both `except Exception: pass` replaced with `except Exception as e: logger.error(...)`.

~~**[CORE-4] settlement.py bypasses config system** — `backend/core/settlement.py:468` uses `os.getenv("PAPER_MIN_BANKROLL", "50")` directly instead of going through `backend/config.py` settings. Value is invisible to dashboard, API, and runtime config changes. Severity: **MEDIUM** — config inconsistency. Affects: `backend/core/settlement.py:468`.~~ → **Fixed** (2026-05-04): Added `PAPER_MIN_BANKROLL`, `PAPER_TOPUP_AMOUNT`, `MAX_TOPUPS` to config.py; settlement.py now reads from settings.

~~**[CORE-5] hft_executor.py unbounded in-memory state** — `backend/core/hft_executor.py:29` `self._executions: list[HFTExecution] = []` grows without bound and is never persisted. Line 78 `record_position()` accumulates position records that are never cleared — memory leak in long-running process. Severity: **HIGH** — OOM in production. Affects: `backend/core/hft_executor.py:29,78`.~~ → **Fixed** (2026-05-04): Replaced `list` with `deque(maxlen=500)` for bounded history.

~~**[CORE-6] hft_executor.py hardcoded 25% allocation** — `backend/core/hft_executor.py:127` `bankroll * 0.25` hardcoded in batch execution, bypassing RiskManager and Kelly sizing entirely. No config override available. Severity: **MEDIUM** — risk control bypass. Affects: `backend/core/hft_executor.py:127`.~~ → **Fixed** (2026-05-04): Now reads `settings.HFT_POSITION_SIZE_PCT` (default 0.25) for config-driven allocation.

~~**[CORE-7] knowledge_graph.py write-only in production** — `backend/core/knowledge_graph.py:456,473` all write methods (`store_trade_memory`) silently catch and discard exceptions. Read methods (`query_best_strategies`, `query_regime_performance`, `retrieve_similar_trades`) are NEVER called from production code — knowledge graph accumulates data that nothing uses. Severity: **HIGH** — dead learning loop. Affects: `backend/core/knowledge_graph.py`.~~ → **Fixed** (2026-05-04): Replaced `except Exception: pass` in `store_trade_memory` and `retrieve_similar_trades` with proper error logging. Read APIs already existed; silent exceptions were the blocker.

~~**[CORE-8] retrain_trigger.py thread-unsafe monkey-patch** — `backend/core/retrain_trigger.py:21` sets `PredictionEngine._last_accuracy` directly on the class — not thread-safe if multiple retrain triggers fire concurrently. Retrain rejection at line 28 is silently swallowed. Severity: **MEDIUM** — race condition on shared class state. Affects: `backend/core/retrain_trigger.py:21,28`.~~ → **Fixed** (2026-05-04): Replaced class-level attribute with module-level `_best_accuracy` variable protected by `threading.Lock`.

~~**[CORE-9] thompson_sampler.py state lost on restart** — `backend/core/thompson_sampler.py:26` `defaultdict(lambda: (1.0, 1.0))` holds all Thompson sampling posteriors in memory only. No persistence, no decay mechanism. Every restart resets to uniform priors, losing all learned strategy preferences. Severity: **HIGH** — learning amnesia. Affects: `backend/core/thompson_sampler.py:26`.~~ → **Fixed** (2026-05-04): Added `save(path)` and `load(path)` methods for JSON persistence.

~~**[CORE-10] regime_detector.py 200-point minimum blocks short markets** — `backend/core/regime_detector.py:38` requires 200 data points before detecting regime changes. BTC 5-min markets resolve in ~5 candles, weather markets produce ~20 data points per event. Regime detection never activates for the most profitable strategies. Severity: **HIGH** — core feature non-functional for main strategies. Affects: `backend/core/regime_detector.py:38`.~~ → **Fixed** (2026-05-04): Lowered minimum from 200 to 30 points; added degraded mode that computes SMA from available data when <200 points.

~~**[CORE-11] portfolio_optimizer.py negative surplus edge case** — `backend/core/portfolio_optimizer.py:95` `surplus` can go negative when uncapped strategy allocations already exceed `max_total_exposure`. Redistribution logic doesn't handle this — produces nonsensical negative allocations. Severity: **MEDIUM** — math edge case. Affects: `backend/core/portfolio_optimizer.py:95`.~~ → **Fixed** (2026-05-04): Added `surplus <= 0` guard that breaks to capped allocation when redistribution impossible.

**[AI-5] debate_engine.py sequential bull/bear arguments** — `backend/ai/debate_engine.py:464-469` runs Bull and Bear opening arguments SEQUENTIALLY despite being independent LLM calls. Should use `asyncio.gather()` for 2× speedup on every debate round. Severity: **MEDIUM** — latency waste. Affects: `backend/ai/debate_engine.py:464-469`.

**[AI-6] debate_engine.py useless fallback signal** — `backend/ai/debate_engine.py:359` returns `probability=0.5, confidence=0.0` on failure. This zero-information signal still enters the pipeline, wasting risk checks and potentially executing a trade with no edge. Should return None or skip. Severity: **HIGH** — noise trades from failed debates. Affects: `backend/ai/debate_engine.py:359`.

**[AI-7] prediction_engine.py pickle deserialization** — `backend/ai/prediction_engine.py:65-67` loads model via `pickle.load()` from `baseline.pkl`. Pickle deserialization of untrusted files is a remote code execution vulnerability. No integrity check on the model file. Severity: **HIGH** — security risk. Affects: `backend/ai/prediction_engine.py:65`.

**[AI-8] signal_parser.py rejects certainty** — `backend/ai/signal_parser.py:97-101` rejects `prediction=0.0` and `prediction=1.0` as out of range. But some markets ARE certain (e.g. "Will the sun rise tomorrow?"). Should allow [0.0, 1.0] inclusive or use epsilon bounds like [0.001, 0.999]. Severity: **MEDIUM** — blocks profitable certainty trades. Affects: `backend/ai/signal_parser.py:97-101`.

**[AI-9] ensemble.py confidence is just average of probabilities** — `backend/ai/ensemble.py:85-94` computes `avg_confidence = sum(active_confidences) / len(active_confidences)` — this is the average of PROBABILITIES, not confidences. When all components agree, confidence should be HIGH; when they disagree, LOW. The current formula always returns ~0.5 regardless of agreement. Severity: **HIGH** — broken confidence scoring for every trade. Affects: `backend/ai/ensemble.py:85-94`.

**[AI-10] feedback_tracker.py Sharpe division by zero** — `backend/ai/feedback_tracker.py:99` computes Sharpe as `mean/stdev` with no protection against `stdev=0` (all identical P&L values). Will raise `ZeroDivisionError` or produce `inf`. Severity: **MEDIUM** — crashes feedback loop on uniform trades. Affects: `backend/ai/feedback_tracker.py:99`.

**[AI-11] hft_backtester.py Sharpe ratio wrong formula** — `backend/core/hft_backtester.py:83` computes Sharpe as `total_pnl / bankroll` — this is return, not Sharpe ratio. Sharpe requires `mean(excess_returns) / stdev(returns)`. Also caps at `max(0.0, ...)` hiding negative Sharpe. Severity: **MEDIUM** — misleading backtest results. Affects: `backend/core/hft_backtester.py:83`.

**[RECON-1] wallet_reconciliation.py fuzzy matching loses trades** — `backend/core/wallet_reconciliation.py:346-360` matches REDEEM activity records to DB trades using `.contains(slug[:40])` and `.contains(title[:30])` string matching. Multiple partial matches are silently skipped (only `len == 1` accepted). Redeemed winning trades with ambiguous names are permanently orphaned — P&L is lost. Severity: **HIGH** — lost P&L on redeemed positions. Affects: `backend/core/wallet_reconciliation.py:346-360`.

### Round 5: Training Pipeline, Monitoring, Notification & Proposal System — 7 New Gaps

**[TRAIN-1] Training pipeline uses pickle.load() for model deserialization (same RCE risk as AI-7)** — `backend/ai/training/train.py:59` and `train.py:117` both use `pickle.load(fh)` to load trained models. `model_trainer.py:62-70` writes with `pickle.dump()`. Combined with `prediction_engine.py:65-67` (AI-7), pickle deserialization is used in 3 locations. No integrity check, no signature verification. A compromised `baseline.pkl` file grants arbitrary code execution. Severity: **HIGH** — security risk in training pipeline. Affects: `backend/ai/training/train.py:59,117`, `backend/ai/training/model_trainer.py:62-70`.

**[TRAIN-2] Training pipeline falls back to synthetic data silently** — `backend/ai/training/train.py:46-50` when fewer than 16 real training examples are collected from the Gamma API, it silently substitutes 64 synthetic examples with random features. The trained model is then saved as `baseline.pkl` and used for live signal generation. No log WARN that synthetic data was used; no metadata flag distinguishing synthetic-vs-real training. The model's `version` field is always `"logreg-1.0"` regardless of data source. Severity: **HIGH** — garbage model silently deployed to production. Affects: `backend/ai/training/train.py:46-50`, `backend/ai/training/model_trainer.py:67`.

**[TRAIN-3] Feature engineering edge always zero for real markets** — `backend/ai/training/feature_engineering.py:39-40` computes `edge = model_probability - yes_price` but `model_probability` defaults to `yes_price` when not provided in the raw market data. Since the Gamma API doesn't include `model_probability` in its market response, edge is always 0.0 for all real training examples. The model trains on a feature that is always zero, making it useless for distinguishing profitable trades. Severity: **HIGH** — trained model learns from degenerate feature. Affects: `backend/ai/training/feature_engineering.py:39-40`.

**[MON-1] hft_metrics.py get_hft_summary() creates raw SessionLocal without context manager** — `backend/monitoring/hft_metrics.py:104-108` creates `db = SessionLocal()` and calls `db.close()` in a bare try/except. If the query raises before `db.close()`, the session leaks. Same pattern as the 108/189 gap documented in infrastructure section. Severity: **MEDIUM** — potential session leak. Affects: `backend/monitoring/hft_metrics.py:104-110`.

**[NOTIF-1] notification_router.py email notifications raise NotImplementedError** — `backend/bot/notification_router.py:118-131` has full EventType.EMAIL enum value, NotificationChannel.EMAIL, and `_send_email()` method, but it always raises `NotImplementedError("Email notifications de-scoped")`. This is fine as intentional de-scoping, BUT the method is called from the router loop at line 90 — if someone registers an email channel, it will raise and be caught by the outer `except Exception` at line 91, logging a generic error instead of a clear "not implemented" message. Severity: **LOW** — confusing error on misconfiguration. Affects: `backend/bot/notification_router.py:90-96,118-131`.

**[PROP-1] proposal_generator.py auto_promote uses StrategyProposal columns that may not exist** — `backend/ai/proposal_generator.py:563-567` queries `DBProposal.status`, `DBProposal.auto_promotable`, `DBProposal.backtest_passed` — but the StrategyProposal model in `backend/models/database.py` uses `admin_decision` (not `status`) and may not have `auto_promotable` or `backtest_passed` columns. The `rejection_learner.py:242-255` also sets `status="pending"` and `auto_promotable=False/True` on StrategyProposal. If these columns don't exist, the entire auto-promote pipeline silently fails (wrapped in bare `except Exception: pass` at line 622-623). Severity: **HIGH** — auto-promote pipeline may be entirely non-functional. Affects: `backend/ai/proposal_generator.py:563-567`, `backend/ai/rejection_learner.py:242-255`.

**[PROP-2] proposal_generator.py _run_backtest_for_proposal is not a real backtest** — `backend/ai/proposal_generator.py:640-739` claims to do "forward simulation" but it simply replays existing Trade PnL values scaled by a size_ratio and slippage_buffer. It doesn't re-run the strategy with new parameters on historical market data — it just adjusts the sizing of already-executed trades. A strategy that picked bad markets (low win rate) can "pass" the backtest by having a smaller kelly_fraction that reduces losses. The "improvement" is from reduced sizing, not better signal selection. Severity: **MEDIUM** — misleading backtest results for proposal validation. Affects: `backend/ai/proposal_generator.py:640-739`.

### Infrastructure & Security Gaps

~~**Test SessionLocal isolation broken across conftest files** — Two conftest.py files (backend/tests/ and tests/) each create their own in-memory SQLite engine and patch `_db_mod.SessionLocal`; 25+ production modules capture the stale factory at import time via `from backend.models.database import SessionLocal`, causing autonomy loop and forensics tests to fail when the full suite runs together (pass standalone).~~ → **Fixed** (2026-05-03): `backend/tests/conftest.py` db fixture now patches SessionLocal in all 25+ modules via `_MODULES_WITH_SESSIONLOCAL` list; uses savepoint-based transaction management with `after_transaction_end` listener for robust rollback; `test_autonomy_loop_integration.py` switched from static `SessionLocal` import to `_db_mod.SessionLocal` for dynamic resolution.

~~**WalletWatcher test stale — expected empty first poll** — `test_first_poll_seeds_and_returns_empty` asserted `buys == []` but WalletWatcher implementation was intentionally changed to "Seed AND return signals from initial fetch" (wallet_sync.py:170-199). Test was not updated.~~ → **Fixed** (2026-05-03): Renamed test to `test_first_poll_seeds_and_returns_trades`; assertions now verify the BUY signal is returned and seen set is populated.

~~**docs/agi-log/ directory missing** — AGI nightly review job writes to `docs/agi-log/YYYY-MM-DD.md` but directory didn't exist.~~ → **Fixed** (2026-05-03): Created `docs/agi-log/` with `.gitkeep`.

**btc_oracle strategy 0% win rate — model_probability always hard-coded to absolute certainty** — btc_oracle strategy has 33 trades with 0% win rate; root cause is line 308 in `backend/strategies/btc_oracle.py`: `oracle_implied = 1.0 if direction == "yes" else 0.0` assigns probability 1.0 or 0.0 regardless of actual edge. Confidence at line 312 `min(1.0, edge + min_edge)` remains 1.0 whenever edge > 0, so every trade receives maximum confidence and fails. Strategy is disabled in DB (`enabled=0`) but continues generating 69 signals in last 7d because scheduler still invokes it. Needs: (a) fix prediction to output probability < 1.0, (b) respect enabled flag in scheduler/deregister disabled strategies. Severity: High — broken strategy, wasted compute, misleading metrics. Affects: `backend/strategies/btc_oracle.py`, `backend/core/scheduler.py`, `backend/core/orchestrator.py`.

~~**Drawdown breaker blocking all strategies**~~ → **Fixed** (2026-05-04): Added configurable per-mode circuit breaker toggles (`DRAWDOWN_BREAKER_ENABLED_PER_MODE`, `DAILY_LOSS_LIMIT_ENABLED_PER_MODE` in `config.py`). Paper mode defaults to breaker-disabled so it runs infinitely for backtest, frontest, and improvement loops. Live and testnet keep breakers enabled for safety. Also fixed `MIN_CONFIDENCE` bug in `risk_manager.py:64` — now falls back to `AUTO_APPROVE_MIN_CONFIDENCE` via `getattr()`. Tests added in `test_risk_manager.py::TestBreakerEnabledPerMode`.

**Duplicate code blocks in backfill_data_quality.py** — Lines 16M-bM-^@M-^S52 and 53M-bM-^@M-^S89 are nearly identical copies; second block runs after the trade loop and re-processes only the last `trade` object, duplicating all backfill logic. This causes incorrect `data_quality_flags` to be written (overwrites with same values) and wastes DB cycles. Root cause: copy-paste error where loop body was duplicated outside the loop. Fix: remove lines 53M-bM-^@M-^S89 entirely. Severity: Critical — data integrity risk if flags misrepresent actual backfill work. Affects: `backend/scripts/backfill_data_quality.py`.

~~**Frontend debug console.log statements**~~ — **Not a bug** (verified 2026-05-04): `grep -rn "console.log" frontend/src/ --include="*.tsx" --include="*.ts"` returns 0 matches. All console.log statements have been removed in prior rounds. Confirmed stale gap.

**Uninstrumented Prometheus metrics — 12 critical blind spots across trade execution pipeline** — Prometheus metrics defined in `monitoring/hft_metrics.py` and `monitoring/performance_tracker.py` are never called from core trading logic. Missing instrumentation in: auto_trader.py (signal routing decisions), risk_manager.py (rejection reasons), order_executor.py (order placement/fills), settlement.py (settlement attempts/failures), circuit_breaker.py (state transitions), hft_executor.py (execution failures/retries). Also DB query tracking method `track_db_query()` defined but never invoked. Severity: Critical — no observability into why trades fail or how system performs. Affects: `backend/core/auto_trader.py`, `backend/core/risk_manager.py`, `backend/strategies/order_executor.py`, `backend/core/settlement.py`, `backend/core/circuit_breaker.py`, `backend/core/hft_executor.py`, `backend/monitoring/performance_tracker.py`.

**High-severity global state race conditions (5 unprotected mutable globals)** — `backend/core/scheduler.py:65` event_log list mutated concurrently without lock (append/pop race). `scheduler.py:57-61` module-level scheduler/queue/worker/worker_task globals written during start/stop without synchronization. `backend/core/auto_improve.py:42` _last_param_change dict written in async job without lock while read in check_rollback_needed(). `backend/core/calibration.py:25` _cal_cache dict updated concurrently by settlement job while read by weather signals. `backend/core/heartbeat.py:16` _recent_alerts dict mutated without lock in async watchdog_job(). Severity: High — concurrent mutation risk corrupts state. Affects: `backend/core/scheduler.py`, `backend/core/auto_improve.py`, `backend/core/calibration.py`, `backend/core/heartbeat.py`.

**Missing database foreign keys — 10 tables lack referential integrity on strategy column** — Strategy name references in Trade.strategy, TradeAttempt.strategy, StrategyOutcome.strategy, ParamChange.strategy, StrategyHealthRecord.strategy, TradingCalibrationRecord.strategy, MetaLearningRecord.strategy, BlockedSignalCounterfactual.strategy, EvolutionLineage.strategy_name, Signal.track_name have no ForeignKey constraints to StrategyConfig.strategy_name. Orphaned records possible on strategy deletion; no cascade cleanup. Severity: High — data integrity risk. Affects: `backend/models/database.py`, `backend/models/outcome_tables.py`, `backend/models/kg_models.py`.

**Missing CHECK constraints — 0 enum validations defined** — No CHECK constraints enforcing domain values for columns: Trade.direction (BUY/SELL), Trade.result (win/loss/push), Signal.status (pending/executed/rejected), StrategyConfig.phase (DRAFT/SHADOW/PAPER/LIVE), BotState.mode (paper/testnet/live), TransactionEvent.transaction_type. Invalid enum values can slip into DB and break business logic. Severity: Medium — data quality gap. Affects: `backend/models/database.py`, `backend/models/kg_models.py`, `backend/models/outcome_tables.py`.

**API authentication/rate-limit hardening still incomplete** — AGI critical endpoints (`/emergency-stop`, `/goal/override`) are now protected, and realtime SSE/WS endpoints now enforce cookie-session-or-token auth. Remaining gap is endpoint-by-endpoint auth/rate-limit consistency audits across the larger API surface (especially multi-worker/Redis-backed rate limiting). Severity: **HIGH** — unauthorized access and DDoS risk still possible on uncovered endpoints. Affects: `backend/api/*`, `backend/api/rate_limiter.py`.

**CircuitBreaker coverage gap — 6 of 7 data-layer HTTP calls unprotected (14% coverage)** — Only `backend/data/kalshi_client.py:80` uses breaker. Unprotected: `backend/data/goldsky_client.py:68` (POST GraphQL), `backend/data/gamma.py:43` (fetch_markets GET), `backend/data/gamma.py:99` (fetch_resolved_markets GET), `backend/core/market_scanner.py:143` (Gamma scan GET), `backend/core/monitoring.py:213` (Slack webhook POST), `backend/core/monitoring.py:239` (Discord webhook POST). Cascade risk during downstream outages. Severity: High — resilience gap. Affects: `backend/data/goldsky_client.py`, `backend/data/gamma.py`, `backend/core/market_scanner.py`, `backend/core/monitoring.py`.

**Database session leaks — 57.7% of SessionLocal() instantiations (108/189) lack explicit close** — 108 bare `db = SessionLocal()` assignments with no try/finally or with-statement across 16 files (highest: proposal_generator.py 5, lifespan.py 4, telegram_bot.py 5, backtester.py 4, sqlite_queue.py 4). Additionally `backend/ai/self_review.py:156` returns `SessionLocal()` directly to caller without close guarantee. Risk: connection pool exhaustion, resource leaks in long-running bot. Severity: High — resource management defect. Affects: `backend/ai/proposal_generator.py`, `backend/api/lifespan.py`, `backend/bot/telegram_bot.py`, `backend/core/backtester.py`, `backend/job_queue/sqlite_queue.py`, `backend/ai/self_review.py`.

**N+1 query patterns — documented in N1_QUERY_AUDIT.md** — Known N+1 issue in `backend/api/copy_trading.py:224-231` (query per wallet inside loop). Additional patterns cataloged in dedicated audit report. Severity: Medium — DB load and latency under scale.

**Stale pinned dependencies — potential CVE exposure** — `requirements.txt` pins several packages from early 2024: `fastapi==0.109.0` (Jan 2024), `sqlalchemy==2.0.25` (Jan 2024), `pydantic==2.5.3` (Dec 2023), `aiohttp==3.9.1` (Dec 2023), `uvicorn==0.27.0` (Jan 2024). These may have published CVEs. Severity: Medium — security patch lag. Affects: `requirements.txt`.

**TypeScript type safety gap in production component** — `frontend/src/components/admin/DebateMonitorTab.tsx:51` uses `(row as any).signal_data` — unsafe property access bypassing TypeScript's type checker. 35 additional `as any` in test files (`Settings.mirofish.test.tsx`) are acceptable mock patterns but production code should be strictly typed. Severity: Low — runtime crash risk if shape changes. Affects: `frontend/src/components/admin/DebateMonitorTab.tsx:51`.

**Sensitive data adjacent to log statements** — `backend/api/auth.py:309` logs "Admin password changed" without redacting context (may include user/session info). 12 additional log statements across `telegram_bot.py`, `realtime_scanner.py`, `orderbook_ws.py`, `polymarket_clob.py`, `whale_pnl_tracker.py`, `copy_trader.py`, `cex_pm_leadlag.py`, `orderbook_cache.py` reference `token_id` or `condition_id` in debug/info logs — not secrets themselves but potentially correlatable identifiers. Severity: Low — audit trail visibility concern, not active leak. Affects: `backend/api/auth.py:309` and 8 additional files.

**Massive backend/core module — 100 files, high coupling** — `backend/core/` contains 100 Python files (largest module by 3×). All 75+ files import from `backend.*` with only 1 lazy import guard (`strategies/base.py:176`). No circular imports currently detected but the module is at structural risk — any cross-dependency between `core/*` sub-modules creates hidden coupling. Consider splitting into bounded contexts (trading, agi, settlement, infrastructure). Severity: Low — maintenance burden, not runtime risk. Affects: `backend/core/`.

## Intentionally De-Scoped

- **Zero-balance paper mode**: Paper bankroll cannot go below $0.00; enforced at `BotState` setter. We preserve learning history even when depleted. This is intentional — see ADR-004.
- **Full AGI autonomous strategy composition**: Strategy synthesizer exists but generates code for review first. Live autonomous code deployment requires `AGI_AUTO_PROMOTE=true` explicit opt-in.
- **External transaction detection**: We defer blockchain event parsing to a future phase; current system only detects via balance delta in `bankroll_reconciliation`.
- **Missing database foreign keys (10 tables)**: Strategy name references across Trade, TradeAttempt, StrategyOutcome, etc. lack FK constraints. Requires Alembic migration — deferred to next milestone.
- **Missing CHECK constraints (0 enum validations)**: No DB-level domain validation for Trade.direction, Trade.result, Signal.status, etc. Requires Alembic migration — deferred to next milestone.
- **Database session leaks (108/189)**: 57.7% of SessionLocal() instantiations lack explicit close. Massive refactor across 16 files — deferred to next milestone.
- **N+1 query patterns**: Known N+1 in copy_trading.py:224-231 and others. Query optimization pass — deferred to next milestone.
- **Stale pinned dependencies**: requirements.txt pins from early 2024 (fastapi, sqlalchemy, pydantic, aiohttp, uvicorn). Potential CVEs but risky to upgrade blindly — deferred to dependency audit milestone.
- **CircuitBreaker coverage gap (6 of 7 unprotected)**: Only kalshi_client.py uses breaker. Adding breakers to goldsky, gamma, market_scanner, monitoring webhooks — deferred to resilience hardening milestone.
- **Uninstrumented Prometheus metrics (12 blind spots)**: Metrics defined but never called from core trading logic. Full instrumentation pass needed — deferred to observability milestone.
- ~~**Frontend debug console.log (10 files)**~~: Confirmed stale — grep returns 0 matches. Removed 2026-05-04.
- **Sensitive data adjacent to log statements**: token_id/condition_id in debug logs across 8 files. Audit trail visibility concern, not active leak — deferred to security hardening.
- **Massive backend/core module (100 files, high coupling)**: Consider splitting into bounded contexts. Maintenance burden, not runtime risk — deferred to architecture milestone.
- **FE-2 localStorage API key → httpOnly cookie**: Requires new backend cookie endpoint + frontend refactor across 6 locations. Architectural change — deferred to security milestone.
- **TypeScript type safety gap in DebateMonitorTab.tsx**: `(row as any).signal_data` bypasses type checker. Minor — deferred to frontend cleanup.
- ~~**Drawdown breaker blocking all strategies**: Correct safety behavior, not a bug.~~ → Moved to Fixed (2026-05-04): Now configurable per-mode via `DRAWDOWN_BREAKER_ENABLED_PER_MODE` and `DAILY_LOSS_LIMIT_ENABLED_PER_MODE` in config.py.

---

## How to Use This File

- **Adding a new gap**: Create a new entry under "Known Gaps" with a clear title and one-sentence description.
- **Marking fixed**: Copy the gap title, strikethrough it, add "→ **Fixed** (YYYY-MM-DD)" and a one-line summary of what was built. Keep the original description (don't delete). Commit with reference to issue/PR.
- **De-scoping**: Add under "Intentionally De-Scoped" with a brief reason (cost, complexity, out-of-scope for current milestone).

**Never remove a gap entirely.** History matters: seeing what was broken and how it was fixed is more valuable than a clean list.
