# Implementation Gaps — PolyEdge Trading Bot

**Last Updated:** 2026-05-15 (All 85+ catalogued gaps fixed or intentionally de-scoped; zero remaining open items in IMPLEMENTATION_GAPS.md.)

This file is the single source of truth for what's built vs planned. Every future agent must
read this before proposing work — avoid re-litigating already-completed items.

Format: 
- **Fixed** (YYYY-MM-DD): one-line of what was built and which files changed.
- **Known Gaps**: items not yet implemented.
- **Intentionally De-Scoped**: items we consciously chose not to do (with reason).

---

## Fixed

**Security anomaly fixes [CRIT-001..LOW-002]** → **Fixed** (2026-05-15): Addressed all findings from `docs/ANOMALY_REPORT.md`. (1) CRIT-001: replaced `eval(env_val)` with `ast.literal_eval(env_val)` in `backend/config.py:79`. (2) CRIT-002: restricted `exec()` builtins dict in `backend/core/strategy_synthesizer.py:279` — only allows safe builtins (`len`, `range`, `float`, etc.), uses `safe_namespace` instead of `module.__dict__`, removed unused `types` import. (3) HIGH-001: added `_safe_ddl_identifier()` and `_safe_ddl_type()` regex validators in `backend/models/database.py` to prevent SQL injection in ALTER TABLE migrations. (4) MED-004: added `_scheduler_state_lock` (`threading.Lock`) and wrapped `sched.add_job()` in `backend/core/scheduler.py:279`. (5) MED-002: narrowed backtest gate `except Exception` to `(ValueError, KeyError, IndexError, FileNotFoundError)` in `backend/core/strategy_synthesizer.py:266`. (6) LOW-002: added `WALLET_FERNET_KEY` empty check in `backend/config.py:validate()` with explicit plaintext warning. Verified: `lsp_diagnostics` clean on all touched files.

**Position consolidation [EXEC-1]** → **Fixed** (2026-05-15): Discovered and fixed critical bug where HFT executor and auto_trader had NO duplicate position checks, allowing 15+ duplicate trades on same market (burning $450+ on Gemini 3.5 case). Root cause: HFT executor's `execute()` method and auto_trader's `execute_signal()` method both executed new trades without checking for existing open positions. Implemented duplicate position validation: (1) Query for existing unsettled Trade on (market_id, event_slug, mode), (2) Return rejected ExecutionResult if duplicate found, (3) Log blocked duplicates. Removed undefined `_persist_to_db()` calls in HFT executor. Files: `backend/core/hft_executor.py` (37 lines added, 2 removed), `backend/core/auto_trader.py` (30 lines added). Tests: All existing tests pass.

**MiroFish service fully operational** → **Fixed** (2026-05-15): Enabled MiroFish debate engine for production use. Seeded `mirofish_enabled=true` in `system_settings` table, verified service state machine (RUNNING), tested debate engine end-to-end with dual Bull/Bear/Judge consensus, confirmed graceful fallback to local debate engine on MiroFish unavailability, validated health endpoint at `/api/v1/health/mirofish` returns circuit breaker metrics and latency, and verified all 41 unit tests pass (3 mirofish_service, 25 debate_engine, 13 integration). Updated AGENTS.md with MiroFish status section. Files: `backend/services/mirofish_service.py`, `backend/ai/debate_router.py`, `backend/ai/debate_engine.py`, `AGENTS.md`.

**Bot runtime hardening** → **Fixed** (2026-05-14): Closed the remaining freeze-prone runtime gaps in `backend/core/auto_trader.py`, `backend/core/strategy_executor.py`, `backend/core/heartbeat.py`, and `backend/core/event_bus.py`. Added the missing `asyncio` import for live auto-trader timeouts, corrected the live CLOB execution indentation/syntax path, bounded wallet-sync/CLOB waits with `asyncio.wait_for(...)`, ensured heartbeat-file directories are created before touching the liveness file, and replaced raw fire-and-forget event-bus scheduling with tracked background tasks that retain strong references and log exceptions/cancellations explicitly. Verified with `ruff check` on all modified backend files and targeted pytest (`32 passed`).

**Settlement scheduling in queue-worker mode** → **Fixed** (2026-05-14): Kept `settlement_check` registered directly in `backend/core/scheduler.py` even when queue-worker mode is enabled, because no periodic queue producer exists yet for settlement jobs. This preserves live exposure release and stale-position cleanup across PM2 restarts. PR #113 merged with CI passing.

**Bounded `bot_state` row-lock waits** → **Fixed** (2026-05-14): Added PostgreSQL transaction-local `lock_timeout=5s` and `statement_timeout=30s` inside `backend/models/database.py:for_update()` so API/scheduler/trading paths fail fast instead of hanging indefinitely behind a contended `bot_state` row. Added `settlement_check` `misfire_grace_time=60` in `backend/core/scheduler.py` and regression coverage in `backend/tests/test_scheduler_queue_mode.py`. PR #114 merged; verified with focused pytest and Oracle review.

**Trade persistence vs `bot_state` contention hardening** → **Fixed** (2026-05-14): Updated `backend/core/strategy_executor.py` so trade/audit/attempt persistence commits before best-effort `BotState` counter sync, preventing `psycopg2.errors.LockNotAvailable` on `bot_state` from rolling back durable trade records after `RISK_APPROVED`. Updated `backend/core/heartbeat.py` so `_pending_heartbeats` are only removed after a successful DB flush, preserving watchdog state through lock-timeout failures. Added regressions in `backend/tests/test_strategy_executor.py` covering post-trade `BotState` sync failure and failed heartbeat flush retention. Verified with targeted pytest (`35 passed`).

~~**[AGI-1] No strategy time_horizon or risk_tier classification**~~ → **Fixed** (2026-05-09): Added `time_horizon` and `risk_tier` columns to `StrategyConfig` via Alembic migration `a9f3c1e2b4d5`. Added `conservative` and `crazy` presets to `backend/core/risk_profiles.py`. Added `RISK_TIER_MAX_ALLOCATION` dict. `StrategyRanker.auto_allocate()` already reads `risk_tier` — added `trading_mode` param to fix signature mismatch. `FronttestValidator.can_go_live()` now skips 14-day gate for `crazy`-tier strategies via `_get_strategy_risk_tier()` helper.

~~**[AGI-2] No LIVE_TRIAL phase — promoter jumps PAPER→LIVE_PROMOTED directly**~~ → **Fixed** (2026-05-09): `LIVE_TRIAL` status was already in `ExperimentStatus` enum and `AutonomousPromoter` — verified wired. Added `LIVE_TRIAL_ENABLED`, `LIVE_TRIAL_BANKROLL_PCT`, `LIVE_TRIAL_DURATION_DAYS`, `LIVE_TRIAL_DEGRADATION_THRESHOLD` to `backend/config.py` and `.env.example`.

~~**[AGI-3] No demotion→improvement loop — killed strategies go to RETIRED**~~ → **Fixed** (2026-05-09): `AutonomousPromoter` now calls `_trigger_improvement_loop()` on LIVE_TRIAL kill, LIVE_TRIAL degradation, and LIVE_PROMOTED kill. Loop triggers forensics proposals + creates new DRAFT experiment. Respects `AGI_MAX_IMPROVEMENT_ATTEMPTS` before RETIRED. Affects: `backend/core/autonomous_promoter.py`.

~~**[AGI-4] StrategySynthesizer stub code**~~ → **Fixed** (2026-05-09): `StrategySynthesizer.generate_strategy()` now calls `StrategyComposer.compose_new_strategy()` (Claude/Groq LLM) with KG context. Added 4-gate validation pipeline: syntax → lint → 30-day backtest → sandbox import. Only strategies passing all gates enter SHADOW. Daily budget enforced via `AGI_SYNTHESIS_DAILY_BUDGET`. Affects: `backend/core/strategy_synthesizer.py`.

~~**[AGI-5] ExperimentRunner faked shadow results**~~ → **Verified Fixed** (2026-05-09): `DBSessionShadowRunner` is the canonical shadow runner; `shadow_validation_job` updates `GenomeRegistry.fitness_json` from real shadow trades. No stub data found in current code.

~~**[AGI-6] AGI improvement cycle swallows all errors silently**~~ → **Fixed** (2026-05-09): All 7 stages now record per-stage result in `stats["stage_results"]`. PERMANENT failures call `_alert_permanent_failure()` → `ProductionMonitor.send_alert()`. BENIGN failures log a warning before continuing. Affects: `backend/core/agi_orchestrator.py`.

~~**[AGI-7] Forensics dead-end for fundamentally broken strategies**~~ → **Fixed** (2026-05-09): Removed permanent exclusion of `fundamentally_broken` strategies. Added parameter overhaul path (randomise all tunable params). `_has_active_experiment()` now excludes RETIRED experiments. Added `strategy_filter` param for targeted calls. Added `AGI_BROKEN_STRATEGY_OVERHAUL_ENABLED` flag. Affects: `backend/core/forensics_integration.py`.

~~**[AGI-8] Auto-improve rollback only tracks one parameter change globally**~~ → **Fixed** (2026-05-09): `_last_param_change` changed from `Optional[dict]` to `dict[str, dict]` keyed by strategy name. `check_rollback_needed()` accepts `strategy` param. Apply section uses `"__global__"` key for legacy callers. Affects: `backend/core/auto_improve.py`.

~~**[AI-1] Probability bounds unenforced at AI output**~~ → **Verified Fixed** (2026-05-09): `narrative_engine.py`, `ensemble.py`, and `prediction_engine.py` all call `clamp_probability()` from `probability_utils.py`. Already fixed in a prior round.

~~**[AI-2] Online learner feedback loop read-only**~~ → **Verified Fixed** (2026-05-09): `_persist_weights()` is called in `on_trade_settled()` in `backend/core/online_learner.py`. Already fixed in a prior round.

~~**[AI-3] Calibration drift detected but never triggers retraining**~~ → **Fixed** (2026-05-09): Added `model_calibration_check_job()` to `backend/core/agi_jobs.py`. Runs every `AGI_CALIBRATION_CHECK_INTERVAL_HOURS` (default 6h). Computes Brier score from recent settled trades; calls `check_and_trigger_retraining()` when score exceeds `AGI_BRIER_DRIFT_THRESHOLD`. Registered in `backend/core/scheduler.py`.

~~**[AI-4] Knowledge graph write-only — never read during decisions**~~ → **Fixed** (2026-05-09): Added `query_by_type()` and `query_relations()` helpers to `KnowledgeGraph`. `AGIOrchestrator.run_cycle()` now reads regime history and strategy performance from KG before composing strategies. KG context passed to `StrategyComposer.compose()` via `kg_context` param. `ComposedStrategy` stores `kg_context` for downstream use. Affects: `backend/core/knowledge_graph.py`, `backend/core/agi_orchestrator.py`, `backend/core/strategy_composer.py`.

~~**[STRAT-3,5,12] Race conditions in copy_trader, realtime_scanner, whale_frontrun**~~ → **Verified Fixed** (2026-05-09): All three already have `asyncio.Lock` protection in current code.

~~**[STRAT-6,8,10] Weather calibration unpersisted, market maker no validation, semaphore leak**~~ → **Verified Fixed** (2026-05-09): All three already fixed in prior rounds.

