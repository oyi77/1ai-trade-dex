# PolyEdge — Comprehensive Fix Plan for 32 Open Issues

## TL;DR

> **Quick Summary**: Fix 32 open issues covering 6 critical financial-loss bugs, 9 high operational risks, 7 medium quality gaps, and 10 research-driven enhancements across backend job queue, AI ensemble, strategies, WebSockets, frontend, monitoring, and documentation.
>
> **Deliverables**:
> - 5 critical fixes: job queue race + stale recovery, AI probability bounds, btc_oracle, online learner persistence, shadow experiment
> - 9 high fixes + 7 medium fixes covering strategy bugs, WebSocket stability, reconciliation, monitoring
> - 10 research-driven features: Polygon MEV, Kalshi batch ops, Platt scaling, LMSR, Kelly optimization, Becker dataset, ForecastBench, Gemini LLM, maker-edge
>
> **Estimated Effort**: Large (5 waves, ~15–25 days with parallel execution)
> **Parallel Execution**: YES — 5 waves with maximum parallelism per wave
> **Critical Path**: Wave 1 (foundation) → Wave 2 (concurrency/safety) → Wave 5 (research)

---

## Context

### Original Request
Create a comprehensive plan addressing all 32 open issues in oyi77/1ai-poly-trader. The repo has no prior open issues — these 32 were freshly created from a full codebase audit.

### Issue Summary
| Severity | Count | Issue Numbers |
|----------|-------|---------------|
| Critical | 6 | #37, #38, #39, #40, #41, #42 |
| High | 9 | #43, #44, #45, #46, #47, #48, #49, #50, #52 |
| Medium | 7 | #53, #54, #55, #57, #58, #59, #60 |
| Research | 10 | #61, #62, #63, #64, #65, #66, #67, #68, #69, #70 |

### Key Constraints
- Backward compatibility with existing paper/live trading
- RiskManager gates remain non-bypassable (ADR-004)
- StrategyConfig-driven config, .env feature flags
- Frontend polling uses POLL.* constants from polling.ts
- pytest for backend, vitest for frontend

---

## Work Objectives

### Core Objective
Fix all critical and high bugs, medium quality gaps, and implement research-driven improvements to make PolyEdge safe for real-money trading and expand its competitive edge.

### Concrete Deliverables
- Safe job queue with row-level locking and stale recovery
- Bounded AI probabilities preventing infinite Kelly fractions
- Functional online learning with weight persistence
- Working shadow experiments connected to real signal generation
- Multi-strategy concurrency safety (copy_trader, probability_arb, weather EMOS)
- Correct ensemble confidence scoring and debate engine failure handling
- Condition-based wallet reconciliation
- WebSocket reconnection with cache invalidation
- Grafana dashboards with instrumented Prometheus metrics
- Lazy-loaded GlobeView with fallback skeleton
- Production runbook (deployment, rollback, incidents)
- Polygon Private Mempool MEV protection
- Kalshi BatchCreateOrders, AmendOrder, and BatchCancelOrders
- Platt scaling + extremization + LMSR spread + Kelly optimization
- Becker dataset integration, ForecastBench benchmarking, Gemini provider

