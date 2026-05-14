<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/core

## Purpose
The trading engine — execution routing, risk management, settlement, circuit breakers, AGI lifecycle, background scheduling, and all cross-cutting infrastructure. This is the most-edited and most critical directory in the codebase.

## Key Files by Group

### Execution & Routing
| File | Description |
|------|-------------|
| `auto_trader.py` | Execution router — routes high-confidence signals to immediate execution, low-confidence to approval queue. **Not a strategy.** Live CLOB calls must stay timeout-bounded. |
| `strategy_executor.py` | Creates trades in paper mode, places orders in live mode; trade/attempt persistence must commit before any best-effort `BotState` counter sync so `bot_state` lock contention cannot roll back durable trade records; all live CLOB waits must stay bounded so the bot cannot hang indefinitely on broker I/O |
| `signals.py` | Signal model and signal routing logic |
| `trade_attempts.py` | `TradeAttemptRecorder` — durable ledger for all execution attempts (executed and rejected) |
| `trade_role.py` | Trade role classification utilities |

### Risk & Circuit Breakers
| File | Description |
|------|-------------|
| `risk_manager.py` | Validates trades against position size, exposure, drawdown, confidence, and per-strategy allocation caps |
| `risk_manager_hft.py` | HFT-specific risk manager with tighter latency constraints |
| `risk_profiles.py` | Risk profile presets + DB-backed overrides; missing `risk_profiles` table must fall back to presets without startup traceback spam |
| `circuit_breaker.py` | Circuit breaker implementation (CLOSED/OPEN/HALF_OPEN state machine) |
| `circuit_breaker_pybreaker.py` | pybreaker-based circuit breaker variant |
| `market_risk.py` | Market-level risk calculations |
| `validation.py` | Trade and signal input validation |

### Settlement
| File | Description |
|------|-------------|
| `settlement.py` | Core settlement logic — resolves trades, updates BotState; must hold `botstate_mutex`; wallet-gone positions may become `closed_unresolved` to release exposure when external resolution lags |
| `settlement_capture.py` | Captures settlement events from exchange |
| `settlement_helpers.py` | Settlement utility functions, `SettlementEvent`/`TransactionEvent` emission, and live position reconciliation; optional analytics/learner hooks must be rollback-isolated from the main settlement transaction |
| `settlement_ws.py` | WebSocket-based settlement event listener |
| `auto_redeem.py` | Automatic position redemption after market resolution |

### AGI Lifecycle
| File | Description |
|------|-------------|
| `autonomous_promoter.py` | Experiment lifecycle daemon — DRAFT→SHADOW→PAPER→LIVE_PROMOTED→RETIRED |
| `agi_health_check.py` | Auto-kills strategies with <30% win rate after sufficient trades |
| `agi_orchestrator.py` | AGI orchestration — coordinates signal generation across strategies |
| `agi_goal_engine.py` | AGI goal tracking and objective management |
| `agi_promotion_pipeline.py` | Promotion gate evaluation logic |
| `agi_event_handlers.py` | AGI event handler callbacks |
| `agi_jobs.py` | AGI background job definitions |
| `agi_types.py` | AGI type definitions |
| `strategy_health.py` | `StrategyHealthMonitor` — computes win rate, Sharpe, drawdown, Brier, PSI |
| `strategy_rehabilitator.py` | Rehabilitation logic for killed strategies |
| `bankroll_allocator.py` | Daily capital allocator — computes per-strategy budgets via `StrategyRanker` |
| `strategy_ranker.py` | Ranks strategies by composite performance score |
| `strategy_performance_registry.py` | `StrategyPerformanceRegistry` singleton — per-strategy metrics updated after each settlement |

### Scheduling
| File | Description |
|------|-------------|
| `scheduler.py` | APScheduler instance and job registration; queue-worker mode keeps `settlement_check` scheduled directly until a periodic queue producer exists so live exposure can be released reliably |
| `scheduling_strategies.py` | All scheduled job implementations — `scan_and_trade_job`, `settlement_job`, `strategy_cycle_job`, etc.; DB sessions must stay short and never remain open across awaited network calls |
| `task_manager.py` | Async task lifecycle management |

### Infrastructure
| File | Description |
|------|-------------|
| `event_bus.py` | SSE broadcast and internal event dispatch — routes WebSocket strategy BUY decisions through `strategy_executor` with StrategyConfig mode semantics; background tasks must keep strong references and log callback failures |
| `mode_context.py` | Trading mode context (paper/live/shadow) |
| `shadow_mode.py` | Shadow mode execution — runs strategies without placing real orders |
| `shadow_validation.py` | Shadow mode trade validation |
| `distributed_lock.py` | Distributed lock for multi-process coordination |
| `redis_pubsub.py` | Redis pub/sub for cross-process event delivery |
| `retry.py` | Retry decorator with exponential backoff |
| `timeout_helpers.py` | Async timeout utilities |
| `errors.py` | Core exception types |
| `error_logger.py` | Structured error logging |