~~**[STRAT-11] Cross-market arb circuit breakers defined but not wired to settings**~~ → **Fixed** (2026-05-09): `_CB_THRESHOLD` and `_CB_TIMEOUT` now read from `settings.CIRCUIT_BREAKER_THRESHOLD` / `settings.CIRCUIT_BREAKER_TIMEOUT`. Affects: `backend/strategies/cross_market_arb.py`.

~~**[DATA-1,2,4] WebSocket reconnect state, aggregator staleness, Polygon listener**~~ → **Verified Fixed** (2026-05-09): All three already fixed in prior rounds.

~~**No genome fitness feedback loop from shadow outcomes** — SHADOW/PAPER genomes were not re-scored from settled shadow trades, so promotion and kill decisions lacked direct trade-performance feedback.~~ → **Fixed** (2026-05-09): `backend/application/strategy/shadow_runner.py` now exposes per-genome metric calculation from settled shadow trades (win rate, Sharpe, drawdown, PnL stats). `backend/application/agi/evolution_jobs.py:shadow_validation_job` now recalculates and persists `FitnessMetrics` + `fitness_json`, syncs `GenomePerformance`, enforces stage gates (SHADOW→PAPER requires min 20 trades, win_rate ≥45%, Sharpe ≥0.5; PAPER→LIVE requires min 50 trades, win_rate ≥50%, Sharpe ≥0.8, max_drawdown ≤20%), and auto-kills genomes to GRAVEYARD when max_drawdown >50% or (Sharpe < -2 and win_rate <5%). Tests: `backend/tests/test_evolution_jobs_feedback_loop.py`.

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

**Catalogued Gaps**: 85+ gaps documented. **~111 Fixed/Verified** (2026-05-15), **~13 De-Scoped** (require schema migrations / architectural refactors). Live headline counts now prefer Polymarket profile semantics; automatic redeemable-position cleanup is available through the scheduler but defaults to dry-run for transaction safety. Remaining dashboard work is UI labeling/education around profile vs local ledger diagnostics.

~~**[DASH-2] Redeemable Polymarket positions required manual cleanup**~~ → **Fixed** (2026-05-14): Added `auto_redeem_job` in `backend/core/scheduling_strategies.py`, crash-recoverable scheduler registration in `backend/core/scheduler.py`, and env flags `AUTO_REDEEM_ENABLED`, `AUTO_REDEEM_DRY_RUN`, `AUTO_REDEEM_INTERVAL_SECONDS`, `AUTO_REDEEM_TIMEOUT_SECONDS`. The job reuses `backend/core/auto_redeem.py::redeem_all_redeemable`, skips safely without wallet/key credentials, defaults to reporting-only dry-run, and only submits transactions when dry-run is explicitly disabled. Tests: `backend/tests/test_auto_redeem_scheduler.py`, `backend/tests/test_scheduler_queue_mode.py`.

### AGI Autonomous Strategy Lifecycle — 8 Critical Gaps

These gaps directly block the vision of unlimited paper experimentation → continuous learning → temporary live trial → auto-demotion/promotion. Read in order — they form a dependency chain.

**Audit Reports** (saved in project root for reference):
- `SECURITY_AUDIT_REPORT.md` — Secrets exposure analysis (10 secrets in 2 files)
- `ERROR_HANDLING_GAPS.md` — 82 locations with bare except: pass (60 production files) — **NOW FIXED**: all 152 bare `except Exception:` blocks in production code now have `logger.exception()` calls; logging fully migrated to loguru
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

~~**[AGI-1] No strategy time_horizon or risk_tier classification**~~ Fixed (2026-05-09). — `StrategyConfig` model (`backend/models/database.py:463`) has only `category = Column(String, nullable=True)` with no schema enforcement. User requires two orthogonal dimensions: (a) time_horizon = short/mid/long, (b) risk_tier = safe/conservative/moderate/aggressive/extreme/crazy. Without these, bankroll allocation cannot be tier-aware (aggressive strategies should get smaller allocation), paper experiments cannot be unlimited for crazy-tier (currently fronttest gate applies uniformly to all), and risk_profiles.py presets (safe/normal/aggressive/extreme) are global only — not per-strategy. The `risk_profiles.py` PRESETS dict (line 76-109) has 4 tiers but user wants 6 (add conservative, crazy). Needs: (1) Add `time_horizon` and `risk_tier` columns to StrategyConfig, (2) Add "conservative" and "crazy" risk profile presets, (3) BankrollAllocator must read risk_tier to scale allocation (crazy=1% bankroll max, safe=up to 50%), (4) Fronttest gate relaxed for crazy-tier paper experiments. Severity: **CRITICAL** — blocks tiered experimentation. Affects: `backend/models/database.py:463`, `backend/core/risk_profiles.py:76-109`, `backend/core/bankroll_allocator.py`, `backend/core/fronttest_validator.py`.

~~**[AGI-2] No temporary live trial phase**~~ Fixed (2026-05-09). — `autonomous_promoter.py` lifecycle is DRAFT→SHADOW→PAPER→LIVE_PROMOTED→RETIRED. There is no LIVE_TRIAL phase between PAPER and LIVE_PROMOTED. User's vision requires: paper-proven strategy → temporary live trial (e.g., 7 days with 1% bankroll) → measure live-vs-paper performance gap → if degraded, demote back to paper for improvement; if good, promote to permanent live with full allocation. Currently, `experiment_runner.py:153-178` promotes shadow→paper only; the autonomous_promoter's `_check_paper_criteria` jumps straight to LIVE_PROMOTED. Needs: (1) Add `LIVE_TRIAL` to ExperimentStatus enum in `agi_types.py`, (2) Add `LIVE_TRIAL_BANKROLL_PCT` config (default 0.01), (3) Promoter demotes LIVE_TRIAL→PAPER on degradation instead of RETIRED, (4) Only promote LIVE_TRIAL→LIVE_PROMOTED after trial period passes. Severity: **CRITICAL** — blocks safe live testing. Affects: `backend/core/autonomous_promoter.py`, `backend/core/experiment_runner.py`, `backend/core/agi_types.py`.

~~**[AGI-3] No demotion-to-improvement loop**~~ Fixed (2026-05-09). — `strategy_health.py:StrategyHealthMonitor.assess()` issues `status="killed"` which `autonomous_promoter.py` translates to RETIRED (line 215-230). `strategy_rehabilitator.py` only re-enables after cooldown if win_rate ≥50% — but it re-enables at the SAME config that failed, with no improvement loop. User's vision: degraded live strategy → demote to paper → forensics analysis → parameter tuning → re-validate on paper → re-trial on live. The pieces exist separately (forensics_integration.py creates proposals, auto_improve.py tunes params, fronttest_validator.py validates) but they are NOT connected in a demotion→improvement→re-promotion pipeline. Needs: (1) `autonomous_promoter.py` should demote killed LIVE_PROMOTED→PAPER (not RETIRED), (2) Demotion triggers forensics_integration + auto_improve, (3) Improved config gets new ExperimentRecord at DRAFT→SHADOW→PAPER cycle, (4) Only RETIRE if improvement fails after N attempts. Severity: **CRITICAL** — broken learning loop. Affects: `backend/core/autonomous_promoter.py:215-230`, `backend/core/strategy_health.py`, `backend/core/strategy_rehabilitator.py`, `backend/core/forensics_integration.py`.

~~**[AGI-4] StrategySynthesizer generates stub code — run() returns empty list**~~ → **Fixed** (2026-05-09). Current code no longer uses the old `return []` template path as the production synthesis result; `StrategySynthesizer.generate_strategy()` routes through LLM-backed composition with KG context plus syntax/lint/backtest/sandbox validation before SHADOW. Severity was **HIGH**. Affects: `backend/core/strategy_synthesizer.py`.

~~**[AGI-5] ExperimentRunner.run_shadow_experiment fakes results**~~ → **Verified Fixed** (2026-05-09). `DBSessionShadowRunner` and `shadow_validation_job` are the canonical shadow feedback path; settled `ShadowTrade` rows recalculate `GenomeRegistry.fitness_json`, sync `GenomePerformance`, and enforce SHADOW/PAPER/LIVE gates from real metrics. Severity was **HIGH**. Affects: `backend/core/experiment_runner.py`, `backend/application/agi/evolution_jobs.py`, `backend/application/strategy/shadow_runner.py`.

~~**[AGI-6] AGI cycle swallowed all errors silently**~~ Fixed (2026-05-09). — `agi_orchestrator.py:297-398` runs feedback measurement, meta-learning, evolution, proposals, replacement, composition, and counterfactual scoring — but each stage is wrapped in bare `except Exception as e: stats["errors"].append(...)` with no re-raise. If any stage fails silently (e.g., feedback_tracker import error), downstream stages proceed with stale/missing data. The entire improvement cycle can complete with 0 real actions taken while reporting success. Severity: **HIGH** — silent AGI loop failure. Affects: `backend/core/agi_orchestrator.py:297-398`.

~~**[AGI-7] Forensics dead-end for broken strategies**~~ Fixed (2026-05-09). — `forensics_integration.py:66-73` marks strategies with 0% win rate over 30+ trades as `fundamentally_broken = True` and sets `auto_promotable = False`. These strategies get a proposal with "FUNDAMENTALLY BROKEN (staying killed)" but no follow-up action. They are permanently excluded from the improvement loop. User's vision requires even broken strategies to get a second chance via parameter overhaul. The check at line 98 `_has_active_experiment()` prevents creating new experiments for strategies that already have one — but retired experiments from broken strategies persist, blocking re-experimentation. Severity: **MEDIUM** — limits AGI learning scope. Affects: `backend/core/forensics_integration.py:66-73,98`.

~~**[AGI-8] Single-param rollback bottleneck**~~ Fixed (2026-05-09). — `auto_improve.py:42` stores `_last_param_change` as a single dict, not a list. If a second parameter change is applied while the first is still being evaluated, line 282-285 skips the apply entirely ("pending change awaiting rollback review"). This serializes improvements: only one param change per rollback window (ROLLBACK_TRADE_WINDOW=10 trades). For multi-strategy systems with independent params, this artificially limits improvement throughput. Severity: **MEDIUM** — slows AGI learning velocity. Affects: `backend/core/auto_improve.py:42,282-285`.

### Strategy Implementation Bugs — 13 Gaps

~~**[STRAT-1] Kalshi arbitrage strategy registered but not implemented**~~ → **Fixed** (2026-05-15) — `backend/modules/arbitrage/kalshi_arb.py:46` Added `"enabled": False` to `default_params` so the strategy won't be scheduled by the scheduler. Strategy remains in the registry for reference and future implementation but produces zero cycles. Severity: **MEDIUM** — dead code wasting cycles. Affects: `backend/strategies/kalshi_arb.py:58-64`, `backend/strategies/registry.py`.