### Definition of Done
- [ ] All 6 critical issues fixed, verified, and PR merged (Closes #39, #40, #41, #42, #37, #38)
- [ ] All 9 high issues fixed, verified, and PR merged (Closes #43, #44, #45, #46, #47, #48, #49, #50, #52)
- [ ] All 7 medium issues addressed, verified, and PR merged (Closes #53, #54, #55, #57, #58, #59, #60)
- [ ] 10 research enhancements implemented and PR merged (Closes #61-#70)
- [ ] `pytest` passes from project root
- [ ] `cd frontend && npm run build` succeeds
- [ ] Zero new `except Exception` blocks
- [ ] IMPLEMENTATION_GAPS.md updated
- [ ] All 32 issues auto-closed by GitHub on PR merge

### Must Have
- Job queue race fix (money at risk)
- AI probability clamping (prevents infinite Kelly)
- Strategy concurrency safety (copy_trader, probability_arb)
- Online learner persistence (AI learning functional)
- WebSocket stale data fix (signal quality)

### Must NOT Have
- Changes to RiskManager enforcement (ADR-004)
- Deletion of strategy code without registry update
- Breaking changes to StrategyConfig schema without migration
- New bare `except Exception` blocks
- Production credential changes without migration plan

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: Tests-After (unit/integration tests added with each fix)
- **Framework**: pytest (backend) + vitest (frontend)
- **Agent-Executed QA**: ALWAYS — every task includes Playwright/curl/tmux verification scenarios

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Frontend/UI**: Use Playwright (playwright skill) — Navigate, interact, assert DOM, screenshot
- **API/Backend**: Use Bash (curl) — Send requests, assert status + response fields
- **Library/Module**: Use Bash (bun/python REPL) — Import, call functions, compare output

---

## Execution Strategy

### Parallel Execution Waves

> Maximize throughput by grouping independent tasks into parallel waves.
> Each wave completes before the next begins.
> Target: 5-8 tasks per wave.

```
Wave 1 (Start Immediately — foundation + quick wins):
├── T1: AI probability clamping utility + apply to all AI modules [#39]
├── T2: BTC Oracle probability fix + base strategy enabled check [#40]
├── T3: Online learner weight persistence [#41]
├── T4: Registry performance gate (MIN_WIN_RATE/MIN_ROI) [#43]
├── T5: General scanner early enabled check [#54]
├── T6: Market maker inventory validation [#55]
├── T7: Debate engine asyncio.gather() parallelization [#53]
└── T8: Debate engine zero-information signal filter [#48]

Wave 2 (After Wave 1 — concurrency/safety fixes, MAX PARALLEL):
├── T9: SQLite job queue .with_for_update() + integration test [#37]
├── T10: Stale job reclaim_stale_jobs() + dead-letter queue [#38]
├── T11: Copy trader asyncio.Lock for _tracked mutations [#44]
├── T12: Probability arb semaphore try/finally fix + Kelly sizing [#45]
├── T13: Weather EMOS CalibrationState persistence [#46]
├── T14: WebSocket cache clearing on reconnect + staleness check [#52]
└── T15: Polygon listener exponential backoff + alerting [#57]

Wave 3 (After Wave 2 — data integrity + schema fixes, MAX PARALLEL):
├── T16: Ensemble confidence agreement metric + unit tests [#47]
├── T17: Wallet reconciliation condition_id matching + orphan logging [#49]
├── T18: Proposal column name validation + schema fix [#50]
├── T19: Shadow experiment dry-run connection + real signal capture [#42]
└── T20: Frontend GlobeView React.lazy() + Suspense skeleton [#59]

Wave 4 (After Wave 3 — infrastructure + monitoring, MAX PARALLEL):
├── T21: Grafana dashboard JSON (P&L, breakers, latency, health) [#58]
├── T22: Prometheus metrics instrumentation (12 blind spots) [#58]
├── T23: Production runbook (deployment, rollback, incidents) [#60]
└── T24: Polygon Private Mempool integration [#61]

Wave 5 (After Wave 4 — research features, MAX PARALLEL):
├── T25: Kalshi BatchCreateOrders + AmendOrder + BatchCancelOrders [#62]
├── T26: Platt scaling + extremization in AI ensemble [#63]
├── T27: LMSR-based spread calculation for market maker [#64]
├── T28: Kelly fraction optimization script [#65]
├── T29: Resolution source validation for cross-platform arb [#66]
├── T30: Becker dataset Parquet integration [#67]
├── T31: ForecastBench ensemble benchmarking [#68]
├── T32: GeminiProvider for 5-forecaster ensemble [#69]
└── T33: Maker-edge optimization (optimism tax spread widening) [#70]

Wave FINAL (After ALL tasks — 4 parallel reviews, then user okay):
├── TF1: Plan compliance audit (oracle)
├── TF2: Code quality review (unspecified-high)
├── TF3: Real manual QA (unspecified-high)
└── TF4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay

Critical Path: T1 → T9 → T16 → T21 → T25 → TF1-F4 → user okay
Parallel Speedup: ~65% faster than sequential
Max Concurrent: 9 (Wave 5)
```

---

## TODOs

---

- [x] 1. AI Probability Clamping Utility + Apply to All AI Modules [#39]

  **What to do**:
  - Create `backend/ai/probability_utils.py` with `clamp_probability(p: float, epsilon: float = 0.01) -> float`
  - Clamp to `[epsilon, 1.0 - epsilon]`, log warning when out-of-bounds input detected
  - Apply clamping at output boundaries of:
    - `backend/ai/ensemble.py` — after multi-provider aggregation
    - `backend/ai/prediction_engine.py` — after model.predict()
    - `backend/ai/narrative_engine.py` — after narrative-based probability estimation
    - `backend/ai/debate_engine.py` — after debate resolution
  - Add unit test: `test_probability_utils.py` with inputs (0.0, 1.0, -0.5, 1.5, 0.5, 0.99)

  **Must NOT do**:
  - Don't clamp in signal_parser.py (already has range check — align, don't duplicate)
  - Don't change edge calculation logic, only clamp final probability

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Simple utility + mechanical wiring across 4 files
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T2-T8)
  - **Blocks**: T16 (ensemble confidence depends on clean probabilities)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `backend/ai/ensemble.py:85-94` — current probability aggregation, insert clamp after
  - `backend/ai/prediction_engine.py:65-67` — model.predict() output, clamp result
  - `backend/ai/narrative_engine.py` — narrative probability generation, clamp output
  - `backend/ai/debate_engine.py:359` — debate result probability, clamp result
  - `backend/strategies/btc_oracle.py:308` — currently hardcoded 1.0/0.0, will be fixed in T2

  **Acceptance Criteria**:
  - [ ] `backend/ai/probability_utils.py` exists with clamp_probability()
  - [ ] All 4 AI output modules call clamp_probability() before returning probability
  - [ ] `pytest backend/tests/test_probability_utils.py` → PASS (5+ test cases)

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Probability clamping prevents extreme values
    Tool: Bash (pytest)
    Steps:
      1. python -c "from backend.ai.probability_utils import clamp_probability; assert clamp_probability(0.0) == 0.01; assert clamp_probability(1.0) == 0.99; assert clamp_probability(-0.5) == 0.01; assert clamp_probability(1.5) == 0.99; assert clamp_probability(0.6) == 0.6"
      2. pytest backend/tests/test_probability_utils.py -v
    Expected Result: All assertions pass, pytest shows 5+ passed
    Evidence: .sisyphus/evidence/task-1-probability-clamp.txt
  ```

  **Commit**: YES
  - Message: `fix(ai): add probability clamping utility to prevent infinite Kelly`
  - Files: `backend/ai/probability_utils.py` (new), `backend/ai/ensemble.py`, `backend/ai/prediction_engine.py`, `backend/ai/narrative_engine.py`, `backend/ai/debate_engine.py`, `backend/tests/test_probability_utils.py` (new)

---

- [x] 2. BTC Oracle Edge-Based Probability + Base Strategy Enabled Check [#40]

  **What to do**:
  - In `backend/strategies/btc_oracle.py:308`: Replace `oracle_implied = 1.0 if direction == "yes" else 0.0` with `oracle_implied = clamp_probability(0.5 + edge * confidence_scalar)` where edge derives from latency arb math
  - In `backend/strategies/btc_oracle.py:312`: Compute confidence as `min(1.0, abs(edge) * 10.0)` not `min(1.0, edge + min_edge)`
  - In `backend/strategies/base.py`: Add `if not getattr(self.config, 'enabled', True): return []` at top of run_cycle()
  - Verify: disabled strategy produces zero signals after fix

  **Must NOT do**:
  - Don't remove btc_oracle from registry — fix it, don't delete it
  - Don't change the latency arb math, only the probability output

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Two-line code change + base class guard
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1, T3-T8)
  - **Blocks**: None
  - **Blocked By**: T1 (needs clamp_probability utility)

  **References**:
  - `backend/strategies/btc_oracle.py:300-315` — current run_cycle() implementation
  - `backend/ai/probability_utils.py` — clamp_probability from T1
  - `backend/strategies/base.py:150-180` — BaseStrategy.run_cycle() pattern

  **Acceptance Criteria**:
  - [ ] btc_oracle outputs probabilities in (0.01, 0.99) range
  - [ ] Disabled strategy produces empty signal list
  - [ ] `pytest backend/tests/test_btc_oracle.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: BTC oracle produces bounded probabilities
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_btc_oracle.py -v -k "test_probability_bounds"
    Expected Result: All oracle probabilities in [0.01, 0.99]
    Evidence: .sisyphus/evidence/task-2-btc-oracle.txt

  Scenario: Disabled strategy returns no signals
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_btc_oracle.py -v -k "test_disabled_returns_empty"
    Expected Result: run_cycle() returns [] when enabled=False
    Evidence: .sisyphus/evidence/task-2-disabled-strategy.txt
  ```

  **Commit**: YES
  - Message: `fix(strategies): btc_oracle edge-based probability + disabled strategy guard`
  - Files: `backend/strategies/btc_oracle.py`, `backend/strategies/base.py`, `backend/tests/test_btc_oracle.py`

---

- [x] 3. Online Learner Weight Persistence [#41]

  **What to do**:
  - In `backend/core/online_learner.py`: After computing weight delta in learning loop
  - Read current `StrategyConfig.params` (JSON column), parse as dict
  - Update with new weights: `params["learned_weights"] = new_weights`, `params["last_learning_ts"] = datetime.utcnow().isoformat()`
  - Write via `db.commit()` using existing session
  - Add `logger.info("Updated strategy %s weights: %s", strategy_name, weight_summary)`
  - Add `test_online_learner_persistence.py`:
    - Create strategy with mock params
    - Run learning cycle
    - Assert params updated with new weights
    - Restart (re-initialize learner from DB), assert weights preserved

  **Must NOT do**:
  - Don't change the learning algorithm, only add persistence layer
  - Don't create new DB table — use existing StrategyConfig.params JSON column

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Adding persistence writeback to existing learning loop
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1-T2, T4-T8)
  - **Blocks**: None
  - **Blocked By**: None (can start immediately)

  **References**:
  - `backend/core/online_learner.py` — current learning loop, need to locate weight update point
  - `backend/models/database.py` — StrategyConfig model with params JSON column
  - `backend/core/strategy_performance_registry.py` — example of reading/writing StrategyConfig

  **Acceptance Criteria**:
  - [ ] Weights persisted to StrategyConfig.params after learning cycle
  - [ ] Weights survived across restarts
  - [ ] `pytest backend/tests/test_online_learner_persistence.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Learning weights persist across cycles
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_online_learner_persistence.py -v
    Expected Result: Weights persist in DB, load correctly on re-init
    Evidence: .sisyphus/evidence/task-3-learner-persistence.txt
  ```

  **Commit**: YES
  - Message: `fix(ai): online learner weight persistence to StrategyConfig.params`
  - Files: `backend/core/online_learner.py`, `backend/tests/test_online_learner_persistence.py` (new)

---

- [x] 4. Registry Performance Gate (MIN_WIN_RATE/MIN_ROI) [#43]

  **What to do**:
  - In `backend/strategies/registry.py:54-65`, add to `create_strategy()`:
    ```python
    MIN_WIN_RATE = 0.30  # configurable via settings
    MIN_ROI = -0.30       # configurable via settings
    ```
  - Check strategy's documented performance (from docstring or metadata):
    - If `win_rate < MIN_WIN_RATE` or `roi < MIN_ROI`: set `enabled=False` with `logger.warning()`
  - Add `force_enable=False` param to create_strategy() for manual override
  - Apply to btc_momentum.py: update docstring metadata with structured performance data
  - Add config fields: `REGISTRY_MIN_WIN_RATE`, `REGISTRY_MIN_ROI`

  **Must NOT do**:
  - Don't remove strategies from registry — auto-disable them
  - Don't hardcode thresholds — use config

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Adding a guard condition to existing factory method
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1-T3, T5-T8)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `backend/strategies/registry.py:54-65` — create_strategy() method
  - `backend/config.py` — add new config fields
  - `backend/strategies/btc_momentum.py:4-5` — documented -49.5% ROI

  **Acceptance Criteria**:
  - [ ] btc_momentum auto-disabled on registration
  - [ ] `backend/tests/test_registry_gate.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Negative-EV strategy auto-disabled
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_registry_gate.py -v
    Expected Result: Strategy with ROI < -0.30 auto-disabled
    Evidence: .sisyphus/evidence/task-4-registry-gate.txt
  ```

  **Commit**: YES
  - Message: `feat(strategies): performance gate in registry to auto-disable negative-EV strategies`
  - Files: `backend/strategies/registry.py`, `backend/config.py`, `backend/tests/test_registry_gate.py` (new)

---

- [x] 5. General Scanner Early Enabled Check [#54]

  **What to do**:
  - In `backend/strategies/general_market_scanner.py`:
  - Move `if not self.client or not self.client.is_enabled:` check to FIRST line of `run_cycle()`
  - Currently at line 266-271, AFTER market fetching and API calls
  - Also add strategy-level check: `if not self.config.enabled: return []`
  - Verify: when AI disabled, no API calls made (check via mock/spy in test)

  **Must NOT do**:
  - Don't change the scanning logic, only reorder the guard

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Moving an existing check to earlier position
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1-T4, T6-T8)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `backend/strategies/general_market_scanner.py:22` — current signal generation (before check)
  - `backend/strategies/general_market_scanner.py:266-271` — current check position

  **Acceptance Criteria**:
  - [ ] No API calls when AI disabled
  - [ ] `pytest backend/tests/test_general_scanner.py -v -k "test_disabled_skips_api"` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Disabled scanner makes zero API calls
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_general_scanner.py -v -k "test_disabled_skips_api"
    Expected Result: 0 API calls when client.is_enabled=False
    Evidence: .sisyphus/evidence/task-5-scanner-early-check.txt
  ```

  **Commit**: YES
  - Message: `fix(strategies): general scanner checks AI enabled before API calls`
  - Files: `backend/strategies/general_market_scanner.py`

---

- [x] 6. Market Maker Inventory Validation [#55]

  **What to do**:
  - In `backend/strategies/market_maker.py:45-85`, add validation at top of `calculate_spread()`:
    ```python
    inventory_pct = max(0.0, min(1.0, inventory_pct))
    if quote_size <= 0:
        return {"error": "Invalid quote_size", "spread": None}
    ```
  - After computing spread: `if spread <= 0: logger.warning(...); return {"spread": None}`
  - Add unit tests: `test_market_maker_validation.py`:
    - inventory_pct=1.5 → clamped to 1.0
    - inventory_pct=-0.5 → clamped to 0.0
    - quote_size=0 → returns error
    - Valid inputs → normal spread output

  **Must NOT do**:
  - Don't change spread calculation formula — only validate inputs/outputs

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Input validation + unit tests
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1-T5, T7-T8)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `backend/strategies/market_maker.py:45-85` — calculate_spread() method

  **Acceptance Criteria**:
  - [ ] Invalid inputs produce safe outputs (no negative spreads)
  - [ ] `pytest backend/tests/test_market_maker_validation.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Inventory validation prevents negative spreads
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_market_maker_validation.py -v
    Expected Result: Clamped inventory, zero-size error, spread > 0
    Evidence: .sisyphus/evidence/task-6-market-maker.txt
  ```

  **Commit**: YES
  - Message: `fix(strategies): market maker inventory validation prevents negative spreads`
  - Files: `backend/strategies/market_maker.py`, `backend/tests/test_market_maker_validation.py` (new)

---

- [x] 7. Debate Engine asyncio.gather() Parallelization [#53]

  **What to do**:
  - In `backend/ai/debate_engine.py:464-469`:
  - Replace sequential calls:
    ```python
    # BEFORE:
    bull_opening = await self._generate_bull_opening(...)
    bear_opening = await self._generate_bear_opening(...)
    
    # AFTER:
    bull_opening, bear_opening = await asyncio.gather(
        self._generate_bull_opening(...),
        self._generate_bear_opening(...)
    )
    ```
  - Verify both calls are truly independent (no shared mutable state)
  - Add timing assertion test: parallel version completes faster than sequential

  **Must NOT do**:
  - Don't change the prompt content, only the execution pattern

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Simple asyncio.gather refactor
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1-T6, T8)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `backend/ai/debate_engine.py:464-469` — sequential bull/bear opening generation

  **Acceptance Criteria**:
  - [ ] Bull and bear arguments generated in parallel
  - [ ] `pytest backend/tests/test_debate_engine.py -v -k "test_parallel"` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Parallel debate is faster than sequential
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_debate_engine.py -v -k "test_parallel_debate"
    Expected Result: Parallel version completes faster, no errors
    Evidence: .sisyphus/evidence/task-7-debate-parallel.txt
  ```

  **Commit**: YES
  - Message: `perf(ai): parallelize debate engine bull/bear arguments with asyncio.gather`
  - Files: `backend/ai/debate_engine.py`

---

- [x] 8. Debate Engine Zero-Information Signal Filter [#48]

  **What to do**:
  - In `backend/ai/debate_engine.py:359`:
  - Change `return {"probability": 0.5, "confidence": 0.0}` to `return None`
  - In caller(s) of `run_debate()`: add `if result is None: continue` or skip
  - Add logging: `logger.warning("Debate engine returned None, skipping signal")`
  - Add unit test: assert `run_debate()` returns None on failure, caller handles None gracefully

  **Must NOT do**:
  - Don't change debate logic — only replace failure return with None

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Return None instead of garbage default signal
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1-T7)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `backend/ai/debate_engine.py:359` — current failure return
  - `backend/core/strategy_executor.py` or wherever debate results are consumed

  **Acceptance Criteria**:
  - [ ] Failed debate returns None (not garbage signal)
  - [ ] Callers handle None without crashing
  - [ ] `pytest backend/tests/test_debate_engine.py -v -k "test_failure_returns_none"` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Failed debate produces no signal
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_debate_engine.py -v -k "test_failure_returns_none"
    Expected Result: run_debate() returns None, caller skips signal generation
    Evidence: .sisyphus/evidence/task-8-debate-null.txt
  ```

  **Commit**: YES
  - Message: `fix(ai): debate engine returns None on failure instead of zero-information signal`
  - Files: `backend/ai/debate_engine.py`

---

- [x] 9. SQLite Job Queue Row-Level Locking + Integration Test [#37]

  **What to do**:
  - In `backend/job_queue/sqlite_queue.py:158-164`:
  - Change dequeue query from `.first()` to `.with_for_update().first()`
  - If SQLite doesn't support `.with_for_update()`, implement advisory lock pattern:
    ```python
    # Atomic compare-and-swap on status column
    updated = db.query(JobQueueItem).filter(
        JobQueueItem.id == job.id,
        JobQueueItem.status == "pending"
    ).update({"status": "processing"}, synchronize_session=False)
    if updated == 0:
        continue  # Another worker claimed this job
    ```
  - Add integration test: `test_sqlite_queue_concurrency.py`
    - Launch 2 concurrent workers
    - Enqueue 100 jobs
    - Assert exactly 100 jobs processed (zero duplicates)
    - Assert no job processed twice

  **Must NOT do**:
  - Don't change queue interface — internal implementation only
  - Don't break Redis queue path

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Concurrency fix with subtle SQLite semantics, needs careful testing
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with T10-T15)
  - **Blocks**: None
  - **Blocked By**: Wave 1 (T1-T8 must complete first — foundation)

  **References**:
  - `backend/job_queue/sqlite_queue.py:120-170` — enqueue/dequeue methods
  - `backend/job_queue/worker.py:186-219` — worker dispatch loop
  - `backend/models/database.py` — JobQueueItem model

  **Acceptance Criteria**:
  - [ ] Zero duplicate job execution under concurrency
  - [ ] `pytest backend/tests/test_sqlite_queue_concurrency.py` → PASS
  - [ ] Existing queue tests still pass

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Concurrent workers don't duplicate jobs
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_sqlite_queue_concurrency.py -v
    Expected Result: 100 jobs enqueued, 100 unique jobs processed, 0 duplicates
    Evidence: .sisyphus/evidence/task-9-queue-concurrency.txt
  ```

  **Commit**: YES
  - Message: `fix(queue): SQLite job queue row-level locking prevents duplicate execution`
  - Files: `backend/job_queue/sqlite_queue.py`, `backend/tests/test_sqlite_queue_concurrency.py` (new)

---

- [x] 10. Stale Job Recovery + Dead-Letter Queue [#38]

  **What to do**:
  - In `backend/job_queue/sqlite_queue.py`:
  - Add `reclaim_stale_jobs(self, max_age_minutes=10, max_reclaims=3)` method:
    ```python
    stale = db.query(JobQueueItem).filter(
        JobQueueItem.status == "processing",
        JobQueueItem.updated_at < datetime.utcnow() - timedelta(minutes=max_age_minutes)
    ).all()
    for job in stale:
        job.reclaim_count = (job.reclaim_count or 0) + 1
        if job.reclaim_count > max_reclaims:
            job.status = "dead_letter"
            logger.error("Job %s moved to dead-letter after %d reclaims", job.id, max_reclaims)
        else:
            job.status = "pending"
    db.commit()
    ```
  - Add `reclaim_count` column to JobQueueItem model (default 0, nullable)
  - Call `reclaim_stale_jobs()` on startup and every 5 minutes via scheduler
  - In `backend/core/scheduler.py:700-703`: add explicit error logging, don't silently catch
  - Add `test_stale_job_recovery.py`: simulate crash, verify jobs reclaimed

  **Must NOT do**:
  - Don't remove existing startup reload — augment it

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: DB model change + recovery logic + scheduler integration
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with T9, T11-T15)
  - **Blocks**: None
  - **Blocked By**: Wave 1

  **References**:
  - `backend/job_queue/sqlite_queue.py:171` — current lack of reclaim
  - `backend/core/scheduler.py:700-703` — startup reload
  - `backend/models/database.py` — JobQueueItem model (add reclaim_count)

  **Acceptance Criteria**:
  - [ ] Stale jobs reclaimed within 5 minutes
  - [ ] Jobs exceeding 3 reclaims moved to dead-letter
  - [ ] `pytest backend/tests/test_stale_job_recovery.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Crashed worker's jobs are recovered
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_stale_job_recovery.py -v
    Expected Result: Stale processing jobs reset to pending, 3+ reclaims → dead-letter
    Evidence: .sisyphus/evidence/task-10-stale-recovery.txt
  ```

  **Commit**: YES
  - Message: `fix(queue): stale job recovery prevents permanent job loss after crashes`
  - Files: `backend/job_queue/sqlite_queue.py`, `backend/models/database.py`, `backend/core/scheduler.py`, `backend/tests/test_stale_job_recovery.py` (new)

---

- [x] 11. Copy Trader asyncio.Lock for Position Tracking [#44]

  **What to do**:
  - In `backend/modules/execution/copy_trader.py`:
  - Add `self._track_lock = asyncio.Lock()` in `__init__()`
  - Wrap all `_tracked` mutations:
    ```python
    async with self._track_lock:
        self._tracked.append(new_position)
    ```
  - Affected locations: lines 75-96 (position tracking), 200-240 (leaderboard refresh)
  - Add `test_copy_trader_concurrency.py`: simulate concurrent run_cycle, assert no corruption

  **Must NOT do**:
  - Don't change position tracking logic, only add lock

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Adding asyncio.Lock to existing mutation points
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with T9-T10, T12-T15)
  - **Blocks**: None
  - **Blocked By**: Wave 1

  **References**:
  - `backend/modules/execution/copy_trader.py:75-96` — _tracked append/remove
  - `backend/modules/execution/copy_trader.py:200-240` — leaderboard refresh

  **Acceptance Criteria**:
  - [ ] No data corruption under concurrent execution
  - [ ] `pytest backend/tests/test_copy_trader_concurrency.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Concurrent copy trader runs don't corrupt positions
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_copy_trader_concurrency.py -v
    Expected Result: Position list consistent after concurrent access
    Evidence: .sisyphus/evidence/task-11-copy-trader-lock.txt
  ```

  **Commit**: YES
  - Message: `fix(strategies): copy trader asyncio.Lock for concurrent position tracking`
  - Files: `backend/modules/execution/copy_trader.py`, `backend/tests/test_copy_trader_concurrency.py` (new)

---

- [x] 12. Probability Arb Semaphore Fix + Kelly Sizing [#45]

  **What to do**:
  - In `backend/strategies/probability_arb.py:23,95`:
  - Wrap semaphore-acquired section in `try/finally`:
    ```python
    await self._exec_semaphore.acquire()
    try:
        # ... arb execution logic ...
    finally:
        self._exec_semaphore.release()
    ```
  - Replace hardcoded sizes at lines 101, 110 with `self.risk_manager.validate_trade(strategy_name=..., proposed_size=..., ...)`
  - Add `test_probability_arb_semaphore.py`: inject exception, verify semaphore released

  **Must NOT do**:
  - Don't change arb detection logic

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: try/finally fix + replace hardcoded values
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with T9-T11, T13-T15)
  - **Blocks**: None
  - **Blocked By**: Wave 1

  **References**:
  - `backend/strategies/probability_arb.py:23` — semaphore definition
  - `backend/strategies/probability_arb.py:95,101,110` — acquire + hardcoded sizes
  - `backend/core/risk_manager.py` — validate_trade() for Kelly sizing

  **Acceptance Criteria**:
  - [ ] Semaphore released even after exception
  - [ ] Sizes use Kelly calculation, not magic numbers
  - [ ] `pytest backend/tests/test_probability_arb_semaphore.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Semaphore released after exception
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_probability_arb_semaphore.py -v
    Expected Result: Exception path releases semaphore, subsequent runs succeed
    Evidence: .sisyphus/evidence/task-12-prob-arb-semaphore.txt
  ```

  **Commit**: YES
  - Message: `fix(strategies): probability arb semaphore try/finally + Kelly sizing`
  - Files: `backend/strategies/probability_arb.py`, `backend/tests/test_probability_arb_semaphore.py` (new)

---

- [x] 13. Weather EMOS CalibrationState Persistence [#46]

  **What to do**:
  - In `backend/modules/scanners/weather_emos.py:77-98`:
  - Replace in-memory `CalibrationState` dict with JSON persistence:
    ```python
    def _load_calibration(self):
        params = json.loads(self.config.params or "{}")
        if "calibration_state" in params:
            return CalibrationState(**params["calibration_state"])
        return CalibrationState()
    
    def _save_calibration(self, state: CalibrationState):
        params = json.loads(self.config.params or "{}")
        params["calibration_state"] = asdict(state)
        self.config.params = json.dumps(params)
        db.commit()
    ```
  - Load on init, save after each observation
  - Add `test_weather_emos_persistence.py`: simulate restart, verify state preserved
  - Add `logger.info` on calibration state save/load

  **Must NOT do**:
  - Don't change EMOS algorithm, only add persistence layer

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Adding persistence layer to existing calibration code
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with T9-T12, T14-T15)
  - **Blocks**: None
  - **Blocked By**: Wave 1

  **References**:
  - `backend/modules/scanners/weather_emos.py:77-98` — CalibrationState class and usage
  - `backend/models/database.py` — StrategyConfig.params JSON column
  - `backend/core/online_learner.py` — same pattern (T3) for reference

  **Acceptance Criteria**:
  - [ ] Calibration survives bot restart
  - [ ] `pytest backend/tests/test_weather_emos_persistence.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Weather calibration survives restart
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_weather_emos_persistence.py -v
    Expected Result: After simulated restart, calibration state matches pre-restart
    Evidence: .sisyphus/evidence/task-13-weather-emos.txt
  ```

  **Commit**: YES
  - Message: `fix(strategies): weather EMOS calibration state persisted to StrategyConfig`
  - Files: `backend/modules/scanners/weather_emos.py`, `backend/tests/test_weather_emos_persistence.py` (new)

---

- [x] 14. WebSocket Cache Clearing on Reconnect + Staleness Check [#52]

  **What to do**:
  - In `backend/data/orderbook_ws.py` and `backend/data/polymarket_websocket.py`:
  - Add `on_reconnect_callback` that:
    ```python
    async def _on_reconnect(self):
        logger.warning("WebSocket reconnected, clearing stale caches")
        self._orderbook_cache.clear()
        await self._subscribe_all()  # Re-subscribe to active markets
    ```
  - Add staleness check before serving cached data:
    ```python
    if (now - cached_entry.timestamp).total_seconds() > 30:
        logger.warning("Stale cache entry for %s, skipping", market_id)
        continue  # Don't serve stale data
    ```
  - Add `test_ws_staleness.py`: simulate disconnect + reconnect, verify cache empty

  **Must NOT do**:
  - Don't change WebSocket connection logic, only add reconnect handler

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: WebSocket lifecycle changes across 2 modules
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with T9-T13, T15)
  - **Blocks**: None
  - **Blocked By**: Wave 1

  **References**:
  - `backend/data/orderbook_ws.py` — orderbook WebSocket client
  - `backend/data/polymarket_websocket.py` — market data WebSocket client
  - Both have existing connect/disconnect handlers — augment, don't replace

  **Acceptance Criteria**:
  - [ ] Cache cleared after reconnect
  - [ ] Data older than 30s rejected
  - [ ] `pytest backend/tests/test_ws_staleness.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Reconnected WebSocket has fresh cache
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_ws_staleness.py -v
    Expected Result: Empty cache after reconnect, data < 30s accepted
    Evidence: .sisyphus/evidence/task-14-ws-staleness.txt
  ```

  **Commit**: YES
  - Message: `fix(data): WebSocket cache clearing on reconnect + staleness validation`
  - Files: `backend/data/orderbook_ws.py`, `backend/data/polymarket_websocket.py`, `backend/tests/test_ws_staleness.py` (new)

---

- [x] 15. Polygon Listener Exponential Backoff + Alerting [#57]

  **What to do**:
  - In `backend/data/polygon_listener.py`:
  - Replace `for retry in range(5): ...` with:
    ```python
    delays = [1, 2, 4, 8, 16, 30, 60]  # Cap at 60s
    for attempt, delay in enumerate(delays):
        try:
            await self._connect()
            break
        except Exception as e:
            logger.warning("Polygon listener retry %d/%d in %ds: %s", attempt+1, len(delays), delay, e)
            if attempt == len(delays) - 1:
                logger.error("Polygon listener permanently failed after %d retries", len(delays))
                await self._send_alert("Polygon listener permanently disconnected")
            await asyncio.sleep(delay)
    ```
  - Add `_send_alert()` using existing notification system (Telegram/Discord)
  - Add `circuit_breaker` integration — after circuit opens, re-enable on timer

  **Must NOT do**:
  - Don't remove retry logic, enhance it

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Exponential backoff + circuit breaker + notification integration
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with T9-T14)
  - **Blocks**: None
  - **Blocked By**: Wave 1

  **References**:
  - `backend/data/polygon_listener.py` — current retry loop
  - `backend/core/circuit_breaker.py` — existing breaker infrastructure
  - `backend/bot/notification_router.py` — existing notification channels

  **Acceptance Criteria**:
  - [ ] Exponential backoff with 60s cap
  - [ ] Alert sent on permanent failure
  - [ ] `pytest backend/tests/test_polygon_listener.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Polygon listener backoff and alert
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_polygon_listener.py -v
    Expected Result: Exponential delays, alert on final failure, circuit re-enables
    Evidence: .sisyphus/evidence/task-15-polygon-listener.txt
  ```

  **Commit**: YES
  - Message: `fix(data): polygon listener exponential backoff, circuit breaker, alerting`
  - Files: `backend/data/polygon_listener.py`, `backend/tests/test_polygon_listener.py`

---

- [x] 16. Ensemble Confidence Agreement Metric + Unit Tests [#47]

  **What to do**:
  - In `backend/ai/ensemble.py:85-94`:
  - Replace `avg_confidence = sum(active_confidences) / len(active_confidences)` with:
    ```python
    if len(probabilities) < 2:
        confidence = probabilities[0] if probabilities else 0.0
    else:
        std = float(np.std(probabilities))
        confidence = 1.0 - (std / 0.5)  # Normalized inverse variance
        confidence = max(0.0, min(1.0, confidence))
    ```
  - Add unit tests in `test_ensemble_confidence.py`:
    - All agree (0.7, 0.7, 0.7) → confidence ≈ 1.0
    - Split (0.3, 0.7) → confidence ≈ 0.2
    - Single provider → confidence = probability
    - Extreme disagreement (0.01, 0.99) → confidence ≈ 0.0

  **Must NOT do**:
  - Don't change the weighted-average probability computation, only confidence

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Statistical formula change with edge case testing
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with T17-T20)
  - **Blocks**: None
  - **Blocked By**: Wave 1 (T1 probability clamping)

  **References**:
  - `backend/ai/ensemble.py:85-94` — current confidence computation
  - Gneiting & Raftery (2007) — Brier score and proper scoring rules

  **Acceptance Criteria**:
  - [ ] High agreement → high confidence (>0.8)
  - [ ] Low agreement → low confidence (<0.3)
  - [ ] `pytest backend/tests/test_ensemble_confidence.py -v` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Agreement produces high confidence
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_ensemble_confidence.py -v -k "test_agreement"
    Expected Result: 0.7/0.7/0.7 → confidence > 0.8
    Evidence: .sisyphus/evidence/task-16-ensemble-conf.txt

  Scenario: Disagreement produces low confidence
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_ensemble_confidence.py -v -k "test_disagreement"
    Expected Result: 0.3/0.7 → confidence < 0.3
    Evidence: .sisyphus/evidence/task-16-ensemble-disagree.txt
  ```

  **Commit**: YES
  - Message: `fix(ai): ensemble confidence uses agreement metric not probability average`
  - Files: `backend/ai/ensemble.py`, `backend/tests/test_ensemble_confidence.py` (new)

---

- [x] 17. Wallet Reconciliation condition_id Matching + Orphan Logging [#49]

  **What to do**:
  - In `backend/core/wallet_reconciliation.py:346-360`:
  - Add `condition_id`-based primary matching BEFORE fuzzy string matching:
    ```python
    # Primary: match by condition_id
    trade = db.query(Trade).filter(Trade.condition_id == activity.condition_id).first()
    if trade:
        return trade
    
    # Fallback: fuzzy match on slug/title (existing logic)
    ...
    ```
  - After all matching, log unmatched REDEEM records:
    ```python
    if not matched:
        logger.warning("Orphaned REDEEM: id=%s, amount=%s, slug=%s", 
                       activity.id, activity.amount, activity.slug[:60])
    ```
  - Add `test_wallet_reconciliation_matching.py`: test condition_id match, fuzzy fallback, orphan logging

  **Must NOT do**:
  - Don't remove fuzzy matching — it's the fallback
  - Don't auto-create trades for orphans — log them

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Two-tier matching logic with reconciliation safety
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with T16, T18-T20)
  - **Blocks**: None
  - **Blocked By**: Wave 1

  **References**:
  - `backend/core/wallet_reconciliation.py:346-360` — current fuzzy matching
  - `backend/models/database.py` — Trade model with condition_id column
  - `backend/strategies/wallet_sync.py` — REDEEM activity schema

  **Acceptance Criteria**:
  - [ ] condition_id matching works for exact matches
  - [ ] Fuzzy fallback still works for partial matches
  - [ ] Orphans logged (not silently dropped)
  - [ ] `pytest backend/tests/test_wallet_reconciliation_matching.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Wallet reconciliation matches by condition_id
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_wallet_reconciliation_matching.py -v
    Expected Result: condition_id match succeeds, fuzzy fallback, orphans logged
    Evidence: .sisyphus/evidence/task-17-wallet-recon.txt
  ```

  **Commit**: YES
  - Message: `fix(core): wallet reconciliation uses condition_id primary matching, logs orphans`
  - Files: `backend/core/wallet_reconciliation.py`, `backend/tests/test_wallet_reconciliation_matching.py` (new)

---

- [x] 18. Proposal Column Name Validation + Schema Fix [#50]

  **What to do**:
  - In `backend/models/database.py`:
  - Verify StrategyProposal model has columns: `admin_decision`, `auto_promotable`, `backtest_passed`
  - If missing: add migration or rename `status` to `admin_decision` to match code expectations
  - In `backend/ai/proposal_generator.py:563-567`:
    ```python
    # BEFORE (buggy):
    proposals = db.query(DBProposal).filter(
        DBProposal.status == "pending",
        DBProposal.auto_promotable == True,
        DBProposal.backtest_passed == True
    ).all()
    
    # AFTER (matched to actual model columns):
    proposals = db.query(DBProposal).filter(
        DBProposal.admin_decision == "pending",
        DBProposal.auto_promotable == True,
        DBProposal.backtest_passed == True
    ).all()
    ```
  - In `backend/ai/rejection_learner.py:242-255`: verify column names match
  - Replace bare `except Exception: pass` at proposal_generator.py:622-623 with specific `except (AttributeError, KeyError) as e: logger.error(...)`

  **Must NOT do**:
  - Don't guess columns — read the actual model definition first

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Schema verification + column alignment across 2 files
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with T16-T17, T19-20)
  - **Blocks**: None
  - **Blocked By**: Wave 1

  **References**:
  - `backend/models/database.py` — StrategyProposal model definition
  - `backend/ai/proposal_generator.py:563-567,622-623` — buggy query
  - `backend/ai/rejection_learner.py:242-255` — potential column mismatch

  **Acceptance Criteria**:
  - [ ] Column names match model definition
  - [ ] Auto-promote pipeline doesn't silently fail
  - [ ] `pytest backend/tests/test_proposal_pipeline.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Proposal pipeline queries correct columns
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_proposal_pipeline.py -v
    Expected Result: Queries execute without AttributeError, pipeline processes proposals correctly
    Evidence: .sisyphus/evidence/task-18-proposal-columns.txt
  ```

  **Commit**: YES
  - Message: `fix(ai): proposal generator column names aligned with StrategyProposal model`
  - Files: `backend/ai/proposal_generator.py`, `backend/ai/rejection_learner.py`, `backend/tests/test_proposal_pipeline.py` (new)

---

- [x] 19. Shadow Experiment Real Signal Generation [#42]

  **What to do**:
  - In `backend/core/experiment_runner.py:75-107`:
  - Replace hardcoded fake data with real signal generation:
    ```python
    async def run_shadow_experiment(self, experiment, duration_days=7):
        strategy = self.registry.create_strategy(experiment.strategy_name)
        strategy.mode = "shadow"  # Signal-only, no execution
        signals = []
        for day in range(duration_days):
            daily_signals = await strategy.run_cycle()
            for sig in daily_signals:
                # Compute hypothetical P&L from current market price
                hypothetical_pnl = self._compute_hypothetical_pnl(sig)
                signals.append({**sig, "hypothetical_pnl": hypothetical_pnl})
        return self._evaluate_signals(signals)
    ```
  - Add `_compute_hypothetical_pnl(signal)` that gets current market price and computes: if signal.direction == "buy_yes" and market.price < 1.0, pnl = (1.0 - price) * size
  - At minimum (if full integration is too complex): raise `NotImplementedError("Shadow experiment requires real strategy runner integration")` instead of returning fake data
  - Add feature flag: `SHADOW_USES_REAL_SIGNALS=true` to enable real signal path

  **Must NOT do**:
  - Don't execute real trades in shadow mode
  - Don't allow shadow → paper promotion with fake data

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Connects experiment runner to strategy runner, needs careful mode isolation
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with T16-T18, T20)
  - **Blocks**: None
  - **Blocked By**: Wave 1 (T2 base strategy changes)

  **References**:
  - `backend/core/experiment_runner.py:75-107` — current fake data generation
  - `backend/strategies/base.py` — BaseStrategy.run_cycle() integration
  - `backend/core/strategy_executor.py` — how real strategies run

  **Acceptance Criteria**:
  - [ ] Shadow signals based on real market data
  - [ ] Shadow → paper promotion requires real performance stats
  - [ ] `pytest backend/tests/test_shadow_experiment.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Shadow experiment produces real signal data
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_shadow_experiment.py -v
    Expected Result: Signals based on real data, P&L computed from market prices, NOT hardcoded
    Evidence: .sisyphus/evidence/task-19-shadow-real.txt
  ```

  **Commit**: YES
  - Message: `fix(core): shadow experiment generates real signals from strategy runner`
  - Files: `backend/core/experiment_runner.py`, `backend/tests/test_shadow_experiment.py` (new), `backend/config.py` (SHADOW_USES_REAL_SIGNALS flag)

---

- [x] 20. Frontend GlobeView React.lazy() + Suspense Skeleton [#59]

  **What to do**:
  - In file that imports GlobeView (likely Dashboard.tsx or similar):
    ```tsx
    // BEFORE:
    import { GlobeView } from '../components/GlobeView';
    
    // AFTER:
    const GlobeView = React.lazy(() => import('../components/GlobeView'));
    ```
  - Wrap usage in Suspense:
    ```tsx
    <Suspense fallback={<div className="globe-skeleton animate-pulse bg-gray-800 rounded-lg h-96" />}>
      <GlobeView />
    </Suspense>
    ```
  - Add `vite-plugin-visualizer` to devDependencies and configure in vite.config.ts for bundle size tracking
  - Verify: initial bundle size reduced by ~1MB (three-globe code-split)

  **Must NOT do**:
  - Don't change GlobeView component behavior — only loading strategy

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
    - Reason: Frontend bundle optimization with React.lazy pattern
  - **Skills**: `["frontend-ui-ux"]`
    - `frontend-ui-ux`: UI component refactoring for lazy loading

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with T16-T19)
  - **Blocks**: None
  - **Blocked By**: Wave 1

  **References**:
  - `frontend/src/components/GlobeView.tsx` — the component to lazy-load
  - `frontend/src/pages/Dashboard.tsx` — likely import location
  - React docs: React.lazy + Suspense pattern

  **Acceptance Criteria**:
  - [ ] GlobeView lazy-loaded (code-split)
  - [ ] Skeleton shown during load
  - [ ] `cd frontend && npm run build` succeeds with reduced chunk size
  - [ ] `cd frontend && npx vitest run` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: GlobeView loads without blocking initial render
    Tool: Playwright
    Preconditions: Frontend running at localhost:5173
    Steps:
      1. Page.goto("http://localhost:5173")
      2. Assert: page has skeleton element
      3. Wait for GlobeView to load
      4. Assert: globe canvas visible
    Expected Result: Skeleton shown first, globe loads after, page interactive immediately
    Evidence: .sisyphus/evidence/task-20-globe-lazy.png
  ```

  **Commit**: YES
  - Message: `perf(frontend): lazy-load GlobeView with Suspense skeleton to reduce initial bundle`
  - Files: `frontend/src/pages/Dashboard.tsx`, `frontend/vite.config.ts`

---

- [x] 21. Grafana Dashboard JSON (P&L, Breakers, Latency, Health) [#58]

  **What to do**:
  - Create `backend/monitoring/grafana/` directory
  - Create `backend/monitoring/grafana/polyedge-dashboard.json` with panels:
    - **Row 1: Live P&L** — time-series panel: `BotState.bankroll`, `BotState.total_pnl` (Prometheus gauges)
    - **Row 2: Circuit Breakers** — status panel: `circuit_breaker_state` metric per breaker
    - **Row 3: Trade Latency** — histogram: order placement → confirmation time
    - **Row 4: Strategy Health** — table: per-strategy win rate, Sharpe, drawdown, Brier
    - **Row 5: Risk Rejections** — counter: `risk_rejections_total{reason}` breakdown
    - **Row 6: Signal Counts** — per-strategy signal generation rate
  - Add `docker-compose.yml` Grafana service definition:
    ```yaml
    grafana:
      image: grafana/grafana:latest
      ports: ["3000:3000"]
      volumes: ["./backend/monitoring/grafana:/etc/grafana/provisioning/dashboards"]
    ```

  **Must NOT do**:
  - Don't change existing Prometheus metrics — only add visualization

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: JSON dashboard creation + docker-compose addition
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with T22-T24)
  - **Blocks**: None
  - **Blocked By**: None (T22 instruments the metrics, but dashboard JSON can be created independently)

  **References**:
  - `backend/monitoring/metrics.py` — existing metric definitions
  - `backend/monitoring/middleware.py` — existing Prometheus middleware
  - `docker-compose.yml` — add Grafana service
  - Grafana docs: dashboard JSON format

  **Commit**: YES
  - Message: `feat(monitoring): Grafana dashboard for P&L, breakers, latency, health, rejections`
  - Files: `backend/monitoring/grafana/polyedge-dashboard.json` (new), `docker-compose.yml`

---

- [x] 22. Prometheus Metrics Instrumentation (12 Blind Spots) [#58]

  **What to do**:
  - Define new Prometheus metrics in `backend/monitoring/metrics.py`:
    - `trade_execution_total{strategy, result}` — Counter for each trade attempt
    - `risk_rejection_total{strategy, reason}` — Counter for each rejection
    - `order_latency_seconds` — Histogram for order placement time
    - `settlement_total{status}` — Counter for settlement outcomes
    - `circuit_breaker_state{breaker_name}` — Gauge (0=open, 1=half-open, 2=closed)
    - `strategy_health_gauge{metric}` — Gauge for win_rate, sharpe, drawdown, brier
    - `bot_state_gauge{field}` — Gauge for bankroll, total_pnl, paper_bankroll
  - Instrument in core modules:
    - `backend/core/auto_trader.py` — increment `trade_execution_total`
    - `backend/core/risk_manager.py` — increment `risk_rejection_total`
    - `backend/strategies/order_executor.py` — observe `order_latency_seconds`
    - `backend/core/settlement.py` — increment `settlement_total`
    - `backend/core/circuit_breaker.py` — set `circuit_breaker_state`
    - `backend/core/strategy_health.py` — set `strategy_health_gauge`

  **Must NOT do**:
  - Don't change business logic — only add metric instrumentation lines

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 6+ files to instrument with careful metric placement
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with T21, T23-T24)
  - **Blocks**: None (T21 visualizes these metrics, but can be created independently)
  - **Blocked By**: Wave 2 (core modules stabilized before instrumentation)

  **References**:
  - `backend/monitoring/metrics.py` — add new metrics
  - `backend/monitoring/middleware.py` — existing request instrumentation pattern
  - Prometheus Python client docs: Counter, Gauge, Histogram API

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Metrics endpoint returns new instrumented metrics
    Tool: Bash (curl)
    Steps:
      1. curl -s http://localhost:8000/metrics | grep -E "(trade_execution_total|risk_rejection_total|order_latency|settlement_total|circuit_breaker_state|strategy_health)"
    Expected Result: All new metric names present in /metrics output
    Evidence: .sisyphus/evidence/task-22-metrics.txt
  ```

  **Commit**: YES
  - Message: `feat(monitoring): instrument 12 Prometheus metrics across trade execution pipeline`
  - Files: `backend/monitoring/metrics.py, backend/core/auto_trader.py, backend/core/risk_manager.py, backend/strategies/order_executor.py, backend/core/settlement.py, backend/core/circuit_breaker.py, backend/core/strategy_health.py`

---

- [x] 23. Production Runbook Documentation [#60]

  **What to do**:
  - Create `docs/runbook/` directory with:
    - **deployment.md**: Railway backend deploy steps, Vercel frontend deploy, env var checklist, pre-deployment health check
    - **rollback.md**: git revert procedure, DB migration rollback, PM2 restart steps
    - **incidents.md**: alert types → severity → triage flow → mitigation steps → postmortem template
    - **circuit-breaker-runbook.md**: what each breaker does, what trips it, how to reset, escalation path
    - **README.md** (in runbook/): index linking to all documents

  **Must NOT do**:
  - Don't include live credentials or URLs in documentation

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: Documentation creation, no code changes
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with T21-T22, T24)
  - **Blocks**: None
  - **Blocked By**: None (pure documentation, no dependencies)

  **References**:
  - `railway.json`, `vercel.json` — deployment configs
  - `ecosystem.config.js` — PM2 process management
  - `backend/config.py` — env var reference
  - `backend/core/circuit_breaker.py` — breaker implementation

  **Commit**: YES
  - Message: `docs: production runbook with deployment, rollback, incidents, circuit breaker procedures`
  - Files: `docs/runbook/deployment.md`, `docs/runbook/rollback.md`, `docs/runbook/incidents.md`, `docs/runbook/circuit-breaker-runbook.md`, `docs/runbook/README.md` (all new)

---

- [x] 24. Polygon Private Mempool Integration [#61]

  **What to do**:
  - In `backend/config.py`: add
    ```python
    POLYGON_PRIVATE_MEMPOOL_URL: str = Field(
        default="https://polygon-rpc.com",  # Fallback to public RPC
        description="Polygon Private Mempool RPC URL for MEV protection"
    )
    ```
  - In `backend/data/polymarket_clob.py`: for all write transaction submissions (sign_and_send), use `settings.POLYGON_PRIVATE_MEMPOOL_URL` instead of default RPC URL
  - Read operations (get_balance, get_orders, etc.) continue through existing RPC provider
  - Add `test_private_mempool.py`: verify write ops use private mempool URL, read ops use standard RPC

  **Must NOT do**:
  - Don't change read path RPC — only write submissions
  - Don't remove fallback to public RPC

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Config addition + RPC URL swap in one module
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with T21-T23)
  - **Blocks**: None
  - **Blocked By**: None (independent config change)

  **References**:
  - `backend/data/polymarket_clob.py` — find all sign_and_send / transaction submission calls
  - `backend/config.py` — add new config field
  - Polygon Private Mempool blog: RPC endpoint for private submission

  **Acceptance Criteria**:
  - [ ] Write transactions use private mempool (when configured)
  - [ ] Read operations unaffected
  - [ ] `pytest backend/tests/test_private_mempool.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Write ops use private mempool endpoint
    Tool: Bash (pytest)
    Steps:
      1. POLYGON_PRIVATE_MEMPOOL_URL=https://private.polygon-rpc.com pytest backend/tests/test_private_mempool.py -v
    Expected Result: sign_and_send uses private URL, get_balance uses standard URL
    Evidence: .sisyphus/evidence/task-24-private-mempool.txt
  ```

  **Commit**: YES
  - Message: `feat(data): Polygon Private Mempool integration for MEV-protected writes`
  - Files: `backend/config.py`, `backend/data/polymarket_clob.py`, `backend/tests/test_private_mempool.py` (new)

---

- [x] 25. Kalshi BatchCreateOrders + AmendOrder + BatchCancelOrders [#62]

  **What to do**:
  - In `backend/data/kalshi_client.py`:
    - Add `batch_create_orders(self, orders: list[dict]) -> dict`:
      ```python
      async def batch_create_orders(self, orders: list[dict]):
          return await self._request("POST", "/portfolio/batch_create_orders", json={"orders": orders})
      ```
    - Add `batch_cancel_orders(self, order_ids: list[str]) -> dict`:
      ```python
      async def batch_cancel_orders(self, order_ids: list[str]):
          return await self._request("DELETE", "/portfolio/batch_cancel_orders", json={"order_ids": order_ids})
      ```
    - Add `amend_order(self, order_id: str, new_price: float = None, new_size: int = None) -> dict`:
      ```python
      async def amend_order(self, order_id: str, new_price: float = None, new_size: int = None):
          payload = {"order_id": order_id}
          if new_price is not None: payload["new_price"] = new_price
          if new_size is not None: payload["new_size"] = new_size
          return await self._request("POST", "/portfolio/amend_order", json=payload)
      ```
  - Wire into arb strategy for atomic multi-leg placement
  - Add `test_kalshi_batch.py`: mock API responses, verify batch methods

  **Must NOT do**:
  - Don't change existing single-order methods — add new batch methods alongside

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: New API methods + mock testing + arb strategy integration
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with T26-T33)
  - **Blocks**: None
  - **Blocked By**: Wave 3 (wallet reconciliation, proposal pipeline stable)

  **References**:
  - `backend/data/kalshi_client.py` — existing _request framework, auth pattern
  - Kalshi API v2 docs: batch_create_orders, batch_cancel_orders, amend_order endpoints
  - `backend/modules/arbitrage/kalshi_arb.py` — arb strategy to wire into

  **Acceptance Criteria**:
  - [ ] Batch methods added with correct API signatures
  - [ ] `pytest backend/tests/test_kalshi_batch.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Kalshi batch order creation works
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_kalshi_batch.py -v
    Expected Result: Batch methods call correct endpoints with correct payloads
    Evidence: .sisyphus/evidence/task-25-kalshi-batch.txt
  ```

  **Commit**: YES
  - Message: `feat(data): Kalshi BatchCreateOrders, AmendOrder, BatchCancelOrders API methods`
  - Files: `backend/data/kalshi_client.py`, `backend/modules/arbitrage/kalshi_arb.py`, `backend/tests/test_kalshi_batch.py` (new)

---

- [x] 26. Platt Scaling + Extremization in AI Ensemble [#63]

  **What to do**:
  - In `backend/ai/ensemble.py`:
    - Add `platt_scale(raw_prob: float, a: float, b: float) -> float`:
      ```python
      def platt_scale(raw_prob: float, a: float, b: float) -> float:
          return 1.0 / (1.0 + math.exp(-(a * raw_prob + b)))
      ```
    - Add `extremize(prob: float, factor: float = 1.2) -> float`:
      ```python
      def extremize(prob: float, factor: float = 1.2) -> float:
          return clamp_probability(0.5 + (prob - 0.5) * factor)
      ```
    - Apply after ensemble aggregation: `adjusted = extremize(platt_scale(avg_prob, a, b))`
    - Store Platt params (`a`, `b`) in StrategyConfig.params, retrain monthly via calibration job
    - Add `test_platt_extremize.py`: verify scaling behavior, extremization amplification

  **Must NOT do**:
  - Don't change existing ensemble aggregation, only add post-processing

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Statistical post-processing with parameter learning
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with T25, T27-T33)
  - **Blocks**: None
  - **Blocked By**: Wave 3 (T16 ensemble confidence fix)

  **References**:
  - `backend/ai/ensemble.py` — existing ensemble aggregation
  - AIA Forecaster (arXiv:2511.07678) — Platt scaling + extremization methodology
  - `backend/core/calibration.py` — existing calibration framework for training Platt params

  **Acceptance Criteria**:
  - [ ] Platt scaling calibrated correctly
  - [ ] Extremization amplifies deviation from 0.5
  - [ ] `pytest backend/tests/test_platt_extremize.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Platt scaling improves calibration
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_platt_extremize.py -v
    Expected Result: Platt-scaled probabilities more accurate than raw, extremize amplifies edge
    Evidence: .sisyphus/evidence/task-26-platt.txt
  ```

  **Commit**: YES
  - Message: `feat(ai): Platt scaling and extremization post-processing for AI ensemble`
  - Files: `backend/ai/ensemble.py`, `backend/tests/test_platt_extremize.py` (new)

---

- [x] 27. LMSR-Based Spread Calculation for Market Maker [#64]

  **What to do**:
  - In `backend/strategies/market_maker.py`:
    - Add `lmsr_spread(yes_inventory: float, no_inventory: float, liquidity_param: float = 10.0) -> dict`:
      ```python
      def lmsr_spread(yes_inventory, no_inventory, liquidity_param=10.0):
          b = liquidity_param
          yes_price = math.exp(yes_inventory / b) / (math.exp(yes_inventory / b) + math.exp(no_inventory / b))
          no_price = 1.0 - yes_price
          spread = abs(yes_price - self.current_midpoint)
          return {"yes_price": yes_price, "no_price": no_price, "spread": spread}
      ```
    - Add `SPREAD_MODE` config: `"static" | "lmsr"`
    - When `SPREAD_MODE == "lmsr"`, use LMSR formulas instead of static spread
    - Add `test_market_maker_lmsr.py`: test LMSR behavior at different inventory levels

  **Must NOT do**:
  - Don't remove static spread — make it configurable

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: New market-making formula with config toggle
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with T25-T26, T28-T33)
  - **Blocks**: None
  - **Blocked By**: Wave 3 (T6 market maker validation)

  **References**:
  - `backend/strategies/market_maker.py:45-85` — existing calculate_spread()
  - Hanson (2003) — LMSR cost function formula
  - `backend/config.py` — add SPREAD_MODE config

  **Acceptance Criteria**:
  - [ ] LMSR spread widens with inventory imbalance
  - [ ] `SPREAD_MODE=static` preserves existing behavior
  - [ ] `pytest backend/tests/test_market_maker_lmsr.py` → PASS

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: LMSR spread adjusts to inventory
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_market_maker_lmsr.py -v
    Expected Result: More YES inventory → lower YES price, wider spread
    Evidence: .sisyphus/evidence/task-27-lmsr.txt
  ```

  **Commit**: YES
  - Message: `feat(strategies): LMSR-based spread calculation for market maker`
  - Files: `backend/strategies/market_maker.py`, `backend/config.py`, `backend/tests/test_market_maker_lmsr.py` (new)

---

- [x] 28. Kelly Fraction Optimization Script [#65]

  **What to do**:
  - Create `scripts/optimize_kelly.py`:
    ```python
    """Optimize Kelly fraction per strategy using historical Trade data."""
    import argparse
    from backend.models.database import SessionLocal, Trade, StrategyConfig
    
    def optimize():
        fractions = [0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
        db = SessionLocal()
        strategies = db.query(StrategyConfig).all()
        results = {}
        for strat in strategies:
            trades = db.query(Trade).filter(Trade.strategy == strat.strategy_name).all()
            if len(trades) < 10:
                continue
            for kf in fractions:
                pnl, sharpe, max_dd = simulate(trades, kf)
                results[f"{strat.strategy_name}_{kf}"] = {"pnl": pnl, "sharpe": sharpe, "max_dd": max_dd}
        best = max(results.items(), key=lambda x: x[1]["sharpe"])
        print(f"Optimal Kelly fraction: {best}")
    ```
  - Run against local DB of resolved trades. Output: per-strategy optimal Kelly fraction table.
  - Do NOT auto-apply — this is an analysis tool. Results inform manual config adjustments.

  **Must NOT do**:
  - Don't auto-modify production config — this is an analysis script

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Simulation script with Sharpe/MDD computation
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with T25-T27, T29-T33)
  - **Blocks**: None
  - **Blocked By**: None (standalone script, no dependencies)

  **References**:
  - `backend/models/database.py` — Trade model for historical data
  - Kelly (1956) — original fractional Kelly formula
  - `backend/core/risk_manager.py` — current Kelly implementation

  **Commit**: YES
  - Message: `feat(scripts): Kelly fraction optimization script using historical trade data`
  - Files: `scripts/optimize_kelly.py` (new)

---

- [x] 29. Resolution Source Validation for Cross-Platform Arb [#66]

  **What to do**:
  - In `backend/modules/arbitrage/kalshi_arb.py` (or new `backend/modules/arbitrage/arb_validation.py`):
    - Add `compare_resolution(market_a: dict, market_b: dict) -> ResolutionComparison`:
      ```python
      from dataclasses import dataclass
      from datetime import datetime
      
      @dataclass
      class ResolutionComparison:
          source_match: bool
          settlement_time_delta: float  # hours
          dispute_process_match: bool
          risk_score: float  # 0.0 = safe, 1.0 = extremely risky
      
      def compare_resolution(market_a, market_b):
          source_match = market_a.get("resolution_source") == market_b.get("resolution_source")
          time_a = datetime.fromisoformat(market_a.get("end_date"))
          time_b = datetime.fromisoformat(market_b.get("end_date"))
          time_delta = abs((time_a - time_b).total_seconds()) / 3600
          # Risk: source mismatch (0.5) + time > 1h (0.1) + other factors
          risk = (0.0 if source_match else 0.5) + min(0.5, time_delta / 24)
          return ResolutionComparison(source_match, time_delta, True, risk)
      ```
    - Reject arb opportunities where `risk_score > 0.3`
    - Must verify FULL resolution text (not just title) matches

  **Must NOT do**:
  - Don't execute arb without resolution validation
  - Don't rely on title alone for match

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: New validation module for cross-platform safety
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with T25-T28, T30-T33)
  - **Blocks**: None
  - **Blocked By**: Wave 4 (T25 Kalshi batch methods needed for arb execution)

  **References**:
  - Morini (2021) "Arbitrage in Prediction Markets" — resolution risk framework
  - Polyguana cross-platform arb guide — real-world resolution divergence examples
  - `backend/modules/arbitrage/kalshi_arb.py` — existing arb detection logic

  **Commit**: YES
  - Message: `feat(arb): resolution source validation prevents divergence-risk arbs`
  - Files: `backend/modules/arbitrage/arb_validation.py` (new), `backend/modules/arbitrage/kalshi_arb.py`

---

- [x] 30. Becker Dataset Parquet Integration [#67]

  **What to do**:
  - Create `scripts/integrate_becker_data.py`:
    - Downloads Parquet data from https://s3.jbecker.dev/data.tar.zst (or uses local copy)
    - Converts to SQLite tables for PolyEdge consumption: `historical_markets`, `historical_trades`
    - Indexes by market slug and timestamp for fast queries
  - In `backend/core/backtester.py` (or new `backend/core/historical_backtester.py`):
    - Load historical market data from Becker tables
    - Replay strategy signals against historical prices
    - Compute P&L, win rate, Sharpe for each strategy
  - In `backend/ai/training/train.py`: replace synthetic training data (line 46-50) with Becker real market outcomes
  - Add `BECKER_DATA_PATH` config (path to extracted data)

  **Must NOT do**:
  - Don't commit large data files to repo — data path is configurable
  - Don't replace existing backtester — augment with historical data support

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Data pipeline integration + training data replacement + backtester enhancement
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with T25-T29, T31-T33)
  - **Blocks**: None
  - **Blocked By**: None (external data, no code dependencies)

  **References**:
  - Jon-Becker/prediction-market-analysis GitHub repo — Parquet schemas, data download
  - `backend/ai/training/train.py:46-50` — synthetic data to replace
  - `backend/core/backtester.py` — existing backtester structure

  **Commit**: YES
  - Message: `feat(data): Becker dataset integration for historical backtesting and model training`
  - Files: `scripts/integrate_becker_data.py` (new), `backend/core/historical_backtester.py` (new), `backend/ai/training/train.py`, `backend/config.py`

---

- [x] 31. ForecastBench AI Ensemble Benchmarking [#68]

  **What to do**:
  - Create `scripts/benchmark_forecastbench.py`:
    - Load ForecastBench public question set (or subset of resolved Polymarket markets matching ForecastBench criteria)
    - Run PolyEdge AI ensemble against each question
    - Compute Brier score, compare against published baselines:
      - Human superforecasters: 0.145
      - GPT-4o: 0.155
      - Claude 3.5 Sonnet: 0.154
      - Random uniform: 0.285
      - Always 0.5: 0.205
  - Output: PolyEdge ensemble Brier score vs baselines table
  - In `backend/core/calibration.py`: add `BRIER_DISABLE_THRESHOLD` config (default 0.35)
  - Auto-disable strategies with sustained Brier > threshold over 30+ predictions

  **Must NOT do**:
  - Don't auto-disable strategies until threshold is validated against real data

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Benchmarking script + config threshold + auto-disable logic
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with T25-T30, T32-T33)
  - **Blocks**: None
  - **Blocked By**: Wave 3 (T16 ensemble confidence scoring)

  **References**:
  - ForecastBench leaderboard — baselines and methodology
  - `backend/core/calibration.py` — add BRIER_DISABLE_THRESHOLD
  - `backend/config.py` — add config field

  **Commit**: YES
  - Message: `feat(ai): ForecastBench benchmarking and Brier-based strategy auto-disable`
  - Files: `scripts/benchmark_forecastbench.py` (new), `backend/core/calibration.py`, `backend/config.py`

---

- [x] 32. GeminiProvider for 5-Forecaster Ensemble [#69]

  **What to do**:
  - Create `backend/ai/gemini.py`:
    ```python
    class GeminiProvider:
        def __init__(self, api_key: str = None):
            self.api_key = api_key or settings.GEMINI_API_KEY
            self.model = "gemini-1.5-pro"
        
        async def predict(self, prompt: str) -> dict:
            # Call Gemini via OpenRouter or Google AI SDK
            response = await self._call_api(prompt)
            return {"probability": response.probability, "confidence": response.confidence}
    ```
  - In `backend/ai/ensemble.py`: add Gemini to provider rotation:
    ```python
    providers = [
        ("claude", self.claude, 0.40),
        ("groq", self.groq, 0.30),
        ("gemini", self.gemini, 0.15),
        ("mirofish", self.mirofish, 0.15),
    ]
    ```
  - Add `GEMINI_API_KEY` and `GEMINI_ENABLED` config
  - Add `test_gemini_provider.py`: mock API, test integration

  **Must NOT do**:
  - Don't make Gemini required — disable-able via config
  - Don't break existing providers

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: New AI provider integration + ensemble weight adjustment
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with T25-T31, T33)
  - **Blocks**: None
  - **Blocked By**: Wave 3 (T16 ensemble confidence scoring)

  **References**:
  - `backend/ai/claude.py` — existing AI provider pattern
  - Google Gemini API / OpenRouter API docs
  - `backend/ai/ensemble.py` — provider rotation
  - `backend/config.py` — add GEMINI_API_KEY, GEMINI_ENABLED

  **Commit**: YES
  - Message: `feat(ai): Gemini provider for 5-forecaster ensemble`
  - Files: `backend/ai/gemini.py` (new), `backend/ai/ensemble.py`, `backend/config.py`, `backend/tests/test_gemini_provider.py` (new)

---

- [x] 33. Maker-Edge Optimization (Optimism Tax Spread Widening) [#70]

  **What to do**:
  - In `backend/strategies/market_maker.py`:
    - Add `optimism_tax_factor(yes_price: float) -> float`:
      ```python
      def optimism_tax_factor(yes_price: float) -> float:
          """Widen spread for YES longshots where taker bias is strongest."""
          if yes_price < 0.10: return 1.5   # Extreme longshot
          if yes_price < 0.20: return 1.3   # Longshot bias zone
          if yes_price < 0.30: return 1.1   # Moderate bias
          return 1.0  # No bias adjustment
      ```
    - Apply to spread: `adjusted_spread = spread * optimism_tax_factor(yes_price)`
  - In `backend/modules/execution/copy_trader.py`:
    - Add `optimism_tax_discount(signal: dict) -> float`:
      ```python
      def optimism_tax_discount(signal):
          """Apply discount to copied signals that match taker bias pattern."""
          if signal.get("price") and signal["price"] < 0.20 and signal.get("direction") == "buy_yes":
              return 0.85  # 15% discount for YES longshots
          return 1.0
      ```
    - Apply discount to position sizing for biased signals
  - Add `maker_edge_capture_rate` Prometheus metric
  - Add `test_maker_edge.py`: verify optimism tax adjustments

  **Must NOT do**:
  - Don't change strategy logic, only add adjustments as multipliers

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Research-to-code translation across 2 strategies
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with T25-T32)
  - **Blocks**: None
  - **Blocked By**: Wave 3 (T6 market maker validation, T11 copy trader lock)

  **References**:
  - Becker (2026) "Microstructure of Wealth Transfer" — optimism tax quantification
  - `backend/strategies/market_maker.py:45-85` — spread calculation
  - `backend/modules/execution/copy_trader.py:75-96` — signal copying logic

  **Commit**: YES
  - Message: `feat(strategies): maker-edge optimization with optimism-tax-aware spread widening`
  - Files: `backend/strategies/market_maker.py`, `backend/modules/execution/copy_trader.py`, `backend/tests/test_maker_edge.py` (new)

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [ ] TF1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in `.sisyphus/evidence/`. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [33/33] | VERDICT: APPROVE/REJECT`

- [ ] TF2. **Code Quality Review** — `unspecified-high`
  Run `pytest` from project root + `cd frontend && npm run build`. Review all changed files for: bare `except Exception`, `pass` in exception handlers, hardcoded values, `as any` in TypeScript. Check AI slop patterns.
  Output: `Build [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] TF3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Execute key QA scenarios: run backend API, verify /metrics endpoint has new metrics, verify /api/v1/health returns OK, verify Kalshi batch methods with mock server, verify debate engine parallel execution. Test cross-task integration.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] TF4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff. Verify 1:1 — everything in spec was built, nothing beyond spec was built. Check "Must NOT do" compliance. Detect cross-task contamination. Flag unaccounted changes.
  Output: `Tasks [33/33 compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## PR Workflow (MANDATORY)

Every task follows this exact flow:

```
1. IMPLEMENT  → Write code, add types, follow existing patterns
2. TEST       → Write and run unit/integration tests
3. VERIFY     → Run QA Scenarios from plan, capture evidence
4. VALIDATE   → Run lsp_diagnostics, pytest/vitest, `npm run build`
5. MANUAL QA  → Execute the deliverable end-to-end (curl/Playwright/REPL)
6. CREATE PR  → Group completed wave tasks, open PR with `Closes #N`
7. CONTINUE   → Proceed to next wave (blocked waves unblock)
```

### PR Grouping Strategy

- **Each wave = 1 PR** (tasks within a wave are small and atomic)
- **PR title**: Wave summary + list of `Closes #N`
- **PR body**: Checklist of tasks + evidence links
- **Merge requirement**: All wave tasks complete, all tests pass, manual QA screenshots attached

### Per-Task Issue Wiring

Each task commit message closes the corresponding GitHub issue:

| Wave | PR Closes | Tasks + Issues |
|------|----------|----------------|
| 1 | `Closes #39, Closes #40, Closes #41, Closes #43, Closes #54, Closes #55, Closes #53, Closes #48` | T1(#39) T2(#40) T3(#41) T4(#43) T5(#54) T6(#55) T7(#53) T8(#48) |
| 2 | `Closes #37, Closes #38, Closes #44, Closes #45, Closes #46, Closes #52, Closes #57` | T9(#37) T10(#38) T11(#44) T12(#45) T13(#46) T14(#52) T15(#57) |
| 3 | `Closes #47, Closes #49, Closes #50, Closes #42, Closes #59` | T16(#47) T17(#49) T18(#50) T19(#42) T20(#59) |
| 4 | `Closes #58, Closes #60, Closes #61` | T21(#58) T22(#58) T23(#60) T24(#61) |
| 5 | `Closes #62, Closes #63, Closes #64, Closes #65, Closes #66, Closes #67, Closes #68, Closes #69, Closes #70` | T25(#62) T26(#63) T27(#64) T28(#65) T29(#66) T30(#67) T31(#68) T32(#69) T33(#70) |

### PR Template

```markdown
## Summary
Wave N: [description] — fixes N issues

## Tasks Completed
- [x] T1: [title] (Closes #NN)
- [x] T2: [title] (Closes #NN)
...

## Verification
### Test Results
```
[Pytest/test output]
```

### Manual QA Screenshots
- T1: .sisyphus/evidence/task-1-*.png
- T2: .sisyphus/evidence/task-2-*.txt
...

### Checklist
- [ ] All tasks in wave completed
- [ ] `pytest` passes (N tests, 0 failures)
- [ ] `npm run build` succeeds (frontend waves)
- [ ] Evidence files saved
- [ ] Zero new `except Exception` blocks
- [ ] IMPLEMENTATION_GAPS.md updated
```

## Commit Strategy

| Wave | Commit Message | Files |
|------|---------------|-------|
| 1 | `fix(ai,strategies): critical foundation — Closes #39, #40, #41, #43, #54, #55, #53, #48` | T1-T8 files |
| 2 | `fix(queue,strategies,data): concurrency safety — Closes #37, #38, #44, #45, #46, #52, #57` | T9-T15 files |
| 3 | `fix(ai,core,frontend): data integrity — Closes #47, #49, #50, #42, #59` | T16-T20 files |
| 4 | `feat(monitoring,docs,data): infrastructure — Closes #58, #60, #61` | T21-T24 files |
| 5 | `feat(research): enhancements — Closes #62, #63, #64, #65, #66, #67, #68, #69, #70` | T25-T33 files |

## Success Criteria

### Verification Commands
```bash
# Backend tests
pytest backend/tests/ -v  # Expected: 150+ pass, 0 fail

# Frontend tests
cd frontend && npm run build  # Expected: Success
cd frontend && npx vitest run  # Expected: All pass

# Metrics endpoint
curl -s http://localhost:8000/metrics | grep -E "(trade_execution_total|risk_rejection_total|circuit_breaker_state)"  # Expected: present

# Health endpoint
curl -s http://localhost:8000/api/v1/health  # Expected: {"status": "ok"}
```

### Final Checklist
- [ ] All 6 critical issues fixed
- [ ] All 9 high issues fixed
- [ ] All 7 medium issues addressed
- [ ] 10 research features implemented
- [ ] IMPLEMENTATION_GAPS.md updated with fix dates
- [ ] Zero new bare `except Exception` blocks
- [ ] `.sisyphus/evidence/` populated for all tasks