### Analytics & Learning
| File | Description |
|------|-------------|
| `trade_forensics.py` | Per-loss trade analysis — diagnoses root causes |
| `backtester.py` | Backtesting engine |
| `backtesting.py` | Backtesting utilities |
| `hft_backtester.py` | HFT-specific backtester |
| `online_learner.py` | Online learning from trade outcomes |
| `regime_detector.py` | Market regime detection (trending/ranging/volatile) |
| `regime_router.py` | Routes strategies based on detected regime |
| `calibration.py` | Probability calibration |
| `calibration_tracker.py` | Calibration metric tracking |
| `thompson_sampler.py` | Thompson sampling for strategy selection |
| `portfolio_optimizer.py` | Portfolio-level optimization |
| `bankroll_reconciliation.py` | Reconciles simulated vs actual bankroll |
| `equity_calculator.py` | Live equity calculation from CLOB + open positions |

## For AI Agents

### Critical Safety Rules
- **`botstate_mutex` is mandatory for BotState read-modify-write** — acquire it only around the short mutation section, and prefer a single atomic SQL `UPDATE` for counters/balances. Use `for_update()` only when code must inspect and mutate structured state in the same window. Preflight/risk reads should use plain reads so PM2 scheduler/API processes do not block trade execution on long `BotState` row locks. See `strategy_executor.py` and `settlement.py` for the pattern. Skipping atomic mutation or the mutation lock causes lost updates under concurrent execution.
- **Trade persistence must not share the same commit boundary as best-effort `BotState` follow-up sync** — if a `bot_state` row is lock-contended, the already-created `Trade`, `TradeAttempt`, and audit rows must stay durable. Persist the trade/attempt first, then run `BotState` counter updates in a short isolated follow-up transaction with bounded retries.
- **Heartbeat flushes must preserve `_pending_heartbeats` on DB failure** — only drop in-memory heartbeat entries after the `bot_state.misc_data` write succeeds, otherwise watchdog health can regress even while strategy activity continues.
- **`risk_manager.py`, `circuit_breaker.py`, and `settlement.py` must not be weakened without an ADR** — these are the last line of defense before real money moves. Any change that relaxes a limit, bypasses a check, or alters settlement logic requires a new ADR in `docs/architecture/`.
- **`settlement.py` is append-only for trade records** — never mutate historical `Trade` rows to explain rejected attempts. Use `TradeAttemptRecorder` instead (see `adr-003`).
- **Optional settlement hooks must be isolated** — learner/forensics/performance/brain integrations are best-effort and must never roll back the primary `Trade` + `SettlementEvent` writes.
- **`auto_trader.py` is an execution router, not a strategy** — trade attribution uses `Signal.track_name` to preserve the originating strategy name.

### BotState Pattern
```python
async with botstate_mutex:
    state = db.query(BotState).with_for_update().first()
    # ... read-modify-write ...
    db.commit()
```

### Session Lifetime Rule
- **Never hold a SQLAlchemy session open across awaited network I/O** — snapshot DB rows first, close/commit the session, then call external APIs. Re-open a fresh session only for the mutation/writeback step. This is especially important in scheduler jobs and data-feed discovery loops, otherwise PostgreSQL accumulates `idle in transaction` sessions and exhausts connection slots.
- This also applies to AGI/LLM flows and websocket broadcasts: prompt-building reads and API response reads must end their transaction before `await`ing Claude, backtests, or realtime fan-out.
- **External broker/network awaits in bot paths must be timeout-bounded** — wallet sync, auto-trader, and live strategy execution must wrap CLOB/API awaits with `asyncio.wait_for(...)` (or equivalent bounded helper) so PM2 can recover from true hangs instead of waiting forever.
- **Fire-and-forget asyncio work must be tracked** — background tasks in `event_bus.py` must be created via a helper that stores strong references, removes completed tasks, ignores normal cancellation, and logs real exceptions.

### Scheduler Job Registry
Jobs are registered in `scheduler.py` and implemented in `scheduling_strategies.py`:
- `scan_and_trade_job` — registry-driven signal scan + execution loop across enabled strategies
- `settlement_job` — resolves open positions
- `strategy_cycle_job` — per-strategy execution cycle
- `autonomous_promotion_job` — AGI experiment promotion (every 6h)
- `bankroll_allocation_job` — daily capital allocation
- `heartbeat_job` — system health heartbeat
- `market_universe_scan_job` — market discovery

### Testing Requirements
- Use in-memory SQLite and stub `apscheduler` (see `tests/conftest.py`)
- Risk manager tests: mock `BotState` and `Trade` queries
- Settlement tests: verify `botstate_mutex` is acquired

## Dependencies

### Internal
- `backend.config` — `settings`
- `backend.models.database` — ORM models, `botstate_mutex`, `for_update`
- `backend.db.utils` — `get_db_session`
- `backend.monitoring` — metrics emission

### External
- `apscheduler` — background job scheduling
- `sqlalchemy` — ORM queries
- `asyncio` — async execution