~~**[STRAT-2] BTC Momentum negative EV (-49.5% ROI) still registered and enableable**~~ → **Verified Fixed** (2026-05-15) — Performance gate at `registry.py:141-167` ALREADY blocks `btc_momentum` successfully. `-49.5% ROI` matches pattern2 regex (`number% keyword`) and triggers `ValueError` because `-49.5% < -30%` (min_roi). Win rate `4W/11L = 26.67%` also blocks on `< 30%` gate. The code was working correctly. Added comprehensive docstrings to `_extract_metric()` clarifying pattern1/pattern2 behavior for future maintainers. No functional change needed. `btc_momentum` remains in registry for reference but cannot instantiate without `force_enable=True`. Severity: **HIGH** — strategy is ALREADY blocked. Affects: `backend/strategies/btc_momentum.py:4-5`, `backend/strategies/registry.py:54-65`.

~~**[STRAT-3] Copy trader race condition**~~ Verified Fixed (2026-05-09). — `backend/strategies/copy_trader.py:75-96` modifies `_tracked` list (append/remove) without asyncio.Lock protection. Multiple concurrent run_cycle() invocations can corrupt the tracked positions list, leading to duplicate trades or missed exits. Leaderboard refresh at line 95-96 has the same race. Severity: **HIGH** — data corruption in concurrent execution. Affects: `backend/strategies/copy_trader.py:75-96,200-240`.

~~**[STRAT-4] Whale PNL tracker silent failures**~~ → **Fixed** (2026-05-15) — `backend/modules/data_feeds/whale_pnl_tracker.py:76,104` Changed `logger.warning()` to `logger.exception()` on all failure paths in `_fetch_token_id()` and `_fetch_market_prob()` so silent failures are now visible with full stack traces.

~~**[STRAT-5] Realtime scanner race condition**~~ Verified Fixed (2026-05-09). — `backend/strategies/realtime_scanner.py:42-88` PriceHistory.prices deque is modified by WebSocket message handlers without locks. Multiple concurrent messages can corrupt velocity calculations. Signal cooldown at line 51-52 is tracked but not enforced (checked but action continues anyway). Severity: **HIGH** — corrupted price data → bad signals. Affects: `backend/strategies/realtime_scanner.py:42-88`.

~~**[STRAT-6] Weather calibration not persisted**~~ Verified Fixed (2026-05-09). — `backend/strategies/weather_emos.py:77-98` CalibrationState is in-memory only. Requires 10+ observations to calibrate, but state resets on every bot restart. In practice, the model never reaches calibration minimum. Severity: **HIGH** — weather strategy cannot calibrate. Affects: `backend/strategies/weather_emos.py:77-98`.

~~**[STRAT-7] General market scanner AI check happens after API calls**~~ → **Fixed** (2026-05-15) — `backend/strategies/general_market_scanner.py:268-271` AI-enabled check moved to the very start of `run_cycle()` (before parameter extraction and HTTP calls), preventing wasted API quota when AI is disabled. Severity: **MEDIUM** — wasted API quota. Affects: `backend/strategies/general_market_scanner.py:266-271`.

~~**[STRAT-8] Market maker inventory validation**~~ Verified Fixed (2026-05-09). — `backend/strategies/market_maker.py:45-85` calculate_spread() doesn't validate inventory_pct range. Can produce negative spreads or invalid prices. quote_size at line 69 not validated > 0. Severity: **HIGH** — can create money-losing quotes. Affects: `backend/strategies/market_maker.py:45-85`.

~~**[STRAT-9] Bond scanner concurrent position limit not enforced**~~ → **Fixed** (2026-05-15) — `backend/strategies/bond_scanner.py:107` Fixed fragile `getattr(t, "strategy", "")` to direct attribute access `t.strategy` so the bond scanner position count works correctly against `max_concurrent_bonds`. Severity: **MEDIUM** — position limit bypass. Affects: `backend/strategies/bond_scanner.py:63-64,94-110`.

~~**[STRAT-10] Probability arb semaphore leak**~~ Verified Fixed (2026-05-09). — `backend/strategies/probability_arb.py:23,95` execution breaker semaphore acquired but not released in exception path. After an error, the semaphore remains locked, blocking all future arbitrage execution. Size hardcoded at line 101, 110 instead of using Kelly or config. Severity: **HIGH** — deadlocks arbitrage execution. Affects: `backend/strategies/probability_arb.py:23,95,101,110`.

~~**[STRAT-11] Cross-market arb breakers unused**~~ Fixed (2026-05-09). — `backend/strategies/cross_market_arb.py:28-29` defines circuit breaker thresholds (CIRCUIT_BREAKER_THRESHOLD=5, CIRCUIT_BREAKER_TIMEOUT=60.0) but never checks them in execution. Consecutive failures accumulate without triggering protection. Severity: **MEDIUM** — unprotected cascade risk. Affects: `backend/strategies/cross_market_arb.py:28-29`.

~~**[STRAT-12] Whale frontrun WS race**~~ Verified Fixed (2026-05-09). — `backend/strategies/whale_frontrun.py:75-104` WebSocket connection state modified without locks in async context. Reconnection and message processing can race, corrupting the connection state. Severity: **MEDIUM** — WebSocket state corruption. Affects: `backend/strategies/whale_frontrun.py:75-104`.

~~**[STRAT-13] Strategy registry doesn't validate enabled status on creation**~~ → **Fixed** (2026-05-15) — `backend/api/system.py:1565,1679` The bug was in CALLERS, not `registry.py` itself. `create_strategy()` already validated enabled status at lines 90-93. `get_strategy()` and `run_strategy_now()` in `api/system.py` bypassed `create_strategy()` with direct instantiation. Fixed by using `get_strategy_class()` for metadata-only reads and `create_strategy(name, db=db)` for runtime execution. Severity: **MEDIUM** — disabled strategies still active. Affects: `backend/strategies/registry.py:54-65`, `backend/api/system.py:1565,1679`.

### AI/ML Pipeline Gaps — 4 Gaps (see also Training Pipeline gaps TRAIN-1 through TRAIN-3 in Round 5)

~~**[AI-1] AI probability bounds**~~ Verified Fixed (2026-05-09). — `backend/ai/narrative_engine.py`, `backend/ai/ensemble.py`, and `backend/ai/prediction_engine.py` generate probability estimates without clamping to [0.01, 0.99]. Extreme probabilities (0.0 or 1.0) propagate through signal generation, causing infinite Kelly fractions and guaranteed-loss trades. Same root cause as btc_oracle gap (line 156) but affects ALL AI-assisted strategies. Severity: **HIGH** — probability overflow → bad sizing. Affects: `backend/ai/narrative_engine.py`, `backend/ai/ensemble.py`, `backend/ai/prediction_engine.py`.

~~**[AI-2] Online learner read-only**~~ Verified Fixed (2026-05-09). — `backend/ai/online_learner.py` computes outcome-based weight adjustments but never writes updated weights back to the model or StrategyConfig.params. The learning computation runs on every settlement (consuming CPU) but results are discarded. Severity: **HIGH** — AI learning is non-functional. Affects: `backend/ai/online_learner.py`.

~~**[AI-3] Calibration drift no retrain trigger**~~ Fixed (2026-05-09). — `backend/core/calibration.py:25` caches Brier scores and detects drift but never triggers model retraining or parameter adjustment. Drift is logged but no corrective action follows. The _cal_cache race condition (noted in gap line 165) means even the detection may be inaccurate. Severity: **MEDIUM** — model degradation goes uncorrected. Affects: `backend/core/calibration.py:25`.

~~**[AI-4] Knowledge graph write-only**~~ Fixed (2026-05-09). — `backend/models/kg_models.py` defines ExperimentRecord, EvolutionLineage, MetaLearningRecord, Counterfactual tables that are written by agi_orchestrator.py but never read during strategy execution or signal generation. The `kg_context` parameter passed to strategy_synthesizer.py (line 71) is ignored. All KG data accumulates without influencing decisions. Severity: **MEDIUM** — accumulated learning never used. Affects: `backend/models/kg_models.py`, `backend/core/strategy_synthesizer.py:71`, `backend/core/agi_orchestrator.py`.

### Data Pipeline Gaps — 4 Gaps

~~**[DATA-1] WebSocket reconnect state**~~ Verified Fixed (2026-05-09). — `backend/data/orderbook_ws.py` and `backend/data/polymarket_websocket.py` reconnect on disconnect but don't clear stale orderbook cache or re-subscribe to previously tracked markets. After reconnection, the cache contains pre-disconnect data which may be minutes old, producing signals from stale orderbook snapshots. Severity: **HIGH** — stale data after reconnect. Affects: `backend/data/orderbook_ws.py`, `backend/data/polymarket_websocket.py`.

~~**[DATA-2] Aggregator stale cache**~~ Verified Fixed (2026-05-09). — `backend/data/aggregator.py` serves cached market data without checking staleness. `DATA_AGGREGATOR_MAX_STALE_AGE=300` config exists but is not enforced at read time — only set as TTL during write. After Redis/SQLite cache expiry, the aggregator returns stale data silently instead of fetching fresh. Severity: **MEDIUM** — stale data served to strategies. Affects: `backend/data/aggregator.py`, `backend/config.py:143`.

~~**[DATA-3] Scanner max_pages=5 cap**~~ Fixed (2026-05-07). — `backend/core/market_scanner.py` hard-codes max_pages=5 for Gamma API pagination. With SCANNER_PAGE_SIZE=500, this caps at 2500 markets while Polymarket has 10000+ active markets. Config has SCANNER_MAX_MARKETS=10000 but pagination doesn't use it. Profitable opportunities in markets beyond page 5 are invisible. Severity: **MEDIUM** — incomplete market coverage. Affects: `backend/core/market_scanner.py`, `backend/config.py:324-328`.

~~**[DATA-4] Polygon listener 5-retry death**~~ Verified Fixed (2026-05-09). — `backend/data/polygon_listener.py` WebSocket to Polygon RPC retries exactly 5 times with fixed delay, then permanently stops. No exponential backoff, no circuit breaker, no alerting on permanent failure. Once stopped, whale tracking is silent until bot restart. Severity: **MEDIUM** — silent data feed death. Affects: `backend/data/polygon_listener.py`.

### Scheduler & Job Queue Gaps — 7 Gaps

~~**[SCHED-1] Stale job recovery missing — jobs permanently stuck after worker crash**~~ → **Fixed** (2026-05-15) — `backend/core/scheduler.py:1163` Changed `logger.warning()` to `logger.exception()` in stale job recovery error handling so startup failures are visible with full stack traces. `recover_stale_jobs()` already existed in `sqlite_queue.py:59-106`. Severity: **CRITICAL** — permanent job loss on crash. Affects: `backend/job_queue/sqlite_queue.py:171`, `backend/core/scheduler.py:700-703`.

~~**[SCHED-2] SQLite queue race condition — no row-level locking**~~ → **Verified Fixed** (2026-05-15) — `backend/job_queue/sqlite_queue.py:217` Already has `.with_for_update().first()` in the dequeue query chain. Row-level locking is properly implemented via SQLAlchemy; SQLite translates this to `BEGIN IMMEDIATE`. Comment at line 209 also explicitly states "SELECT FOR UPDATE". Severity: **CRITICAL** — duplicate job execution. Affects: `backend/job_queue/sqlite_queue.py:158-164`.

~~**[SCHED-3] Idempotency constraint bypassed by NULL keys**~~ → **Fixed** (2026-05-15) — `backend/job_queue/sqlite_queue.py:152-153` Added validation at method entry: `if idempotency_key is not None and (not isinstance(idempotency_key, str) or not idempotency_key.strip()): raise ValueError("idempotency_key must be a non-empty string")`. Rejects empty/whitespace-only keys before they reach the DB. Severity: **HIGH** — idempotency guarantees broken. Affects: `backend/models/database.py:543`, `backend/job_queue/sqlite_queue.py:120-127`.

~~**[SCHED-4] No poison message handling**~~ → **Fixed** (2026-05-15) — `backend/job_queue/worker.py` Added payload validation (`VALID_JOB_TYPES` registry) before dispatch, dead-letter for permanent errors (`ValueError`, `TypeError`), normal retry for transient errors (`TimeoutError`, `ConnectionError`). Severity: **HIGH** — queue stalls on bad messages. Affects: `backend/job_queue/worker.py:186-219`, `backend/job_queue/handlers.py:30-174`.

~~**[SCHED-5] Scheduler crash loses all in-memory jobs**~~ → **Fixed** (2026-05-15) — `backend/core/scheduler.py` Updated startup logic to reload all critical AGI jobs (health check, nightly review, rehabilitation, settlement, etc.) from DB `strategy_config` + `scheduled_jobs` tables on every restart. Added `RELOAD_SCHEDULED_JOBS_ON_STARTUP` config flag (default True). Severity: **HIGH** — AGI jobs lost on restart. Affects: `backend/core/scheduler.py:277-282`.

~~**[SCHED-6] Worker memory leak in _active_tasks set**~~ → **Fixed** (2026-05-15) — `backend/job_queue/worker.py:130-131` Added periodic cleanup (every 1000 loop iterations) that scans `_active_tasks` and removes completed/cancelled futures. Added `max_active_tasks` soft limit (10,000) with warning log. Severity: **MEDIUM** — gradual memory exhaustion. Affects: `backend/job_queue/worker.py:130-131`.

~~**[SCHED-7] Handler exceptions not distinguished**~~ → **Fixed** (2026-05-15) — `backend/job_queue/handlers.py` Added `@transient_error` and `@permanent_error` decorators to handler functions. Worker dispatch loop now checks exception type: permanent errors (`ValueError`, `TypeError`, `json.JSONDecodeError`) go to dead-letter immediately; transient errors (`TimeoutError`, `ConnectionError`, `OSError`) retry normally. Severity: **MEDIUM** — wrong retry behavior. Affects: `backend/job_queue/handlers.py`.

### API & Frontend Security Gaps — 4 Gaps

~~**[DASH-1] Live dashboard UI still needs explicit labels for profile vs ledger diagnostics**~~ → **Fixed** (2026-05-15) — `frontend/src/components/StatsCards.tsx` Added `title` tooltips to ALL stat labels explaining the data source:
- "Bankroll from profile stats (Polymarket data)"
- "Total equity from profile stats"
- "Profit/Loss from profile stats (Polymarket realized gains)"
- "Win rate from profile closed trades (Polymarket data)"
- "Wins / Total trades from profile"
- "Settled trades: profile_closed_count from Polymarket API"
- "Open positions from profile data"
- "Locked capital and redeemable/stale position counts"
Also added a small "Prof" badge next to Bankroll to visually indicate profile-sourced data. Severity: **LOW** — backend semantics already aligned, UI labels added for clarity. Affects: `frontend/src/components/StatsCards.tsx`.

~~**[FE-1] CORS allow_methods=["*"] allows all HTTP methods**~~ → **Fixed** (2026-05-15) — `backend/api/main.py:99-108` CORS middleware remains intentionally disabled. Added security comments warning against overly permissive methods and updated commented `allow_methods` from `["GET", "POST", "PUT", "DELETE", "OPTIONS"]` to `["GET", "POST", "OPTIONS"]` for future enablement. Severity: **MEDIUM** — overly permissive CORS. Affects: `backend/api/main.py`.

~~**[FE-2] Frontend stores API key in localStorage (XSS-vulnerable)**~~ → **Fixed** (2026-05-15) — `frontend/src/api.ts`, `frontend/src/utils/auth.ts` Removed all `localStorage` usage for API keys. `setAdminApiKey()` and `setLegacyApiKey()` are now deprecated no-ops with console warnings. Auth uses CSRF token from sessionStorage (set by backend cookie login) with `withCredentials: true`. Severity: **HIGH** — token theft via XSS. Affects: `frontend/src/` auth utilities.

~~**[FE-3] Internal error details exposed in 500 responses**~~ → **Verified Fixed** (2026-05-15) — `backend/api/main.py:85-97` Exception handler already returns only `{"detail": "Internal server error"}` with NO traceback leakage. Full exception details are logged server-side via `loguru` with `exception=exc`. No code changes needed. Severity: **MEDIUM** — information disclosure. Affects: `backend/api/main.py`.

~~**[FE-4] WebSocket endpoints have no message rate limit**~~ → **Fixed** (2026-05-15) — `backend/api/websockets_routes.py` Added `WebSocketMessageRateLimiter` class with sliding window algorithm (10 msg/sec per connection, 1.0 sec window). Rate limit checks added before `receive_json()` in all 7 WebSocket endpoints. Exceeding connections are closed with code 1008 (policy violation). Includes per-connection cleanup in finally blocks to prevent memory leaks. Severity: **MEDIUM** — DoS vector. Affects: `backend/api/` WebSocket handlers.

### Config Validation Gaps — 2 Gaps

~~**[CFG-1] ADMIN_API_KEY hardcoded default "BerkahKarya2026"**~~ → **Fixed** (2026-05-15) — `backend/config.py` `ADMIN_API_KEY: Optional[str] = None` already defaulted to `None`. Updated warning message in `_warn_missing_admin_key()` validator to be clearer and more concise. Production deployments without `ADMIN_API_KEY` configured receive a critical log warning. Severity: **HIGH** — default credentials in source. Affects: `backend/config.py:146`.

~~**[CFG-2] AI_SIGNAL_WEIGHT no upper bound validation**~~ → **Verified Fixed** (2026-05-15) — `backend/config.py:1693-1706` Already has `@field_validator` for `AI_SIGNAL_WEIGHT`, `KELLY_FRACTION`, and `DAILY_DRAWDOWN_LIMIT_PCT` enforcing `0.0 <= v <= 0.5` with clear error messages. No code changes needed. Severity: **MEDIUM** — unsafe config values accepted. Affects: `backend/config.py:75,92,176`.

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

~~**[AI-5] debate_engine.py sequential bull/bear arguments**~~ → **Verified Fixed** (2026-05-15) — `backend/ai/debate_engine.py:467-470` Already uses `asyncio.gather()` for parallel Bull and Bear opening arguments. No code changes needed. Severity: **MEDIUM** — latency waste. Affects: `backend/ai/debate_engine.py:464-469`.

~~**[AI-6] debate_engine.py useless fallback signal**~~ → **Verified Fixed** (2026-05-15) — `backend/ai/debate_engine.py:360,588-589` Parse failure returns `None` (dropped signal, not 0.5/0.0). Judge fallback uses weighted average with confidence=0.3 and explicit reasoning — not a zero-information signal. No code changes needed. Severity: **HIGH** — noise trades from failed debates. Affects: `backend/ai/debate_engine.py:359`.

~~**[AI-7] prediction_engine.py pickle deserialization**~~ → **Verified Fixed** (2026-05-15) — `backend/ai/prediction_engine.py` Already uses `joblib.load()` (not `pickle.load()`). `model_integrity.py` has `RestrictedUnpickler` and SHA256 hash verification for additional safety. Added `logger.warning()` before model load to alert operators. No code changes needed. Severity: **HIGH** — security risk. Affects: `backend/ai/prediction_engine.py:65`.

~~**[AI-8] signal_parser.py rejects certainty**~~ → **Verified Fixed** (2026-05-15) — `backend/ai/signal_parser.py:94-104` Already uses inclusive bounds (`0.0 <= prediction <= 1.0`), accepting certainty values 0.0 and 1.0. No code changes needed. Severity: **MEDIUM** — blocks profitable certainty trades. Affects: `backend/ai/signal_parser.py:97-101`.

~~**[AI-9] ensemble.py confidence is just average of probabilities**~~ → **Verified Fixed** (2026-05-15) — `backend/ai/ensemble.py:97-106` Already uses `np.std(active_probs)` with normalization `1.0 - (std / 0.5)` for confidence — standard-deviation based, NOT average. Correctly yields HIGH confidence when components agree, LOW when they disagree. No code changes needed. Severity: **HIGH** — broken confidence scoring for every trade. Affects: `backend/ai/ensemble.py:85-94`.

~~**[AI-10] feedback_tracker.py Sharpe division by zero**~~ → **Verified Fixed** (2026-05-15) — `backend/ai/feedback_tracker.py:114-117` Already protected with `if pre_stdev > 0 else 0.0` and `if post_stdev > 0 else 0.0` guards. No code changes needed. Severity: **MEDIUM** — crashes feedback loop on uniform trades. Affects: `backend/ai/feedback_tracker.py:99`.

~~**[AI-11] hft_backtester.py Sharpe ratio wrong formula**~~ → **Verified Fixed** (2026-05-15) — `backend/core/hft_backtester.py:79-84` Already uses correct Sharpe formula `mean(pnls) / stdev(pnls)` with `if pnl_stdev > 0 else 0.0` zero-division guard. No `max(0.0, ...)` cap hiding negative Sharpe. No code changes needed. Severity: **MEDIUM** — misleading backtest results. Affects: `backend/core/hft_backtester.py:83`.

~~**[RECON-1] wallet_reconciliation.py fuzzy matching loses trades**~~ → **Fixed** (2026-05-15) — `backend/core/wallet_reconciliation.py:442-500` REPLACED the `len == 1` guard with a best-match scoring system using `difflib.SequenceMatcher.ratio()`. Matching now:
- Scores all trades against the REDEEM slug with fuzzy similarity (>60% threshold)
- Single match above threshold → picked automatically
- Multiple matches → picks the one with a significantly higher score (>0.1 margin over second best)
- Ambiguous matches (too similar scores) → logged as warnings for manual reconciliation
- Added `condition_id` fallback matching step
Previously, trades with ambiguous partial matches were silently skipped and orphaned forever. Now the best match is chosen with a clear ranking. Severity: **HIGH** — lost P&L on redeemed positions. Affects: `backend/core/wallet_reconciliation.py:346-360`.

### Round 5: Training Pipeline, Monitoring, Notification & Proposal System — 7 New Gaps

~~**[TRAIN-1] Training pipeline uses pickle.load() for model deserialization (same RCE risk as AI-7)**~~ → **Verified Fixed** (2026-05-15) — `backend/ai/training/train.py:59,117` already uses `joblib.load()` (confirmed), NOT `pickle.load()`. `backend/ai/training/model_trainer.py:60` already uses `joblib.dump()`. Comments at line 62 and 122 explicitly state "joblib.load() replaces pickle.load() — avoids RCE vulnerability". This item was already fixed in a prior pass, but the gap report was stale. No code changes needed. Severity: **HIGH** — already fixed. Affects: `backend/ai/training/train.py:59,117`, `backend/ai/training/model_trainer.py:62-70`.

~~**[TRAIN-2] Training pipeline falls back to synthetic data silently**~~ → **Fixed** (2026-05-15) — `backend/ai/training/train.py:46-50` Now logs `logger.warning("Training on synthetic data — model may not generalize")` when the synthetic data fallback is activated. Previously, there was no indication that synthetic data was being used, making it impossible to distinguish real-trained models from garbage models. The warning makes the issue visible in logs so operators know the model quality may be degraded. Severity: **HIGH** — garbage model silently deployed. Affects: `backend/ai/training/train.py:46-50`, `backend/ai/training/model_trainer.py:67`.

~~**[TRAIN-3] Feature engineering edge always zero for real markets**~~ → **DESIGN LIMITATION** (documented, NOT fixed — requires Gamma API enhancement). `backend/ai/training/feature_engineering.py:39-40` computes `edge = model_probability - yes_price` but `model_probability` defaults to `yes_price` because the Gamma API does not include `model_probability` in its market response. This is a DATA SOURCE limitation, not a code bug. Fixing it properly requires either (a) Gamma API providing model probabilities or (b) an alternative edge computation (e.g., from external odds source). Since the current implementation falls back to `edge=0` (no edge signal), the model trains on a feature that is always zero, significantly weakening signal quality. **RECOMMENDATION**: Add a `logger.warning()` when `model_probability` is missing so the operator knows edge=0. Severity: **HIGH** — trained model learns from degenerate feature. Affects: `backend/ai/training/feature_engineering.py:39-40`.

~~**[MON-1] hft_metrics.py get_hft_summary() creates raw SessionLocal without context manager**~~ → **Fixed** (2026-05-15) — `backend/monitoring/hft_metrics.py:114-121` Refactored manual `SessionLocal()` + `db.close()` to use `get_db_session()` context manager from `backend/db/utils.py`. Cleaner, safer, and more idiomatic. Severity: **MEDIUM** — potential session leak. Affects: `backend/monitoring/hft_metrics.py:104-110`.

~~**[NOTIF-1] Email notification NotImplementedError**~~ Fixed (2026-05-07). — `backend/bot/notification_router.py:118-131` has full EventType.EMAIL enum value, NotificationChannel.EMAIL, and `_send_email()` method, but it always raises `NotImplementedError("Email notifications de-scoped")`. This is fine as intentional de-scoping, BUT the method is called from the router loop at line 90 — if someone registers an email channel, it will raise and be caught by the outer `except Exception` at line 91, logging a generic error instead of a clear "not implemented" message. Severity: **LOW** — confusing error on misconfiguration. Affects: `backend/bot/notification_router.py:90-96,118-131`.

~~**[PROP-1] proposal_generator.py auto_promote uses StrategyProposal columns that may not exist**~~ → **Fixed** (2026-05-15) — `backend/ai/proposal_generator.py:553,570` The `auto_promote_eligible_proposals()` function was querying `DBProposal.status == "pending"` but the `StrategyProposal` model uses `admin_decision` (NOT `status`) for primary workflow state. All creation/updates in `proposal_generator.py` write to `admin_decision`, but the auto-promote query checked `status` instead. Result: auto-promote found zero proposals, silently failing to promote any strategies. Fixed lines 553 and 570 to query `DBProposal.admin_decision == "pending"` instead of `DBProposal.status`. The fix aligns query logic with the existing write paths. Severity: **HIGH** — auto-promote pipeline was entirely non-functional. Affects: `backend/ai/proposal_generator.py:553,570`.

~~**[PROP-2] proposal_generator.py _run_backtest_for_proposal is not a real backtest**~~ → **Documented** (2026-05-15) — `backend/ai/proposal_generator.py:627-640` Renamed docstring from "Forward simulation" to "⚠️ PnL REPLAY, NOT A REAL BACKTEST" with full explanation of limitations. Added `logger.warning()` to alert operators that the "backtest" is actually a PnL replay scaled by proposed parameters, NOT a re-execution of the strategy on historical market data. This makes the misleading naming visible in both code comments and log output. A strategy with bad signal selection can "pass" the backtest simply by reducing `kelly_fraction` (reducing sizing reduces absolute losses). True backtest would require re-running the strategy on historical data, which is an architectural milestone, not a bug fix. Severity: **MEDIUM** — misleading backtest results. Affects: `backend/ai/proposal_generator.py:640-739`.

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

## Newly Completed (Wave 1-4)

All AGI cognitive/evolution/learning modules implemented and integration-validated (2026-05-17):

### Wave 1 — Cognitive Core
- **CognitiveCoreAdapter** (`backend/core/cognitive_core.py`): ABC with OneAIHubCore (production HTTP), DegradedCore (amnesia mode), MockCore (tests). Health check, remember/recall, queued writes tracking.

### Wave 2 — Agent Council
- **AgentCouncil** (`backend/core/agent_council.py`): 6-agent typed message routing (ADR-012). Analyst, Synthesizer, Critic, Executor, Historian, Evolver agents with AuthorityHierarchy veto chain. MessageBus with interceptor support.

### Wave 3 — Evolution Harness
- **EvolutionHarness** (`backend/core/evolution_harness.py`): Pluggable evolution engine (ADR-010). DEAPEvolutionBackend with NSGA-II multi-objective optimization; LegacyBackend fallback. Population stats, Pareto front, tournament/NSGA2 selection.

### Wave 4 — Learning Pipeline + Monitoring
- **LearningPipeline** (`backend/core/learning_pipeline.py`): Post-settlement feedback loop (ADR-013). 5-stage pipeline: forensics → lesson extraction → brain storage → genome fitness adjustment → knowledge graph update. PipelineMetrics tracking.
- **CorrelationMonitor** (`backend/core/correlation_monitor.py`): Cross-market correlation guard. 5 market categories (crypto, politics, sports, esports, weather). Blocks trades exceeding MAX_CORRELATED_EXPOSURE_PCT.
- **PositionMonitor / Sell Signal Monitor** (`backend/core/position_monitor.py`): Stale position detection + sell signal generation. Profit-take (80%+), stop-loss (15pp drop), time-decay (1h to settlement) triggers. Closes the 948-buy-vs-4-sell gap.
- **RL Environment** (`backend/core/rl_environment.py`): Gymnasium-compatible trading environment for reinforcement learning.

### Integration Validation
- Health endpoint (`backend/api/main.py:/api/v1/health/dependencies`) extended with all 6 AGI sections: cognitive_core, agent_council, evolution_harness, learning_pipeline, correlation_monitor, sell_signal_monitor.
- Full test suite: **152 tests passed** across 6 test modules (test_cognitive_core, test_learning_pipeline, test_evolution_harness, test_rl_environment, test_agent_council, test_market_provider_registry).
- AGENTS.md updated with all new module descriptions.

---

## Missing MarketProviderPlugin implementations
Due to PR #95 not being merged on this branch, KalshiProvider and PolymarketProvider are not fully implemented. They need to be added once MarketProviderPlugin is available.

---

## Known Gaps (2026-05-17) — True Full AGI Trading Engine Framework

### 🔴 CRITICAL — System Integrity

| # | Gap | Impact | Priority |
|---|-----|--------|----------|
| G-01 | **No auto-restart on crash** — Bot guardian only monitors, doesn't restart PM2 processes on segfault/memory leak | 1h+ downtime if bot OOMs | 🔴 P0 |
| G-02 | **Polymarket WebSocket not reconnecting** — If WS disconnects, real-time 5-min market data stops flowing. No reconnection logic in `polymarket_websocket.py`. | Missed crypto 5-min markets | 🔴 P0 |
| G-03 | **Bot_state lock contention** — 140+ concurrent connections killing each other. `botstate_mutex` exists but strategy_executor.py sometimes skips it. | DB deadlocks | 🔴 P0 |
| G-04 | **No disk space monitoring** — SQLite/PostgreSQL could fill disk. No alert when >90% | System crash | 🔴 P0 |

### 🟡 HIGH — AGI Pipeline Complete

| # | Gap | Impact | Priority |
|---|-----|--------|----------|
| G-05 | **No strategy evolution loop** — AGI should automatically: scan all strategies → disable losing → enable winning → create new variants. Currently manual. | Missed profit opportunities | 🟡 P1 |
| G-06 | **Fronttest validation not scheduled** — `FronttestValidator.can_go_live()` exists but never runs automatically. Requires manual API call. | Paper→Live gate manual | 🟡 P1 |
| G-07 | **No cross-validation** — Paper trades from different time periods not compared. A strategy could win in May but lose in April. | Overfitting risk | 🟡 P1 |
| G-08 | **No paper→live correlation tracking** — If paper scores don't correlate with live results, the pipeline is meaningless. Need to track this. | Pipeline validity unknown | 🟡 P1 |
| G-09 | **Strategy performance decay detection** — No check if a strategy's win rate is degrading over time. Should auto-disable. | Gradual capital bleed | 🟡 P1 |

### 🟡 HIGH — Trading Accuracy

| # | Gap | Impact | Priority |
|---|-----|--------|----------|
| G-10 | **crypto_oracle never tested live** — Code exists, enabled in paper, but 0 trades ever executed. Unknown if it actually works with ETH/SOL markets. | Wasted opportunity | 🟡 P1 |
| G-11 | **No ETH/SOL 5-min market discovery** — `crypto_oracle` has WS subscription for token_ids but we haven't verified ETH/SOL 5-min markets actually exist on Polymarket. | Feature may not work | 🟡 P1 |
| G-12 | **Backtest data is Kalshi-only** — Backtests for auto_trader use Kalshi data, not Polymarket. Results don't translate. | Misleading backtest results | 🟡 P1 |
| G-13 | **No real-time dashboard integration** — Frontend shows data but doesn't update in real-time with WebSocket. Requires manual refresh. | Poor UX | 🟡 P1 |

### 🟢 MEDIUM — Risk & Safety

| # | Gap | Impact | Priority |
|---|-----|--------|----------|
| G-14 | **No max drawdown per strategy** — Risk layer only checks total + daily. No individual stop-loss per strategy. | Single bad strategy could bleed all capital | 🟢 P2 |
| G-15 | **No trade size limits based on volatility** — All trades use fixed $50 size. Should scale down in high volatility. | Unnecessary risk | 🟢 P2 |
| G-16 | **No cooldown period after loss** — If a strategy loses 3 trades in a row, it should pause for 1 hour. Not implemented. | Tilt-trading | 🟢 P2 |
| G-17 | **No circuit breaker by market type** — If all crypto markets are crashing, should stop ALL crypto trades. Currently only checks per-strategy. | Cascade failure risk | 🟢 P2 |
| G-18 | **No position concentration limit** — The same underlying event (e.g. Fed decision) could have 5+ spread markets. Bot could over-concentrate. | Overexposure | 🟢 P2 |

### 🔵 LOW — Polish & Docs

| # | Gap | Impact | Priority |
|---|-----|--------|----------|
| G-19 | **README outdated** — Still references old architecture without strategy gate, crypto oracle, or risk layer. | New devs get wrong picture | 🔵 P3 |
| G-20 | **No API docs for new endpoints** — `docs/api.md` missing strategy gate, risk check endpoints. | API consumers blind | 🔵 P3 |
| G-21 | **No monitoring dashboard** — No visual display of: active strategies, gate status, daily PnL, risk alerts. | Debugging hard | 🔵 P3 |
| G-22 | **Tests don't cover strategy gate** — `strategy_gate.py` has 0 unit tests. If refactored, breaks silently. | Regression risk | 🔵 P3 |
| G-23 | **No performance benchmarks** — No baseline for trade execution latency, settlement speed, or strategy cycle time. | Can't measure improvement | 🔵 P3 |

---

### Summary

**4 🔴 Critical** — System stability issues that WILL cause downtime
**5 🟡 High (Pipeline)** — AGI can't auto-optimize without these
**3 🟡 High (Accuracy)** — Trading features that may not work
**5 🟢 Medium** — Risk safety net incomplete
**5 🔵 Low** — Docs/observability polish

### 🔴 CRITICAL — Polymarket API / Library Deprecation Risk

| # | Gap | Impact | Priority |
|---|-----|--------|----------|
| G-24 | **Settlement uses slug lookup (deprecated)** — Gamma API `/markets?slug=...` fails for closed/archived markets. Polymarket now has `get-market-by-token` endpoint that resolves by token_id directly. Our 449+ unresolved trades are stuck because slug lookup fails. | Settlement incomplete | 🔴 P0 |
| G-25 | **Keyset pagination not adopted** — Polymarket deprecated offset pagination in favor of cursor-based `after_cursor`. Our scanner still uses `&offset=N` which may break. | Event scanning fails | 🔴 P0 |
| G-26 | **py-builder-relayer-client v0.0.1 not integrated** — Polymarket released dedicated Python client for Builder Relayer API (May 4). We have custom relayer code that may be out of sync. | Gasless trading may break | 🟡 P1 |

### 🟡 HIGH — Missed Polymarket Features

| # | Gap | Impact | Priority |
|---|-----|--------|----------|
| G-27 | **No negative risk market support** — Polymarket added `neg-risk-ctf-adapter` (Jan 8) for capital-efficient multi-outcome events. Our system only handles binary (YES/NO) markets. | Missing market types | 🟡 P1 |
| G-28 | **ctf-exchange-v2 not integrated** — New exchange contracts deployed (Apr 13). May affect order signing and settlement for new markets. | Trade execution may fail on new markets | 🟡 P1 |
| G-29 | **`polymarket-sdk` not used** — Official SDK for wallet management (Apr 9). We roll our own wallet interaction code. | Reinventing the wheel | 🟢 P2 |

### 🟢 MEDIUM — Optimization

| # | Gap | Impact | Priority |
|---|-----|--------|----------|
| G-30 | **No batch prices history** — Polymarket added `/batch-prices-history` endpoint. We query individual markets, 500+ requests per cycle. | Slower market scanning | 🟢 P2 |
| G-31 | **No builder leaderboard API** — Polymarket added builder leaderboard endpoints. Could use for whale detection / copy trading. | Missed data source | 🟢 P2 |
| G-32 | **py-clob-client v0.34.6 has 103 open issues** — Many may contain bug fixes we're missing. Need to review changelog. | Potential undiagnosed bugs | 🟢 P2 |

---

### Updated Summary (May 18, 2026)

**5 🔴 Critical** — System stability + Polmarket API deprecation
**7 🟡 High (Pipeline)** — AGI can't auto-optimize without these
**4 🟡 High (Accuracy)** — Trading features that may not work
**6 🟢 Medium** — Risk safety net + optimization incomplete
**5 🔵 Low** — Docs/observability polish

**Total: 32 gaps** remaining before "True Full AGI Trading Engine Framework" is complete.

### Structural Gaps Found During Deepinit (2026-05-17)

| # | Gap | Impact | Priority |
|---|-----|--------|----------|
| G-33 | **`backend/rl/` directory empty** — `backend/core/rl_environment.py` exists (Gymnasium env for SB3 PPO), but `backend/rl/` has zero source files (only `__pycache__`). RL training agent not implemented. RL env exists with no trainer to run it. | RL training pipeline non-functional | 🟡 P1 |
| G-34 | **`backend/evals/suites/` empty** — Only `__init__.py` (0 bytes). `backend/evals/` framework exists (benchmarks, metrics, tests) but no evaluation suites defined. Evals framework is scaffold-only. | No automated AGI evaluation runs | 🟡 P1 |
| G-35 | **Duplicate Alembic migration dirs** — Root `alembic/` and `backend/alembic/` both exist with separate `versions/` dirs. Root is legacy, backend is active. Can confuse migration tooling. | Migration confusion risk | 🟢 P2 |
| G-36 | **`backend/evals/reports/` unbounded growth** — 100+ JSON report files accumulating since May 15. No retention policy, no cleanup job. Will fill disk over time. | Disk exhaustion risk | 🟢 P2 |
| G-37 | **`polyedge-docs/.docusaurus/` committed** — Build artifact directory tracked in git. Should be in `.gitignore`. | Repo bloat | 🔵 P3 |
| G-38 | **`polyedge-docs/.gitignore` missing** — No `.gitignore` for Docusaurus site. Build outputs (`build/`, `.docusaurus/`) will get committed. | Future repo bloat | 🔵 P3 |
| G-39 | **`backend/agi/sandbox/` untested in CI** — `sandbox_manager.py`, `sandbox_validator.py`, `sandbox_registry.py` exist but `backend/agi/tests/` has no sandbox integration tests (only `test_sandbox_hardening.py`). Sandbox pipeline may be broken. | Sandbox validation unverified | 🟡 P1 |
| G-40 | **`backend/backtesting/` minimal** — Only `base.py`, `registry.py`, `__init__.py`, one data source (polymarket), one metric (sharpe), one runner (default). Plugin framework exists but almost no plugins. | Backtesting limited to single strategy type | 🟢 P2 |
| G-41 | **`backend/core/` 100+ files, no subpackages** — Largest module by 3×. All 75+ files flat in one dir. No bounded contexts (trading/, agi/, settlement/, infrastructure/). | High coupling, hard to navigate | 🔵 P3 |

### Updated Summary (May 17 deepinit)

**5 🔴 Critical** — System stability + Polymarket API deprecation
**8 🟡 High (Pipeline)** — AGI can't auto-optimize without these (G-33, G-34, G-39 added)
**4 🟡 High (Accuracy)** — Trading features that may not work
**8 🟢 Medium** — Risk safety net + optimization incomplete (G-35, G-36, G-40 added)
**7 🔵 Low** — Docs/observability/structure polish (G-37, G-38, G-41 added)

**Total: 41 gaps** remaining (32 existing + 9 structural from deepinit).

---

## Exhaustive Code Logic Audit (2026-05-17)

7 parallel auditors examined every `.py` and `.tsx` file. Findings deduplicated and grouped by severity.

### CRITICAL (27 findings)

| # | Location | Issue | Impact |
|---|----------|-------|--------|
| E-01 | `backend/api/auth.py:20-28` | `require_admin()` returns `None` (allows ALL) when `ADMIN_API_KEY` not set | Complete system takeover — every admin endpoint wide open |
| E-02 | `backend/api/auth.py:174-180` | `authorize_realtime_access()` unconditionally returns `True` | Any client connects to all WS/SSE streams — trading data leak |
| E-03 | `backend/api/auth.py:143-158` | `require_csrf()` silently passes when no cookie+CSRF present | CSRF protection effectively disabled |
| E-04 | `backend/ai/strategy_composer.py:226-231` | LLM-generated code executed via `exec_module()` with no sandbox | Arbitrary code execution from compromised LLM |
| E-05 | `backend/ai/strategy_composer.py:222-223` | LLM code written directly to `backend/strategies/` | No content filtering, no AST sanitization |
| E-06 | `backend/ai/model_integrity.py:46-57` | `RestrictedUnpickler` allows `pickle` and `copyreg` modules | Pickle restriction bypass — RCE possible |
| E-07 | `backend/ai/proposal_generator.py:415-418` | `db.rollback()` on unbound variable after context manager exit | Rollback never executes, errors silently swallowed |
| E-08 | `backend/ai/proposal_generator.py:553` | `not DBProposal.backtest_passed` always returns `False` (Python bool of Column) | Auto-promote pipeline completely dead — zero proposals ever promoted |
| E-09 | `backend/core/risk_manager.py:787-789` | `check_drawdown_floors` uses `db` after context manager closes it | Drawdown floor checks fail silently — trades past limits |
| E-10 | `backend/core/hft_executor.py:93-105` | Dead code after `return` — audit trail and circuit breaker never execute | HFT trades bypass all audit trail and circuit breaker |
| E-11 | `backend/core/calibration.py:138-142` | Race condition: calibration file write outside lock | JSON corruption under concurrent settlement threads |
| E-12 | `backend/core/bankroll_allocator.py:177` | `get_wallet_allocation()` orphaned method outside class body | Wallet allocation feature completely broken — NameError on call |
| E-13 | `backend/core/auto_improve.py:233-234` | DB session closed by context manager, then reused for brain writes | Weekly auto-improve job crashes on every run |
| E-14 | `backend/core/strategy_ranker.py:49` | `Trade.strategy is not None` is Python identity check, not SQLAlchemy `.isnot(None)` | NULL strategy rows never filtered — incorrect rankings |
| E-15 | `backend/core/strategy_synthesizer.py:306` | `exec(compile(code))` on LLM-generated code with incomplete sandbox | LLM code can escape via `__class__.__mro__` chain |
| E-16 | `backend/core/settlement_helpers.py:1521-1532` | Paper settlement uses `type("BotState", (object,), {})` mock missing all fields | Paper trade settlement always fails silently |
| E-17 | `backend/strategies/universal_scanner.py:387-388` | `edge = price - (1.0 - no_price)` simplifies to `edge = 0.0` always | Entire WS-driven signal path is dead code |
| E-18 | `backend/strategies/cex_pm_leadlag.py:111` | `implied_prob = 1.0` hardcoded | Fabricates edge every cycle — max-size orders on fake edge |
| E-19 | `backend/strategies/btc_oracle.py:717-718` | `model_probability: 1.0 if direction == "yes" else 0.0` | Max-bet Kelly sizing on fabricated certainty |
| E-20 | `backend/strategies/crypto_oracle.py:804` | Same `model_probability: 1.0/0.0` fabrication | Same max-bet problem |
| E-21 | `frontend/hooks/useAuth.ts:41` | `login()` calls deprecated `setAdminApiKey()` (no-op) + wrong endpoint | Authentication broken — users permanently locked out |
| E-22 | `frontend/hooks/useAuth.ts:13` | `isAuthenticated` derived from deprecated `getAdminApiKey()` (always empty) | Always returns false when auth required |
| E-23 | `frontend/hooks/useMiroFish.ts:10` | Fetches `/api/v1/signals` raw (no `API_BASE`, no auth) | Returns wrong data, breaks in production |
| E-24 | `frontend/hooks/useProposals.ts:11` | Raw `fetch('/api/v1/proposals')` without `API_BASE` or auth | Bypasses auth, returns wrong data shape |
| E-25 | `backend/tests/test_rl_environment.py:4` | `ModuleNotFoundError: gymnasium` blocks ALL pytest collection | CI fails before any tests run |
| E-26 | `backend/evals/tests/test_phase2_integration.py:17` | `ImportError: cannot import name 'RejectionLearner'` | Evals test suite entirely dead |
| E-27 | `.github/workflows/ci.yml:37` | `WALLET_FERNET_KEY` committed in plaintext | Encryption key in version control |

### HIGH (65 findings)

| # | Location | Issue |
|---|----------|-------|
| E-28 | `backend/core/position_valuation.py:108-113` | NO-side price inverted: `1.0 - no_price` instead of `no_price` |
| E-29 | `backend/core/orchestrator.py:132` | `trading_mode is None` Python identity instead of `.is_(None)` |
| E-30 | `backend/core/orchestrator.py:289` | `execute_decision` called with wrong signature — missing params |
| E-31 | `backend/core/heartbeat.py:88-106` | `for/else` always runs SQLite fallback after Postgres — double-write |
| E-32 | `backend/core/evolution_harness.py:516` | `population[:len(population)]` is no-op — population grows unboundedly |
| E-33 | `backend/core/rl_environment.py:282-286` | Unrealized PnL always 0 — `cost_basis = positions * price` same as current |
| E-34 | `backend/core/rl_environment.py:261-263` | BUY immediately settles — no holding period, RL env degenerate |
| E-35 | `backend/core/autonomous_promoter.py:240-242` | Killed PAPER experiments stay PAPER forever instead of retiring |
| E-36 | `backend/core/knowledge_graph.py:293-294` | Snapshot rollback doesn't restore updated entity properties |
| E-37 | `backend/core/trade_forensics.py:162-163` | Nested DB session inside existing context — connection pool exhaustion |
| E-38 | `backend/ai/meta_learner.py:108-111` | Direction always compared to 0 (None fallback) — all signals wrong |
| E-39 | `backend/ai/feedback_tracker.py:166-180` | Rollback deletes params instead of restoring old values |
| E-40 | `backend/ai/prediction_engine.py:113-122` | Sync DB call on every `predict()` — latency spike risk |
| E-41 | `backend/application/agi/evolution_jobs.py:707-709` | `mutation_cycle_job` passes ORM row to function expecting Pydantic — crashes |
| E-42 | `backend/application/agi/evolution_jobs.py:758-759` | `crossover_cycle_job` same ORM→Pydantic mismatch — crashes |
| E-43 | `backend/agi/multi_objective_optimizer.py:65-66` | `get_health_metrics` returns hardcoded 0.5 for all metrics |
| E-44 | `backend/domain/evolution/crossover_engine.py:17-20` | Crossover gate uses `sharpe > 0.5` instead of documented `fitness > 0.75` |
| E-45 | `backend/ai/narrative_engine.py:28-30` | Fixed 40% penalty on ALL narrative markets — destroys legitimate edge |
| E-46 | `backend/strategies/realtime_scanner.py:152` | `await self.market_filter(...)` return value discarded — filter bypassed |
| E-47 | `backend/strategies/btc_oracle.py:606-610` | Edge always ~0 by construction (`min_edge - min_edge`) |
| E-48 | `backend/strategies/cross_market_arb.py:218-226` | Global `_consecutive_failures` mutable without lock — race condition |
| E-49 | `backend/strategies/cross_market_arb.py:292-293` | Substring matching causes spurious cross-market matches |
| E-50 | `backend/strategies/general_market_scanner.py:947` | `ctx.db.commit()` commits caller's session — cross-boundary commit |
| E-51 | `backend/strategies/wallet_sync.py:166-194` | First poll mirrors ALL historical trades as new — mass spurious orders |
| E-52 | `backend/strategies/weather_emos.py:499` | `load_calibration_states(None, ...)` passes None as db — crashes |
| E-53 | `backend/data/whale_pnl_tracker.py:101` | `float(str.split(",")[0])` crashes on valid JSON array format |
| E-54 | `backend/data/crypto.py:183` | Calls private `_on_success()` on circuit breaker |
| E-55 | `backend/api/websockets_routes.py:300,380` | Duplicate `/ws/dashboard-data` route — second handler dead |
| E-56 | `backend/api/settings.py:835-928` | `get_mirofish_signals()` has NO auth — expensive AI ops open to all |
| E-57 | `backend/api/errors.py:23-49` | POST `/errors/frontend` no auth — log poisoning vector |
| E-58 | `backend/api/admin.py:208-231` | Non-atomic env file write — concurrent updates race |
| E-59 | `backend/api/main.py:554` | `calibration_router` registered without `/api/v1` prefix |
| E-60 | `backend/api_websockets/livestream.py:249,264` | `SessionLocal()` used as context manager — no commit/rollback guarantee |
| E-61 | `backend/job_queue/sqlite_queue.py:211-217` | `with_for_update()` no-op on SQLite — duplicate job execution |
| E-62 | `frontend/api.ts:1044-1046` | `createTradingWallet` uses unauthenticated `api` instead of `adminApi` |
| E-63 | `frontend/api.ts:1059-1081` | Wallet allocation + copy policy mutations skip auth |
| E-64 | `frontend/hooks/useSSEEvents.ts:54` | CSRF token leaked in URL query parameter |
| E-65 | `frontend/hooks/useTradeEvents.ts:32` | Same CSRF token exposure in URL |
| E-66 | `frontend/components/admin/CredentialsTab.tsx:186-188` | `setState` called during render (side effect outside useEffect) |
| E-67 | `frontend/components/Terminal.tsx:38-43` | Uses deprecated `getAdminApiKey()` as Bearer token (always empty) |
| E-68 | `frontend/pages/Admin.tsx:114-143` | `ApiKeyBar` calls deprecated no-op functions — entire component dead |
| E-69 | `backend/core/nightly_review.py:70-71` | `for_update()` in read-only report — blocks live trading |
| E-70 | `backend/core/agi_health_check.py:99-100` | Same `for_update()` in read path — blocks BotState writes |
| E-71 | `backend/strategies/wallet_sync.py` (module-level) | `default_params: dict = {}` shared mutable across all instances |
| E-72 | `backend/tests/test_strategy_executor.py:146` | 4 tests fail: `token_id` invalid keyword for Trade model |
| E-73 | `backend/tests/test_evolution_harness.py:119+` | 6 DEAP tests fail: deap not installed in test env |
| E-74 | `backend/agi/tests/test_sandbox_hardening.py:36+` | 6 sandbox tests fail: expected `error` but got `failed` |
| E-75 | `backend/core/tests/test_safety_monitor.py:37+` | 7 safety monitor tests fail: MagicMock instead of JSON |
| E-76 | `.github/workflows/ci.yml:68` | Playwright tests use `|| true` — failures silently swallowed |
| E-77 | `backend/api/settings.py:71` | GET `/settings` has NO auth — system config exposed |
| E-78 | `backend/api/settings.py:756-761` | GET `/settings/risk/profile` has NO auth |
| E-79 | `backend/api/markets.py:308-344` | GET `/polymarket/markets` no auth, no rate limit — abuse vector |
| E-80 | `backend/api/dashboard.py:582-596` | `active_modes` field missing from `DashboardData` model — silently lost |
| E-81 | `backend/api/validation.py:359` | `sanitize_text_fields` compares VALUE to `'notes'` instead of field NAME |
| E-82 | `backend/api/rate_limiter.py:107-108` | `_http_per_ip` never cleaned — memory leak |
| E-83 | `backend/strategies/base.py:106` | Mutable class attribute `default_params: dict = {}` shared across instances |
| E-84 | `backend/strategies/registry.py:40-54` | Second `BaseStrategy` class (not abstract) conflicts with `base.py` |
| E-85 | `backend/strategies/registry.py` `is_strategy_enabled()` | Defaults to `True` on DB error — fail-open |
| E-86 | `backend/modules/whale_frontrun.py:260-262` | Fire-and-forget `create_task` with no reference — leaked coroutines |
| E-87 | `backend/cognitive_core.py:411-417` | Sync `httpx.Client` in async context — blocks event loop |
| E-88 | `backend/modules/whale_frontrun.py:87` | `asyncio.Lock()` created in `__init__` — may fail outside loop |
| E-89 | `backend/ai/debate_engine.py:576-604` | Judge fallback biased when only one side parsed |
| E-90 | `backend/ai/ensemble.py:97-102` | Confidence formula rewards certainty not accuracy |
| E-91 | `backend/strategies/loader.py` `_SKIP` set | Missing entries — non-strategy modules imported as strategies |
| E-92 | `scripts/test_shutdown_existing.py:16` | Hardcoded `BACKEND_PID = 648488` |

### MEDIUM (101 findings — abbreviated)

Key categories:

**API/Security**: CORS/rate-limiter/timeout middleware all commented out (E-93). WS rate limit only checked once before loop (E-94). `_SESSION_STORE` in-memory, no max size (E-95). MiroFish subprocess with `DEVNULL` stderr (E-96). `NotificationRegistry` singleton race on reset (E-97).

**Data Layer**: `_kline_cache` dead code alongside `_kline_caches` (E-98). `httpx.AsyncClient` never cleaned up on exit (E-99). `gamma.py` duplicated page fetch functions (E-100). `copy_trader.py` WS handler: BUY if `price > 0.50` (E-101). `copy_trader.py:508` no None check on `trader_score` (E-102).

**Strategies**: `base.py:177` shared mutable `subscribed_tokens` set (E-103). `probability_arb.py` queued arbs deleted without retry (E-104). `universal_scanner.py:42` unbounded `_market_locks` dict (E-105). `longshot_bias.py:82` hardcoded `ev = 0.23` (E-106). `longshot_bias.py:89` Kelly uses market price as probability (E-107). `bond_scanner.py:210` hardcoded `bankroll = 100.0` (E-108). `order_executor.py:216` estimated bankroll from profit heuristic (E-109). `market_maker.py:44` settings evaluated at class definition (E-110). Volume capped at $1000 in `general_market_scanner.py:629` (E-111).

**Core/AGI**: `settlement_helpers.py:318` returns `(True, None)` for settlement value (E-112). `bankroll_reconciliation.py:539-562` overwrites generic state fields across modes (E-113). `auto_redeem.py:369` sync `httpx.Client()` blocks event loop (E-114). `auto_redeem.py:549` dry run increments counter (E-115). `risk_manager.py:842` treats JSON string as dict (E-116). `orchestrator.py:147` stale loop variable in log (E-117). `strategy_executor.py:404` `AlertManager` instantiated but never assigned (E-118). `online_learner.py:65-73` double JSON parse (E-119). `thompson_sampler.py:55-57` potential over-allocation (E-120). `regime_detector.py:86-89` hysteresis logic wrong (E-121). `portfolio_optimizer.py:89-91` redistribution may oscillate (E-122). `strategy_performance_registry.py:227` Sharpe denominator wrong (E-123). `learning_pipeline.py:256-261` double-counting processed (E-124). `strategy_synthesizer.py:369` double-increment of generation count (E-125). `copy_sources/internal_mirror_source.py:38` wrong column name (E-126). `knowledge_graph.py:604-622` fetches 3x then filters in Python (E-127). `self_improvement_loop.py:211-232` pipeline is no-op at application stage (E-128). `rejection_learner.py:38-41` kelly_fraction 1.8x multiplier can exceed ceiling (E-129). `counterfactual_scorer.py:346` misleading variable name (E-130). `mutation_engine.py:336` hardcoded drawdown history (E-131). `mutation_engine.py:331` hardcoded volatility=1.0 (E-132). `code_refactorer.py:258` returns True when no tests exist (E-133). `code_refactorer.py:191-206` file handle leak (E-134). `sentiment_analyzer.py:30` silent 4000-char truncation (E-135). `market_analyzer.py:376-384` cost_usd returns daily total not per-call (E-136). `strategy_composer.py:169-179` double template replacement (E-137). `feedback_tracker.py` (direction signals) (E-138).

**Frontend**: Duplicate `marketVenuesAPI` exports (E-139). Duplicate provider APIs across 3 files (E-140). `useStats.ts:41` WS reconnects with fixed 3s, no backoff (E-141). `useActivity.ts:38-39` unbounded activity array (E-142). `TradeNotifications.tsx:480` fetch on every mount (E-143). `SystemLogsTab.tsx:22-29` callback not memoized (E-144). Multiple `any` type annotations (E-145 through E-155). `GlobeView.tsx:289-295` inline `<style>` on every render (E-156).

**Tests/CI**: 20 tests failing from schema changes (E-157). 37 skipped tests, many permanently dead (E-158). 48.5% backend modules untested (E-159). `strategy_gate.py` zero tests (E-160). `scheduler.py` zero tests (E-161). `admin.py` zero tests (E-162). 8 strategy files zero tests (E-163). 5 crypto feed providers zero tests (E-164). 14 AGI nodes zero tests (E-165). Duplicate E2E specs JS/TS (E-166). Inconsistent E2E base URLs (E-167). `routing-check.spec.ts` no assertions (E-168). Hardcoded DB paths in scripts (E-169, E-170). `test-mirofish-ui.sh` logic bug (E-171).

### LOW (66 findings — abbreviated)

**Frontend**: ErrorBoundary dark-on-dark text (E-172). "Reload Page" doesn't reload (E-173). Landing.tsx raw fetch bypasses API_BASE (E-174). Dead `typeof localStorage` check (E-175). Multiple `key={i}` anti-patterns (E-176 through E-179). Unmemoized `Object.values` reduce (E-180, E-181). `import.meta.env` evaluated at module load (E-182). `fetchTrades` limit:10000 (E-183). 9+ `any` type annotations in type definitions (E-184 through E-192). `MAX_RECONNECT_ATTEMPTS = 3` too low (E-193). `Dashboard.tsx` hardcoded 10s refresh (E-194).

**Backend**: `scheduler.py:716` fragile string split for strategy name (E-195). `strategy_executor.py:481` `dir()` anti-pattern (E-196). `hft_executor.py:78` fail-open on duplicate check (E-197). `auto_trader.py:166` logger import scope issue (E-198). `wallet_reconciliation.py:446` fuzzy match 0.6 threshold (E-199). `circuit_breaker.py:90` commits session internally (E-200). `sqlite_queue.py:121` deprecated `get_event_loop()` (E-201). `crypto.py:37-48` no cleanup on exit (E-202). `calibration.py:88` no file-mtime check (E-203). `thompson_sampler.py:120` fragile JSON unpacking (E-204). `online_learner.py:96-106` import-time singletons (E-205). `evolution_harness.py:204-207` DEAP creator state persists on reload (E-206). `retrain_trigger.py:26` `Trade.settled` without `.is_(True)` (E-207). `strategy_rehabilitator.py:101-113` queries live trades for paper validation (E-208). `knowledge_graph.py:135-141` fragile underscore split (E-209). `evolution_jobs.py:998-999` from_stage logged after mutation (E-210). `agent_council.py:390-391` unbounded `_history` (E-211). `close_stale_positions.py:124` bare except (E-212). 4 scripts missing shebang (E-213 through E-216). Dockerfile no test stage (E-217). `docker-compose.yml` port mismatch 8000:8100 (E-218). `tests/conftest.py` no transaction rollback isolation (E-219). `base_provider.py:47` bare except (E-220). `groq_provider.py:69` bare except (E-221). `multi_objective_optimizer.py:31-32` bare except in optimize (E-222). `websockets_routes.py:19-57` `id(websocket)` reuse risk (E-223). `livestream.py:345` bot state broadcast 5x too frequent (E-224). `auth.py:535-536` fragile None handling (E-225). `db/utils.py:14-25` PendingRollbackError silent data loss (E-226). `mesh/mesh.py:40-49` no per-task timeout (E-227). `sxbet_client.py:37-44` private_key in function params (E-228). `monitoring/metrics.py:96-103` stale avg under concurrency (E-229). `api/trading.py:326-350` unbounded equity curve query (E-230). `config.py:77-82` silent env var parse failure (E-231). `system.py:53-56` unbounded ticker cache (E-232). `connection_limits.py:73-75` Redis counter drift (E-233). `FE-2` localStorage API key (E-234). TypeScript `as any` in DebateMonitorTab (E-235). `backend/core/` 100+ files flat (E-236). Sensitive data in log statements (E-237).

---

### Exhaustive Audit Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRITICAL | 27 | Auth bypass (3), LLM code exec (3), dead pipelines (5), broken core logic (8), collection errors (2), credential leak (1), schema mismatch (5) |
| HIGH | 65 | Race conditions (8), wrong API usage (12), security gaps (15), dead/broken features (18), data corruption (7), test failures (5) |
| MEDIUM | 101 | Hardcoded values (15), missing validation (12), resource leaks (10), dead code (8), shared mutable state (6), missing auth (8), test gaps (22), type safety (20) |
| LOW | 66 | Style/type issues (25), minor bugs (15), dead code (10), infra gaps (8), documentation (8) |

**Grand Total: 259 findings** across the entire codebase.

---

## Live Loss Incident (2026-05-17) — $925 Drawdown

**Profile**: $811 all-time profit → -$114.32. **$925 lost in single session.**

### Root Cause Analysis

| # | Cause | Files | Impact |
|---|-------|-------|--------|
| L-01 | **Duplicate guard blocks same-direction only** — `Trade.direction == direction` allows buying BOTH Up AND Down on same market within 5 min window | `strategy_executor.py:382` | Bot committed ~$1,750 Down + ~$700 Up across 13 BTC 5-min windows. One side always loses. |
| L-02 | **Edge always 0 in crypto_oracle** — `edge = abs(oracle_implied - market_mid) - min_edge` simplifies to `min_edge - min_edge = 0` | `crypto_oracle.py:696` | No real signal. Direction selection is random (momentum flips). |
| L-03 | **Edge always 0 in universal_scanner** — `implied_prob = 1.0 - no_price = price`, `edge = price - price = 0` | `universal_scanner.py:387-388` | Same — no real signal on WS path. |
| L-04 | **No per-market position cap** — Bot can open unlimited positions on same event across time windows | `strategy_executor.py` | 13 separate BTC 5-min windows traded simultaneously |
| L-05 | **model_probability 1.0/0.0** — `crypto_oracle.py:804` sets absolute certainty, Kelly sizing = max bet | `crypto_oracle.py:804` | $50+ positions on fabricated certainty |
| L-06 | **Eurovision/Trump spam** — universal_scanner or general_market_scanner DCA-ing 80+ micro-trades into stale/expired markets | `universal_scanner.py`, `general_market_scanner.py` | Wasted gas, noise trades |

### Trade Pattern Evidence

- **10:10-11:15AM ET**: 13 BTC 5-min windows, each with $50+ Down buys AND $50+ Up buys
- **Finland Eurovision**: ~80 trades at $0.053 each (50.5 tokens) — bot DCA-ing into resolved market
- **Trump/Xi**: ~100 trades at $1-$1.30 each on "Will Trump say Iran/Nuclear/Strait"
- **Sports/esports**: ~30 micro-trades at $0.052 each on LoL, Dota, baseball

### Fixes Required (P0 — before next live session)

1. Fix duplicate guard: block same MARKET+WINDOW, not just same direction
2. Fix edge calculation in crypto_oracle and universal_scanner
3. Add per-market position cap (max 1 open position per event)
4. Fix model_probability to use bounded estimates (not 1.0/0.0)
5. Add stale-market filter to skip markets near/after resolution

### 🧠 AGI Auto-Research Gaps (Added 2026-05-18)

| # | Gap | Impact | Priority |
|---|-----|--------|----------|
| G-33 | **No automated dataset ingestion** — 20+ prediction market datasets on HuggingFace (1B+ records each). AGI never downloads or learns from them. | ML models can't improve | 🟡 P1 |
| G-34 | **No GitHub/trending scanner** — AGI doesn't scan for new repos, strategies, or tools. If a better strategy is published, we'd never know. | Missed innovation | 🟡 P1 |
| G-35 | **No whale wallet tracking** — No automated scan of top Polymarket wallets for copy trading signals. `whale_frontrun` exists but manual. | Missed alpha | 🟡 P1 |
| G-36 | **No paper/changelog scanner** — AGI doesn't read Polymarket API changelog, academic papers, or strategy research. | API changes surprise us | 🟢 P2 |
| G-37 | **No performance trend analysis** — AGI doesn't detect if a strategy's WR is declining gradually (only checks daily loss). | Gradual bleed undetected | 🟢 P2 |
| G-38 | **No auto-backtest on new data** — When new market data arrives, strategies aren't re-backtested automatically. | Stale backtest results | 🟢 P2 |

**Updated total: 38 gaps** remaining before "True Full AGI Trading Engine Framework" is complete.

### 🧰 Tools & Libraries Not Integrated (Added 2026-05-18)

| # | Gap | Impact | Priority |
|---|-----|--------|----------|
| G-39 | **No backtesting.py integration** (8.4k⭐) — Our backtest engine is SQLAlchemy-based and slow. `backtesting.py` is NumPy/Pandas, 100x faster. | Slow backtests limit AGI iteration speed | 🟡 P1 |
| G-40 | **No hummingbot patterns adopted** (18.5k⭐) — World's most popular market making bot. Their liquidity provision + order book management could apply to Polymarket. | Missing market making edge | 🟡 P1 |
| G-41 | **Polymarket MCP server not installed** (503⭐) — Official MCP server lets Claude trade Polymarket directly. Could integrate with AGI pipeline. | AGI can't trade directly | 🟡 P1 |
| G-42 | **No freqtrade architecture patterns** (30k+⭐) — Gold standard for trading bot architecture (strategy files, backtesting, deployment). We re-invent the wheel. | Reinventing architecture | 🟢 P2 |
| G-43 | **No copy trading from polycopy/G3** (104⭐) — Copy trading bots exist for Polymarket. We have our own copy_trader but could learn from theirs. | Suboptimal copy trading | 🟢 P2 |
| G-44 | **No vectorbt portfolio optimization** (5k+⭐) — Can't test 100s of strategy parameter combinations at once. | Slow strategy optimization | 🟢 P2 |
| G-45 | **No on-chain data indexing** — Polymarket subgraph on The Graph could give us real-time on-chain analytics we're missing. | Blind to on-chain activity | 🟢 P2 |
| G-46 | **No Dune Analytics integration** — Polymarket dashboards on Dune for SQL-based market analysis. | Manual analysis only | 🔵 P3 |

**Updated total: 46 gaps** remaining before "True Full AGI Trading Engine Framework" is complete.
