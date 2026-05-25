# PolyEdge — Comprehensive Improvement Plan

## TL;DR

> **Goal**: Fix $551/year self-hedge waste, eliminate negative-EV trades, improve maker fill rate from 0.7%→60%, unlock $1,782 stuck capital, and instrument the alpha source to determine capacity ceiling.
>
> **Deliverables**:
> - 4 new RiskManager methods (side lock, edge filter, per-strategy circuit, auto-pause)
> - Bucket-calibrated Kelly sizing using realized win rates
> - Maker-first order execution with 15s limit-then-taker escalation
> - Token bucket rate limiter for order submission
> - Position monitor (30min job) + stale-position close script
> - SignalLog table for alpha source instrumentation
> - Calibration API with per-bucket breakdown
>
> **Estimated Effort**: Medium–Large (30+ tasks, 4+ waves)
> **Parallel Execution**: YES — foundation tasks unblock 5+ parallel waves
> **Critical Path**: RiskManager additions → btc_oracle calibration → position monitor → SignalLog

---

## Context

### Original Request
Comprehensive improvements from 28-day live trading audit (254 predictions, 910 buy orders, +$1,702.59 net realized P&L on $3,128.63 deployed). See `.sisyphus/drafts/btc-oracle-alpha-research.md` for alpha source analysis.

### What We Discovered
- **Profitable strategy is `btc_oracle.py`, NOT `btc_momentum.py`** — btc_momentum is disabled with -49.5% ROI; btc_oracle produces +58.3% ROI via 2–5s structural oracle repricing lag
- Alpha: RSI + momentum + VWAP + SMA on Coinbase/Kraken/Binance 1-min BTC candles predicts Polymarket BTC market direction before Polymarket reprices
- **Edge is real and structural** — not statistical artifact; will persist until market microstructure changes
- **Execution defects** — self-hedging, no edge filter, bursty submission, 81 forgotten positions

---

## Work Objectives

### Core Objective
Maximize net realized P&L by fixing execution defects, calibrating Kelly sizing to realized win rates, reducing maker fees, unlocking frozen capital, and instrumenting the alpha source.

### Concrete Deliverables
- `risk_manager.check_side_lock()` — block opposing-side orders on same market
- `risk_manager.check_edge()` — reject entries where `edge_pp < 5`
- `risk_manager.check_strategy_performance()` — auto-pause sports/politics
- `calibration.get_bucket_win_rate()` — realized per-price-bucket win rate lookup
- `calibration.kelly_fraction()` — Quarter-Kelly using realized rate
- `TokenBucketRateLimiter` — per-market 1-order-per-10s, global 3-per-s
- Maker-first order execution in `polymarket_clob.py`
- `position_monitor.py` + APScheduler job
- `scripts/close_stale_positions.py` — dry-run + execute modes
- `SignalLog` table + instrumentation in `btc_oracle.py`
- Calibration API with per-bucket breakdown

### Definition of Done
- [x] `tests/test_side_lock.py` FAILS before side lock impl, PASSES after
- [x] `tests/test_edge_filter.py` FAILS before edge filter impl, PASSES after
- [x] Bucket-calibrated Kelly produces 0% size for 0–30¢ bucket entries
- [x] `close_stale_positions.py --dry-run` reports on all 81 pending positions
- [x] Maker fill rate metric in Prometheus shows >60% (after 2 weeks shadow)
- [x] SignalLog queryable: `SELECT btc_spot, market_mid, edge_pp, pnl WHERE market_mid 0.45–0.55`

### Must Have
- RiskManager changes are additive, never bypass existing safety rules
- All changes work in paper mode before live mode
- No mutation of historical Trade rows
- All Prometheus metrics follow existing naming conventions

### Must NOT Have
- New strategies — 9 exist, 1 profitable
- Bypass RiskManager from strategy code
- Direct BotState writes outside bankroll_reconciliation.py
- Touch ai/ensemble.py or MiroFish

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES — `pytest` at project root
- **Automated tests**: YES (TDD) — every task MUST have a failing test before implementation
- **Framework**: `pytest` + `unittest.mock`
- **Agent-Executed QA**: ALWAYS — every task has QA scenarios executed by agent

### QA Policy
Every task includes agent-executed QA scenarios. Evidence saved to `.sisyphus/evidence/`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation — all RiskManager additions, can run max parallel):
├── T1:  SideLockError + check_side_lock() in risk_manager.py
├── T2:  EdgeFilterError + check_edge() in risk_manager.py
├── T3:  MIN_EDGE_PP config + edge check in validate_trade()
├── T4:  Auto-pause: check_strategy_performance() in circuit_breaker.py
├── T5:  Sports/politics DISABLED_STRATEGIES env-var pause logic
└── T6:  Test side lock (test_side_lock.py — RED phase)

Wave 2 (Bucket Calibration — depends on Wave 1 RiskManager):
├── T7:  calibration.py get_bucket_win_rate() extension
├── T8:  calibration.py kelly_fraction() with Quarter-Kelly
├── T9:  btc_oracle.py — replace static Kelly with calibration.kelly_fraction()
├── T10: Edge filter end-to-end test (test_edge_filter.py — RED phase)
└── T11: Test bucket Kelly (test_bucket_kelly.py — RED phase)

Wave 3 (Execution Quality — max parallel):
├── T12: TokenBucketRateLimiter class in order_executor.py
├── T13: Maker-first execution: place_limit_order() → wait 15s → escalate to taker
├── T14: Rate limiter integration in strategy_executor.py
├── T15: Test rate limiter (test_token_bucket.py — RED phase)
└── T16: Test maker-first execution (test_maker_first.py — RED phase)

Wave 4 (Capital Recovery — parallel after Wave 3):
├── T17: position_monitor.py with stale-position scan logic
├── T18: APScheduler job in scheduler.py for position_monitor
├── T19: scripts/close_stale_positions.py (--dry-run + --execute modes)
├── T20: Test position monitor (test_position_monitor.py — RED phase)
└── T21: Test close_stale_positions script (integration test)

Wave 5 (Instrumentation — parallel, can start mid-project):
├── T22: SignalLog table + Alembic migration
├── T23: btc_oracle.py signal logging to SignalLog
├── T24: Calibration API per-bucket breakdown endpoint
├── T25: Test SignalLog (test_signal_log.py — RED phase)
└── T26: Test calibration API (test_calibration_api.py — RED phase)

Wave FINAL (4 parallel review agents):
├── F1:  Plan compliance audit (oracle)
├── F2:  Code quality review
├── F3:  Real manual QA (Playwright for frontend, curl for API)
└── F4:  Scope fidelity check
```

### Dependency Matrix
- **T1-T6**: No deps — Wave 1 starts immediately
- **T7-T11**: Depend on T1-T3 (RiskManager base methods exist)
- **T12-T16**: Depend on T1-T3 (rate limiter uses same risk checks)
- **T17-T21**: Depend on T7 (position sizing uses Kelly)
- **T22-T26**: Independently parallelizable — can start in Wave 2
- **F1-F4**: After ALL T1-T26 complete

---

## TODOs

---

## TODOs

- [x] 1. **Add `SideLockError` and `check_side_lock()` to RiskManager**

  **What to do**:
  - Add `SideLockError` exception class at top of `risk_manager.py`
  - Add `check_side_lock(self, market_id: str, proposed_side: str, db=None)` method to `RiskManager`
  - Query `Trade` table: `Trade.market_ticker == market_id AND Trade.settled == False AND Trade.direction != proposed_side`
  - If match found → raise `SideLockError(f"Side lock: already have {existing.direction} open on {market_id}; rejecting {proposed_side}")`
  - Call from `validate_trade()` after `_has_unsettled_trade` check, before size adjustment
  - Add Prometheus counter `risk_rejection_side_lock_total`

  **Must NOT do**:
  - Don't add new DB writes — read-only query on existing Trade table
  - Don't block same-direction trades on same market

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Risk management logic requires careful query construction and state machine understanding

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2-6)
  - **Blocks**: Task 6 (test)
  - **Blocked By**: None

  **References**:
  - `backend/core/risk_manager.py:450-477` — `_has_unsettled_trade()` pattern (query structure, nullcontext pattern, owns_db pattern)
  - `backend/models/database.py` — Trade model fields: `market_ticker`, `direction`, `settled`
  - `backend/core/risk_manager.py:27-30` — `RiskDecision` dataclass pattern for error types
  - `backend/monitoring/hft_metrics.py` — `record_signal()` and metric naming conventions

  **Acceptance Criteria**:
  - [ ] `risk_manager.py` has `SideLockError` class defined
  - [ ] `check_side_lock()` method exists and queries correctly
  - [ ] `validate_trade()` calls `check_side_lock()` before allowing trade
  - [ ] `increment_risk_rejection(strategy="...", reason="side_lock")` called on rejection
  - [ ] `ruff format backend/core/risk_manager.py` passes

  **QA Scenarios**:
  ```
  Scenario: Side lock blocks opposing direction
    Tool: Bash
    Preconditions: Open trade on market "BTC-UP" with direction="up" in DB
    Steps:
      1. Import RiskManager and get_db_session
      2. rm = RiskManager(); db = next(get_db_session())
      3. Call rm.check_side_lock("BTC-UP", "down", db=db)
    Expected Result: Raises SideLockError with message containing "Side lock" and "up" and "BTC-UP"
    Evidence: .sisyphus/evidence/task-1-side-lock-opposing.pdf

  Scenario: Same direction is allowed
    Tool: Bash
    Preconditions: Open trade on market "BTC-UP" with direction="up" in DB
    Steps:
      1. rm = RiskManager(); db = next(get_db_session())
      2. Call rm.check_side_lock("BTC-UP", "up", db=db)
    Expected Result: Returns None (no exception)
    Evidence: .sisyphus/evidence/task-1-side-lock-same-dir.pdf
  ```

  **Commit**: YES
  - Message: `feat(risk): add SideLockError and check_side_lock() to prevent self-hedging`
  - Files: `backend/core/risk_manager.py`
  - Pre-commit: `pytest backend/tests/test_side_lock.py -v`

---

- [x] 2. **Add `EdgeFilterError` and `check_edge()` to RiskManager**

  **What to do**:
  - Add `EdgeFilterError` exception class at top of `risk_manager.py`
  - Add `MIN_EDGE_PP = 5.0` as class attribute on `RiskManager` (configurable via `settings.MIN_EDGE_PP`)
  - Add `check_edge(self, market_price: float, signal_win_rate: float, market_id: str, db=None)` method to `RiskManager`
  - Compute: `edge_pp = (signal_win_rate - market_price) * 100`
  - If `market_price < 0.30` AND `edge_pp < 10`: raise `EdgeFilterError`
  - If `edge_pp < MIN_EDGE_PP`: raise `EdgeFilterError`
  - Log rejection to `TradeAttempt` table with `{market_id, market_price, signal_win_rate, edge_pp}`
  - Call from `validate_trade()` before size adjustment

  **Must NOT do**:
  - Don't use market price as win probability (circular)
  - Don't block trades where edge_pp >= MIN_EDGE_PP

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Edge calculation logic requires careful probability math and audit-logging

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3-6)
  - **Blocks**: Task 10 (edge filter test)
  - **Blocked By**: None

  **References**:
  - `backend/core/risk_manager.py:27-30` — `RiskDecision` dataclass pattern
  - `backend/core/trade_attempts.py` — `TradeAttemptRecorder` for logging rejections
  - `backend/config.py` — `MIN_EDGE_PP` setting pattern
  - Audit data: 0–30¢ bucket has -9pp edge (auto-reject unless edge_pp > 10)

  **Acceptance Criteria**:
  - [ ] `EdgeFilterError` class defined
  - [ ] `check_edge()` computes edge correctly: `(signal_win_rate - market_price) * 100`
  - [ ] Auto-rejects market_price < 0.30 unless edge_pp > 10
  - [ ] Auto-rejects edge_pp < 5
  - [ ] Logs to `TradeAttempt` table
  - [ ] `ruff format backend/core/risk_manager.py` passes

  **QA Scenarios**:
  ```
  Scenario: Edge below minimum threshold rejected
    Tool: Bash
    Preconditions: None
    Steps:
      1. rm = RiskManager()
      2. Call rm.check_edge(market_price=0.50, signal_win_rate=0.52, market_id="TEST")
    Expected Result: Raises EdgeFilterError, edge_pp = (0.52-0.50)*100 = 2pp < 5pp minimum
    Evidence: .sisyphus/evidence/task-2-edge-low.pdf

  Scenario: Edge above minimum passes
    Tool: Bash
    Preconditions: None
    Steps:
      1. rm = RiskManager()
      2. Call rm.check_edge(market_price=0.50, signal_win_rate=0.58, market_id="TEST")
    Expected Result: Returns None (edge_pp = 8pp >= 5pp)
    Evidence: .sisyphus/evidence/task-2-edge-pass.pdf

  Scenario: Low-price market requires higher edge
    Tool: Bash
    Preconditions: None
    Steps:
      1. rm = RiskManager()
      2. Call rm.check_edge(market_price=0.25, signal_win_rate=0.30, market_id="TEST")
    Expected Result: Raises EdgeFilterError — market < 0.30 requires edge_pp > 10
    Evidence: .sisyphus/evidence/task-2-edge-low-price.pdf
  ```

  **Commit**: YES
  - Message: `feat(risk): add EdgeFilterError and check_edge() for pre-trade edge validation`
  - Files: `backend/core/risk_manager.py`
  - Pre-commit: `pytest backend/tests/test_edge_filter.py -v`

---

- [x] 3. **Add `MIN_EDGE_PP` config and wire `check_edge()` into `validate_trade()`**

  **What to do**:
  - Add `MIN_EDGE_PP: float = 5.0` to `backend/config.py` with env var `MIN_EDGE_PP`
  - Add to `.env.example`: `MIN_EDGE_PP=5.0`
  - Wire `check_edge()` call into `validate_trade()` — after direction check, before size adjustment
  - Pass `market_price` from `market_ticker` lookup or directly if available
  - Pass `signal_win_rate` from `strategy_name` calibration lookup
  - If `check_edge()` raises `EdgeFilterError` → return `RiskDecision(False, ...)` with adjusted_size=0

  **Must NOT do**:
  - Don't pass hardcoded values — use actual market price from DB lookup
  - Don't skip the edge check for any strategy

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Config wiring and integration touches multiple files

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1-2, 4-6)
  - **Blocks**: Task 10
  - **Blocked By**: Task 2 (needs check_edge method)

  **References**:
  - `backend/config.py` — pattern for adding new float config with env override
  - `.env.example` — where to add new env var
  - `backend/core/risk_manager.py:152-165` — `validate_trade()` signature and flow
  - `backend/strategies/btc_oracle.py:370` — `edge` is already computed here, can pass through

  **Acceptance Criteria**:
  - [ ] `MIN_EDGE_PP` in config.py with env var override
  - [ ] `.env.example` updated
  - [ ] `validate_trade()` calls `check_edge()` and handles `EdgeFilterError`
  - [ ] Test: market_price=0.25, signal_win_rate=0.30 → rejected
  - [ ] Test: market_price=0.50, signal_win_rate=0.58 → allowed

  **QA Scenarios**:
  ```
  Scenario: Edge filter integrated into validate_trade
    Tool: Bash
    Preconditions: Config has MIN_EDGE_PP=5.0
    Steps:
      1. rm = RiskManager()
      2. db = next(get_db_session())
      3. result = rm.validate_trade(size=10, current_exposure=0, bankroll=1000,
           confidence=0.8, market_ticker="TEST", db=db, strategy_name="btc_oracle",
           direction="up", market_price=0.50, signal_win_rate=0.52)
    Expected Result: result.allowed=False with "edge" in reason
    Evidence: .sisyphus/evidence/task-3-edge-integrated.pdf
  ```

  **Commit**: YES
  - Message: `feat(config): add MIN_EDGE_PP config and wire edge check into validate_trade`
  - Files: `backend/config.py`, `.env.example`, `backend/core/risk_manager.py`

---

- [x] 4. **Add `check_strategy_performance()` to circuit_breaker.py**

  **What to do**:
  - Add `check_strategy_performance(strategy_name: str, db=None) -> bool` to `CircuitBreaker` class
  - Query last 20 resolved trades for `strategy_name` where `trading_mode == effective_mode`
  - Compute: `win_rate = wins / total` over last 20 trades
  - Compute: `pnl / capital` over last 30 days
  - Return `False` (pause) if: `pnl/capital < 0.05 OR win_rate < 0.45`
  - Store pause state in `StrategyConfig` table (set `enabled=False` for strategy)
  - Log skip to `TradeAttempt` table

  **Must NOT do**:
  - Don't modify historical Trade rows
  - Don't auto-restart — manual `POST /api/admin/strategies/{name}/resume` required

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Performance tracking across trades requires careful SQL and state management

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1-3, 5-6)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `backend/core/circuit_breaker.py` — existing CircuitBreaker class
  - `backend/models/database.py` — StrategyConfig model, Trade model
  - `backend/core/strategy_performance_registry.py` — `StrategyPerformanceRegistry` for existing metrics
  - Audit thresholds: win_rate < 45% OR pnl/capital < 5% → pause

  **Acceptance Criteria**:
  - [ ] `check_strategy_performance()` method exists in circuit_breaker.py
  - [ ] Queries last 20 trades for win rate
  - [ ] Queries last 30 days for PnL/capital ratio
  - [ ] Returns False and disables strategy if thresholds breached
  - [ ] Logs to TradeAttempt

  **QA Scenarios**:
  ```
  Scenario: Strategy below win rate threshold paused
    Tool: Bash
    Preconditions: btc_oracle has 8W/12L (33% WR) in last 20 trades
    Steps:
      1. cb = CircuitBreaker("strategy_perf", ...)
      2. cb.check_strategy_performance("btc_oracle", db=db)
    Expected Result: Returns False, StrategyConfig.enabled set to False
    Evidence: .sisyphus/evidence/task-4-perf-pause.pdf
  ```

  **Commit**: YES
  - Message: `feat(circuit): add check_strategy_performance() for per-strategy circuit breaker`
  - Files: `backend/core/circuit_breaker.py`

---

- [x] 5. **Add `DISABLED_STRATEGIES` env-var and auto-pause logic for sports/politics**

  **What to do**:
  - Add `DISABLED_STRATEGIES: str = ""` to `backend/config.py` with env var `DISABLED_STRATEGIES`
  - Add to `.env.example`: `DISABLED_STRATEGIES=sports_scanner,politics_scanner`
  - Add `_paused_strategies: set[str]` set to `set(DISABLED_STRATEGIES.split(","))` minus empty strings
  - In `orchestrator.py` strategy dispatch loop: check if `strategy_name in _paused_strategies` → skip with log
  - Log skip reason to `TradeAttempt` with `reason="strategy_paused"`
  - Add admin API endpoint `POST /api/v1/admin/strategies/{name}/pause` to add to paused set
  - Add admin API endpoint `POST /api/v1/admin/strategies/{name}/resume` to remove from paused set

  **Must NOT do**:
  - Don't persist paused state across restarts — use in-memory set for session
  - Don't pause AGI orchestrator or btc_oracle

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: Simple config + set operations

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1-4, 6)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `backend/config.py` — setting pattern
  - `backend/core/orchestrator.py` — strategy dispatch loop
  - `backend/api/agi_routes.py` — admin endpoint pattern
  - Audit: sports and politics have negative expectancy — pause immediately

  **Acceptance Criteria**:
  - [ ] `DISABLED_STRATEGIES` in config.py
  - [ ] Strategy dispatch skips paused strategies
  - [ ] Pause/resume admin endpoints work
  - [ ] Sports/politics strategies skipped in next cycle

  **QA Scenarios**:
  ```
  Scenario: Paused strategy skipped in orchestrator
    Tool: Bash
    Preconditions: DISABLED_STRATEGIES="sports_scanner" in env
    Steps:
      1. Load config, check "sports_scanner" in _paused_strategies
      2. Run orchestrator cycle
    Expected Result: sports_scanner skipped, log entry "strategy_paused"
    Evidence: .sisyphus/evidence/task-5-paused-skip.pdf
  ```

  **Commit**: YES
  - Message: `feat(config): add DISABLED_STRATEGIES env-var for immediate strategy pause`
  - Files: `backend/config.py`, `.env.example`, `backend/core/orchestrator.py`

---

- [x] 6. **Test: `test_side_lock.py` — RED phase (must FAIL before side lock impl)**

  **What to do**:
  - Create `backend/tests/test_side_lock.py`
  - Test: open YES trade on market M → new NO signal on M → `SideLockError` raised
  - Test: open YES trade on market M → new YES signal on M → allowed (no exception)
  - Test: no open trade on market M → any signal → allowed
  - Mock DB with in-memory SQLite
  - Must use `pytest` fixtures

  **Must NOT do**:
  - Don't write passing test — this is RED phase (test must fail until T1 is implemented)

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: TDD test — must correctly define expected behavior

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1-5)
  - **Blocks**: None
  - **Blocked By**: Task 1 (must exist before test can pass)

  **References**:
  - `backend/tests/conftest.py` — existing fixtures
  - `backend/tests/test_strategy_executor.py` — Trade creation pattern for mocking
  - `backend/core/risk_manager.py:450-477` — `_has_unsettled_trade` query pattern

  **Acceptance Criteria**:
  - [ ] `backend/tests/test_side_lock.py` created
  - [ ] Test "opposing direction blocked" FAILS before T1 implementation
  - [ ] Test "same direction allowed" passes (no side lock yet)
  - [ ] Test "no open trade allowed" passes

  **QA Scenarios**:
  ```
  Scenario: Test suite runs and fails as expected
    Tool: Bash
    Preconditions: T1 not yet implemented
    Steps:
      1. pytest backend/tests/test_side_lock.py -v
    Expected Result: Test "opposing_direction_blocked" FAILS with AttributeError or similar
    Evidence: .sisyphus/evidence/task-6-red-fail.pdf
  ```

  **Commit**: YES
  - Message: `test(risk): add test_side_lock.py RED phase test for side lock feature`
  - Files: `backend/tests/test_side_lock.py`

---

- [x] 7. **Add `get_bucket_win_rate()` to calibration.py**

  **What to do**:
  - Extend `backend/core/calibration.py` with new methods
  - Add `BUCKETS = [(0,10),(10,20),(20,30),(30,40),(40,50),(50,60),(60,70),(70,80),(80,90),(90,100)]`
  - Add `_price_to_bucket(price: float) -> tuple[float, float]` helper
  - Add `get_bucket_win_rate(price: float, strategy: str, lookback: int = 200) -> Optional[float]`
    - Query Trade table: `strategy == strategy AND settled == True AND exit_price IS NOT None` last `lookback` rows
    - Find bucket for entry price, compute `wins / total` for that bucket
    - Returns `None` if < 10 samples
  - Add `get_bucket_sample_size(price: float, strategy: str) -> int`

  **Must NOT do**:
  - Don't compute win rate from market_price — use realized Trade outcomes only
  - Don't return fake data — return `None` if insufficient samples

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Calibration math and SQL aggregation

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 8-11)
  - **Blocks**: Tasks 9, 11
  - **Blocked By**: Tasks 1-3 (RiskManager base)

  **References**:
  - `backend/core/calibration.py:1-105` — existing CalibrationEngine pattern
  - `backend/models/database.py` — Trade model: `strategy`, `direction`, `settled`, `pnl`
  - `backend/db/utils.py` — `get_db_session` pattern
  - Audit bucket data: 45-50¢ → 68.3% WR, 50-55¢ → 85.6% WR (confirming signal is real)

  **Acceptance Criteria**:
  - [ ] `get_bucket_win_rate(0.47, "btc_oracle")` returns ~0.683 if enough samples
  - [ ] Returns `None` if < 10 samples in bucket
  - [ ] `_price_to_bucket(0.47)` returns `(40, 50)`
  - [ ] `ruff format backend/core/calibration.py` passes

  **QA Scenarios**:
  ```
  Scenario: Bucket win rate from historical trades
    Tool: Bash
    Preconditions: DB has 50 settled btc_oracle trades in 45-50¢ bucket, 40 wins
    Steps:
      1. from backend.core.calibration import get_bucket_win_rate
      2. rate = get_bucket_win_rate(0.47, "btc_oracle", lookback=200)
    Expected Result: 0.80 (40/50)
    Evidence: .sisyphus/evidence/task-7-bucket-win-rate.pdf

  Scenario: Insufficient samples returns None
    Tool: Bash
    Preconditions: DB has 5 trades in bucket
    Steps:
      1. rate = get_bucket_win_rate(0.47, "btc_oracle")
    Expected Result: None (not enough samples)
    Evidence: .sisyphus/evidence/task-7-bucket-insufficient.pdf
  ```

  **Commit**: YES
  - Message: `feat(calibration): add get_bucket_win_rate() with per-price-bucket realized win rates`
  - Files: `backend/core/calibration.py`
  - Pre-commit: `pytest backend/tests/test_calibration.py -v`

---

- [x] 8. **Add `kelly_fraction()` with Quarter-Kelly to calibration.py**

  **What to do**:
  - Add `kelly_fraction(realized_win_rate: float, market_price: float) -> float`
  - Compute: if `realized_win_rate <= market_price` → return 0.0 (no edge)
  - `edge = realized_win_rate - market_price`
  - `q = 1 - realized_win_rate`
  - `kelly = edge / q` (standard Kelly)
  - `n = _bucket_sample_size(market_price)`
  - `multiplier = 0.25 if n < 500 else 0.5` (ramp from 0.25x to 0.5x Kelly)
  - `return kelly * multiplier`
  - Cap at 0.02 (2% of bankroll hard cap per trade)

  **Must NOT do**:
  - Don't use market_price as win probability — use `realized_win_rate`
  - Don't return Kelly > 0.5 (capped at Quarter-Kelly)

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Kelly formula math + edge case handling

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7, 9-11)
  - **Blocks**: Task 9
  - **Blocked By**: Tasks 1-3

  **References**:
  - `backend/core/calibration.py:1-105` — existing pattern
  - Kelly formula: K = (p*W - q*L) / W where p=win_prob, q=1-p, W=win_size, L=loss_size
  - Since binary option (win=1, loss=0): K = (p - q)/q = (p - (1-p))/(1-p) = (2p-1)/(1-p)
  - Simplified for binary: kelly = (win_rate - loss_rate) / loss_rate where loss_rate = 1 - win_rate
  - Audit: 17 trades >$20 had 100% WR — larger positions were always winners

  **Acceptance Criteria**:
  - [ ] `kelly_fraction(0.70, 0.50)` returns > 0 (edge detected)
  - [ ] `kelly_fraction(0.40, 0.50)` returns 0 (no edge)
  - [ ] `kelly_fraction(0.86, 0.52)` returns Quarter-Kelly scaled result
  - [ ] Result capped at 0.02 (2% of bankroll)
  - [ ] `ruff format backend/core/calibration.py` passes

  **QA Scenarios**:
  ```
  Scenario: Kelly with positive edge
    Tool: Bash
    Preconditions: 500+ samples in bucket
    Steps:
      1. from backend.core.calibration import kelly_fraction
      2. frac = kelly_fraction(0.70, 0.50)
    Expected Result: frac > 0 (edge = 0.20, q = 0.30, kelly = 0.667, quarter = 0.333)
    Evidence: .sisyphus/evidence/task-8-kelly-positive.pdf

  Scenario: No edge returns zero
    Tool: Bash
    Preconditions: 500+ samples in bucket
    Steps:
      1. frac = kelly_fraction(0.40, 0.50)
    Expected Result: 0.0 (win_rate < market_price)
    Evidence: .sisyphus/evidence/task-8-kelly-zero.pdf

  Scenario: Capped at 2%
    Tool: Bash
    Preconditions: 500+ samples, huge edge
    Steps:
      1. frac = kelly_fraction(0.95, 0.50)
    Expected Result: min(kelly*0.5, 0.02) — capped at 0.02
    Evidence: .sisyphus/evidence/task-8-kelly-capped.pdf
  ```

  **Commit**: YES
  - Message: `feat(calibration): add kelly_fraction() with Quarter-Kelly and realized win rates`
  - Files: `backend/core/calibration.py`
  - Pre-commit: `pytest backend/tests/test_calibration.py -v`

---

- [x] 9. **Replace btc_oracle static Kelly with `calibration.kelly_fraction()`**

  **What to do**:
  - In `btc_oracle.py`, replace `calculate_dynamic_size()` usage with `calibration.kelly_fraction()`
  - After `edge` is computed (line 370 or around), get bucket win rate:
    ```python
    from backend.core.calibration import get_bucket_win_rate, kelly_fraction
    win_rate = get_bucket_win_rate(market_mid, "btc_oracle")
    if win_rate is None and market_mid < 0.40:
        # Insufficient data + low price = skip or minimum size
        suggested_size = params.get("min_position_usd", self.default_params["min_position_usd"])
    elif win_rate is not None:
        kelly = kelly_fraction(win_rate, market_mid)
        suggested_size = min(bankroll * kelly, bankroll * 0.02)
    ```
  - Keep fallback to `calculate_dynamic_size()` for when calibration returns None
  - Keep the 2% hard cap from Kelly sizing

  **Must NOT do**:
  - Don't remove the edge filtering — if `edge <= 0`, still skip
  - Don't use market_price as win rate in Kelly calculation

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Strategy modification requires understanding execution path

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7-8, 10-11)
  - **Blocks**: None
  - **Blocked By**: Tasks 7, 8

  **References**:
  - `backend/strategies/btc_oracle.py:400-406` — current `calculate_dynamic_size()` call
  - `backend/strategies/btc_oracle.py:298-545` — `run_cycle()` full context
  - `backend/core/calibration.py` — new `kelly_fraction()` method
  - `backend/config.py` — `INITIAL_BANKROLL` for bankroll reference

  **Acceptance Criteria**:
  - [ ] `btc_oracle.py` imports `get_bucket_win_rate` and `kelly_fraction` from calibration
  - [ ] Entry in 0–30¢ bucket with `win_rate=None` → fallback to min size or skip
  - [ ] Entry in 45–55¢ bucket with `win_rate=0.68–0.86` → Kelly-sized position
  - [ ] `ruff format backend/strategies/btc_oracle.py` passes

  **QA Scenarios**:
  ```
  Scenario: Bucket-calibrated sizing used in btc_oracle
    Tool: Bash
    Preconditions: btc_oracle run_cycle with market_mid=0.52, win_rate=0.856
    Steps:
      1. Run btc_oracle.run_cycle() in paper mode
      2. Check size of resulting decision
    Expected Result: size = min(bankroll * kelly_fraction(0.856, 0.52), bankroll * 0.02)
    Evidence: .sisyphus/evidence/task-9-kelly-sizing.pdf

  Scenario: Fallback when calibration has insufficient data
    Tool: Bash
    Preconditions: btc_oracle with market_mid=0.35, win_rate=None (too few samples)
    Steps:
      1. Run btc_oracle.run_cycle()
    Expected Result: Falls back to min_position_usd or skips
    Evidence: .sisyphus/evidence/task-9-kelly-fallback.pdf
  ```

  **Commit**: YES
  - Message: `feat(btc_oracle): replace static Kelly with bucket-calibrated kelly_fraction()`
  - Files: `backend/strategies/btc_oracle.py`
  - Pre-commit: `pytest backend/tests/test_btc_oracle.py -v`

---

- [x] 10. **Test: `test_edge_filter.py` — RED phase (must FAIL before T2-T3 impl)**

  **What to do**:
  - Create `backend/tests/test_edge_filter.py`
  - Test: edge_pp=2 < MIN_EDGE_PP=5 → `EdgeFilterError` raised
  - Test: edge_pp=8 > MIN_EDGE_PP=5 → allowed
  - Test: market_price < 0.30 with edge_pp=8 (needs >10) → `EdgeFilterError`
  - Test: market_price < 0.30 with edge_pp=12 → allowed
  - Mock `RiskManager` and call `check_edge()` directly

  **Must NOT do**:
  - Don't write passing test — RED phase (test must fail until T2-T3 done)

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: TDD test defines expected behavior

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7-9, 11)
  - **Blocks**: None
  - **Blocked By**: Tasks 2, 3

  **References**:
  - `backend/tests/conftest.py` — fixtures
  - `backend/core/risk_manager.py` — `check_edge()` signature
  - Audit data: 0–30¢ bucket has -9pp edge

  **Acceptance Criteria**:
  - [ ] Test file created
  - [ ] Test "edge below minimum" FAILS before T2-T3
  - [ ] Test "low price high edge" FAILS before T3

  **QA Scenarios**:
  ```
  Scenario: Test runs and fails as expected
    Tool: Bash
    Preconditions: T2-T3 not implemented
    Steps:
      1. pytest backend/tests/test_edge_filter.py -v
    Expected Result: FAILS with AttributeError or missing method
    Evidence: .sisyphus/evidence/task-10-red-fail.pdf
  ```

  **Commit**: YES
  - Message: `test(risk): add test_edge_filter.py RED phase test`
  - Files: `backend/tests/test_edge_filter.py`

---

- [x] 11. **Test: `test_bucket_kelly.py` — RED phase (must FAIL before T7-T8 impl)**

  **What to do**:
  - Create `backend/tests/test_bucket_kelly.py`
  - Test: `kelly_fraction(0.70, 0.50)` → positive value
  - Test: `kelly_fraction(0.40, 0.50)` → 0.0
  - Test: `kelly_fraction(0.95, 0.50)` → capped at 0.02
  - Test: `get_bucket_win_rate()` → returns None for insufficient samples
  - Test: `get_bucket_win_rate()` → returns correct rate for sufficient samples

  **Must NOT do**:
  - Don't write passing test — RED phase

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: TDD test for calibration math

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7-10)
  - **Blocks**: None
  - **Blocked By**: Tasks 7, 8

  **References**:
  - `backend/core/calibration.py` — new methods
  - `backend/tests/test_calibration.py` — existing test pattern

  **Acceptance Criteria**:
  - [ ] Test file created
  - [ ] All tests FAIL before T7-T8 implementation

  **QA Scenarios**:
  ```
  Scenario: Test runs and fails
    Tool: Bash
    Preconditions: T7-T8 not implemented
    Steps:
      1. pytest backend/tests/test_bucket_kelly.py -v
    Expected Result: FAILS with missing method
    Evidence: .sisyphus/evidence/task-11-red-fail.pdf
  ```

  **Commit**: YES
  - Message: `test(calibration): add test_bucket_kelly.py RED phase test`
  - Files: `backend/tests/test_bucket_kelly.py`

---

- [x] 12. **Add `TokenBucketRateLimiter` class in order_executor.py**

  **What to do**:
  - Create `TokenBucketRateLimiter` class in `backend/strategies/order_executor.py`
  - Per-market rate limit: `max_per_market_per_10s=1` (configurable)
  - Global rate limit: `global_max_per_second=3` (configurable)
  - `acquire(market_id: str) -> None`: blocks if rate limit exceeded
    - Check `_market_timestamps[market_id]` — if last order within 10s → raise `RateLimitError`
    - Check `_global_timestamps` — if >3 orders in last 1s → raise `RateLimitError`
    - On success: append current timestamp to both
    - Use sliding window cleanup: remove timestamps older than window
  - `RateLimitError` exception class defined at module level
  - Make configurable via `settings.ORDER_RATE_LIMIT_PER_MARKET` and `settings.ORDER_RATE_LIMIT_GLOBAL`

  **Must NOT do**:
  - Don't add to `__init__.py` exports — keep in order_executor.py
  - Don't make blocking sleep — just raise and let caller retry

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Concurrency-safe rate limiting with sliding window

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 13-16)
  - **Blocks**: Tasks 14, 15
  - **Blocked By**: Tasks 1-3

  **References**:
  - `backend/strategies/order_executor.py:1-423` — existing file structure
  - `backend/config.py` — settings pattern
  - Audit: 281 trades in same-second batches — need 1 per market per 10s

  **Acceptance Criteria**:
  - [ ] `TokenBucketRateLimiter` class with `acquire()` method
  - [ ] Per-market: 2 orders to same market within 10s → RateLimitError
  - [ ] Global: 4 orders in 1s → RateLimitError
  - [ ] Sliding window cleanup works correctly
  - [ ] `ruff format backend/strategies/order_executor.py` passes

  **QA Scenarios**:
  ```
  Scenario: Per-market rate limit enforced
    Tool: Bash
    Preconditions: No prior orders
    Steps:
      1. rbl = TokenBucketRateLimiter()
      2. rbl.acquire("BTC-UP")  # first — allowed
      3. rbl.acquire("BTC-UP")  # second within 10s — RateLimitError
    Expected Result: Second call raises RateLimitError
    Evidence: .sisyphus/evidence/task-12-rate-limit-market.pdf

  Scenario: Global rate limit enforced
    Tool: Bash
    Preconditions: 3 orders already placed this second
    Steps:
      1. rbl = TokenBucketRateLimiter()
      2. for i in range(3): rbl.acquire(f"MARKET-{i}")  # 3 allowed
      3. rbl.acquire("MARKET-4")  # 4th in same second — RateLimitError
    Expected Result: 4th call raises RateLimitError
    Evidence: .sisyphus/evidence/task-12-rate-limit-global.pdf
  ```

  **Commit**: YES
  - Message: `feat(rate_limit): add TokenBucketRateLimiter for per-market and global rate limits`
  - Files: `backend/strategies/order_executor.py`
  - Pre-commit: `pytest backend/tests/test_token_bucket.py -v`

---

- [x] 13. **Add maker-first execution: limit order → 15s wait → taker escalation**

  **What to do**:
  - In `polymarket_clob.py`, add `place_maker_first_order()` method
  - `place_maker_first_order(token_id, side, size, edge_pp, timeout=15)`:
    - If `edge_pp > 20` (high confidence): immediately use `place_limit_order()` as taker (skip maker)
    - Otherwise: post limit at `best_bid + 0.001` (1 tick improvement)
    - Wait up to `timeout` seconds for fill
    - If not filled: cancel limit order, escalate to `place_market_order()` (taker)
    - Return `OrderResult` with `fill_price` and `maker_filled=True/False`
  - Add `record_maker_fill_rate(market_id: str, filled: bool)` to HFT metrics
  - Update Prometheus metric `maker_fill_rate` (counter, labeled by `market_id`)
  - Wire `edge_pp` parameter from `btc_oracle` decision into `place_maker_first_order()`

  **Must NOT do**:
  - Don't block indefinitely — use `asyncio.wait_for()` with timeout
  - Don't call `place_market_order()` directly — use the same `place_limit_order()` flow

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Async timeout handling and CLOB order management

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 12, 14-16)
  - **Blocks**: Task 16
  - **Blocked By**: Tasks 1-3

  **References**:
  - `backend/data/polymarket_clob.py:504-646` — `place_limit_order()` pattern
  - `backend/data/polymarket_clob.py:648` — `cancel_order()` method
  - `backend/monitoring/hft_metrics.py` — `record_execution()` pattern for metrics
  - Audit: 0.7% maker rate → target >60%

  **Acceptance Criteria**:
  - [ ] `place_maker_first_order()` method exists
  - [ ] High edge_pp > 20 → taker fill immediately
  - [ ] Normal edge_pp → limit order, wait 15s, escalate if not filled
  - [ ] `maker_fill_rate` Prometheus counter incremented
  - [ ] `ruff format backend/data/polymarket_clob.py` passes

  **QA Scenarios**:
  ```
  Scenario: High edge trades immediately as taker
    Tool: Bash
    Preconditions: edge_pp=25
    Steps:
      1. clob = PolymarketCLOB(mode="paper")
      2. result = clob.place_maker_first_order("TOKEN", "BUY", 10, edge_pp=25)
    Expected Result: result.success=True, result.maker_filled=False (taker)
    Evidence: .sisyphus/evidence/task-13-high-edge-taker.pdf

  Scenario: Normal edge posts limit and waits
    Tool: Bash
    Preconditions: edge_pp=8, paper mode
    Steps:
      1. clob = PolymarketCLOB(mode="paper")
      2. result = clob.place_maker_first_order("TOKEN", "BUY", 10, edge_pp=8, timeout=5)
    Expected Result: result.success=True, result.maker_filled=True (paper always fills)
    Evidence: .sisyphus/evidence/task-13-normal-edge-maker.pdf
  ```

  **Commit**: YES
  - Message: `feat(execution): add maker-first order execution with 15s limit-then-taker escalation`
  - Files: `backend/data/polymarket_clob.py`
  - Pre-commit: `pytest backend/tests/test_maker_first.py -v`

---

- [x] 14. **Integrate TokenBucketRateLimiter into strategy_executor.py**

  **What to do**:
  - In `strategy_executor.py`, add `TokenBucketRateLimiter` as module-level singleton
  - Before calling `clob.place_maker_first_order()`, call `rate_limiter.acquire(market_ticker)`
  - On `RateLimitError`: log skip to TradeAttempt, return `TradeResult(success=False, error="rate_limited")`
  - Add `rate_limiter` to `StrategyExecutor.__init__()` as instance variable
  - Make `max_per_market_per_10s` and `global_max_per_second` configurable via `settings`

  **Must NOT do**:
  - Don't block the trade if rate limited — just skip with proper logging
  - Don't instantiate new rate limiter per trade

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Integration across strategy_executor, order_executor, and polymarket_clob

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 12-13, 15-16)
  - **Blocks**: Task 15
  - **Blocked By**: Tasks 12, 13

  **References**:
  - `backend/core/strategy_executor.py` — existing `execute_decisions()` flow
  - `backend/core/risk_manager.py:152-165` — `validate_trade()` pattern (called before this)
  - `backend/strategies/order_executor.py` — `TokenBucketRateLimiter` class

  **Acceptance Criteria**:
  - [ ] `TokenBucketRateLimiter` instantiated as module-level singleton
  - [ ] `rate_limiter.acquire()` called before `place_maker_first_order()`
  - [ ] `RateLimitError` → trade skipped with TradeAttempt log
  - [ ] `ruff format backend/core/strategy_executor.py` passes

  **QA Scenarios**:
  ```
  Scenario: Rate-limited trade skipped
    Tool: Bash
    Preconditions: TokenBucketRateLimiter already has order for "BTC-UP" 2s ago
    Steps:
      1. executor = StrategyExecutor(mode="paper")
      2. executor.execute_decisions([decision_for_BTC_UP], db=db)
    Expected Result: TradeAttempt logged with reason="rate_limited", no order placed
    Evidence: .sisyphus/evidence/task-14-rate-limited-skip.pdf

  Scenario: Non-rate-limited trade succeeds
    Tool: Bash
    Preconditions: Fresh rate limiter
    Steps:
      1. executor = StrategyExecutor(mode="paper")
      2. executor.execute_decisions([decision_for_BTC_UP], db=db)
    Expected Result: Order placed successfully
    Evidence: .sisyphus/evidence/task-14-trade-succeeds.pdf
  ```

  **Commit**: YES
  - Message: `feat(execution): integrate TokenBucketRateLimiter into strategy_executor`
  - Files: `backend/core/strategy_executor.py`
  - Pre-commit: `pytest backend/tests/test_strategy_executor.py -v`

---

- [x] 15. **Test: `test_token_bucket.py` — RED phase (must FAIL before T12 impl)**

  **What to do**:
  - Create `backend/tests/test_token_bucket.py`
  - Test: 2 orders to same market within 10s → `RateLimitError`
  - Test: 4 orders globally within 1s → `RateLimitError`
  - Test: 1 order per market, spaced 10s apart → all succeed
  - Test: sliding window cleanup (orders older than window don't count)

  **Must NOT do**:
  - Don't write passing test — RED phase

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: TDD test for rate limiter

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 12-14, 16)
  - **Blocks**: None
  - **Blocked By**: Task 12

  **References**:
  - `backend/strategies/order_executor.py` — `TokenBucketRateLimiter` will be at module level
  - `backend/tests/conftest.py` — fixture pattern

  **Acceptance Criteria**:
  - [ ] Test file created
  - [ ] All tests FAIL before T12 implementation

  **QA Scenarios**:
  ```
  Scenario: Test runs and fails
    Tool: Bash
    Preconditions: T12 not implemented
    Steps:
      1. pytest backend/tests/test_token_bucket.py -v
    Expected Result: FAILS with ImportError or missing class
    Evidence: .sisyphus/evidence/task-15-red-fail.pdf
  ```

  **Commit**: YES
  - Message: `test(rate_limit): add test_token_bucket.py RED phase test`
  - Files: `backend/tests/test_token_bucket.py`

---

- [x] 16. **Test: `test_maker_first.py` — RED phase (must FAIL before T13 impl)**

  **What to do**:
  - Create `backend/tests/test_maker_first.py`
  - Test: edge_pp > 20 → taker fill (no wait)
  - Test: edge_pp < 20 → limit order placed, then filled
  - Test: limit order not filled within timeout → escalated to taker
  - Test: `maker_fill_rate` counter incremented

  **Must NOT do**:
  - Don't write passing test — RED phase

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: TDD test for maker-first execution

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 12-15)
  - **Blocks**: None
  - **Blocked By**: Task 13

  **References**:
  - `backend/data/polymarket_clob.py` — `place_maker_first_order()` signature
  - `backend/tests/test_polymarket_clob.py` — existing CLOB test patterns

  **Acceptance Criteria**:
  - [ ] Test file created
  - [ ] All tests FAIL before T13 implementation

  **QA Scenarios**:
  ```
  Scenario: Test runs and fails
    Tool: Bash
    Preconditions: T13 not implemented
    Steps:
      1. pytest backend/tests/test_maker_first.py -v
    Expected Result: FAILS with missing method
    Evidence: .sisyphus/evidence/task-16-red-fail.pdf
  ```

  **Commit**: YES
  - Message: `test(execution): add test_maker_first.py RED phase test`
  - Files: `backend/tests/test_maker_first.py`

---

- [x] 17. **Create `position_monitor.py` with stale-position scan logic**

  **What to do**:
  - Create `backend/core/position_monitor.py`
  - `async def scan_stale_positions(db=None) -> list[dict]`:
    - Query all open trades: `Trade.settled == False`
    - For each trade:
      - Calculate age: `(now - Trade.created_at).total_seconds() / 3600` (hours)
      - Get current market price via `polymarket_clob.get_mid_price(token_id)`
      - If `age > 48 OR market_closes_within_2h`:
        - Re-run signal logic (call btc_oracle signal computation for that market)
        - If `edge_pp < -5 OR adverse_price_drift > 10pp`: flag for exit
        - If market illiquid (spread > 10pp): accept market price and exit
        - Else: post limit sell at current mid
    - Return list of `{trade_id, market_id, action, reason, price, size}`
  - `async def close_stale_positions(flags: list[dict], execute: bool = False)`:
    - If `execute=False`: dry run, return what would happen
    - If `execute=True`: actually place exit orders
    - Update Trade with `exit_reason` and `exit_price` after execution

  **Must NOT do**:
  - Don't mutate historical Trade rows
  - Don't close positions without checking edge
  - Don't use market price as exit price — always verify liquidity first

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Complex async logic with market data + order management

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 18-21)
  - **Blocks**: Task 20
  - **Blocked By**: Tasks 7-9

  **References**:
  - `backend/data/polymarket_clob.py:504` — `get_mid_price()` and `place_limit_order()` usage
  - `backend/strategies/btc_oracle.py:298-545` — signal computation for stale re-check
  - `backend/core/settlement.py` — exit_reason pattern
  - Audit: 81 positions, $1,782 locked, some > 48h old

  **Acceptance Criteria**:
  - [ ] `scan_stale_positions()` returns list of dicts with action/reason
  - [ ] Positions > 48h OR near close flagged for review
  - [ ] `close_stale_positions()` dry-run returns what would execute
  - [ ] `close_stale_positions(execute=True)` places exit orders
  - [ ] `ruff format backend/core/position_monitor.py` passes

  **QA Scenarios**:
  ```
  Scenario: Stale position identified
    Tool: Bash
    Preconditions: Open trade on "BTC-UP" created 50h ago
    Steps:
      1. from backend.core.position_monitor import scan_stale_positions
      2. positions = await scan_stale_positions(db=db)
    Expected Result: Position appears in list with action="review" and age=50
    Evidence: .sisyphus/evidence/task-17-stale-identified.pdf

  Scenario: Recent position not flagged
    Tool: Bash
    Preconditions: Open trade created 2h ago
    Steps:
      1. positions = await scan_stale_positions(db=db)
    Expected Result: Position NOT in list (age < 48h)
    Evidence: .sisyphus/evidence/task-17-recent-not-flagged.pdf
  ```

  **Commit**: YES
  - Message: `feat(monitor): add position_monitor.py for stale position detection and exit`
  - Files: `backend/core/position_monitor.py`
  - Pre-commit: `pytest backend/tests/test_position_monitor.py -v`

---

- [x] 18. **Add APScheduler job for position_monitor in scheduler.py**

  **What to do**:
  - In `backend/core/scheduler.py`, add `position_monitor` job:
    ```python
    scheduler.add_job(
        'backend.core.scheduling_strategies.run_position_monitor_job',
        'interval',
        minutes=30,
        id='position_monitor',
        replace_existing=True,
        misfire_grace_time=300,
    )
    ```
  - In `backend/core/scheduling_strategies.py`, add `run_position_monitor_job()`:
    - Call `position_monitor.scan_stale_positions()` with fresh DB session
    - If `AGI_AUTO_CLOSE_POSITIONS` env var enabled: call `close_stale_positions(flags, execute=True)`
    - Log results to `TradeAttempt` with `reason="stale_position_scan"`
  - Add config: `AGI_AUTO_CLOSE_POSITIONS: bool = False` to `backend/config.py`

  **Must NOT do**:
  - Don't auto-close by default — dry-run only unless explicitly enabled
  - Don't hold DB session across async calls

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: Standard APScheduler job pattern

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 17, 19-21)
  - **Blocks**: None
  - **Blocked By**: Task 17

  **References**:
  - `backend/core/scheduler.py` — existing job registration pattern
  - `backend/core/scheduling_strategies.py` — job implementation pattern
  - `backend/config.py` — feature flag pattern

  **Acceptance Criteria**:
  - [ ] `position_monitor` job registered in APScheduler
  - [ ] Job runs every 30 minutes
  - [ ] `run_position_monitor_job()` handles session correctly
  - [ ] Auto-close only if `AGI_AUTO_CLOSE_POSITIONS=true`

  **QA Scenarios**:
  ```
  Scenario: Job registered in scheduler
    Tool: Bash
    Preconditions: Scheduler initialized
    Steps:
      1. scheduler = get_scheduler()
      2. job = scheduler.get_job('position_monitor')
    Expected Result: job is not None, interval=30 minutes
    Evidence: .sisyphus/evidence/task-18-job-registered.pdf
  ```

  **Commit**: YES
  - Message: `feat(scheduler): add position_monitor APScheduler job every 30 minutes`
  - Files: `backend/core/scheduler.py`, `backend/core/scheduling_strategies.py`, `backend/config.py`

---

- [x] 19. **Create `scripts/close_stale_positions.py` with --dry-run + --execute**

  **What to do**:
  - Create `scripts/close_stale_positions.py` as standalone script
  - `--dry-run` (default): queries all 81 pending positions, prints table:
    ```
    trade_id | market_id | age_hours | current_price | entry_price | pnl_est | action
    ```
  - `--execute`: actually places exit orders (requires `--force` confirmation)
  - `--hours N`: flag positions older than N hours (default: 48)
  - Uses `backend.db.utils.get_db_session()` and `polymarket_clob`
  - Prints summary: "Would close X positions, estimated recovery: $Y"
  - With `--execute --force`: "Closed X positions, actual recovery: $Y"

  **Must NOT do**:
  - Don't execute without explicit `--force` flag
  - Don't close positions with positive edge (hold them)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: Operational script for capital recovery

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 17-18, 20-21)
  - **Blocks**: None
  - **Blocked By**: Task 17

  **References**:
  - `scripts/` directory structure — existing script patterns
  - `backend/core/position_monitor.py` — reuse `scan_stale_positions()` logic
  - `backend/data/polymarket_clob.py` — order placement
  - Audit: $1,782 in 81 positions, some likely recoverable

  **Acceptance Criteria**:
  - [ ] `python scripts/close_stale_positions.py` shows dry-run table
  - [ ] `python scripts/close_stale_positions.py --hours 24` shows positions > 24h
  - [ ] `python scripts/close_stale_positions.py --execute --force` executes closes
  - [ ] Script handles errors gracefully (missing market, order rejection)

  **QA Scenarios**:
  ```
  Scenario: Dry run outputs position table
    Tool: Bash
    Preconditions: 81 open positions in DB
    Steps:
      1. python scripts/close_stale_positions.py --hours 24
    Expected Result: Table with trade_id, market, age, prices, estimated action
    Evidence: .sisyphus/evidence/task-19-dry-run.pdf

  Scenario: Execute requires --force
    Tool: Bash
    Preconditions: Dry run shows positions
    Steps:
      1. python scripts/close_stale_positions.py --execute  # no --force
    Expected Result: "Use --force to execute" error message
    Evidence: .sisyphus/evidence/task-19-force-required.pdf
  ```

  **Commit**: YES
  - Message: `feat(capital): add scripts/close_stale_positions.py for stale position recovery`
  - Files: `scripts/close_stale_positions.py`

---

- [x] 20. **Test: `test_position_monitor.py` — RED phase (must FAIL before T17 impl)**

  **What to do**:
  - Create `backend/tests/test_position_monitor.py`
  - Test: position > 48h old → flagged as stale
  - Test: position < 48h old → not flagged
  - Test: near-market-close position flagged even if < 48h
  - Test: adverse drift > 10pp → exit recommended
  - Mock `polymarket_clob.get_mid_price()` and `btc_oracle` signal computation

  **Must NOT do**:
  - Don't write passing test — RED phase

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: TDD test for position monitor

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 17-19, 21)
  - **Blocks**: None
  - **Blocked By**: Task 17

  **References**:
  - `backend/core/position_monitor.py` — will be new file
  - `backend/tests/conftest.py` — fixture pattern

  **Acceptance Criteria**:
  - [ ] Test file created
  - [ ] All tests FAIL before T17 implementation

  **QA Scenarios**:
  ```
  Scenario: Test runs and fails
    Tool: Bash
    Preconditions: T17 not implemented
    Steps:
      1. pytest backend/tests/test_position_monitor.py -v
    Expected Result: FAILS with ImportError
    Evidence: .sisyphus/evidence/task-20-red-fail.pdf
  ```

  **Commit**: YES
  - Message: `test(monitor): add test_position_monitor.py RED phase test`
  - Files: `backend/tests/test_position_monitor.py`

---

- [x] 21. **Integration test: `close_stale_positions.py` script end-to-end**
- [x] 23. **Add signal logging to `btc_oracle.py`**
- [x] 24. **Add calibration API with per-bucket breakdown endpoint**
- [x] 26. **Test: `test_calibration_api.py` — RED phase (must FAIL before T24 impl)**

  **What to do**:
  - Create `backend/tests/test_calibration_api.py`
  - Test: `GET /api/v1/calibration` returns 200
  - Test: response has `buckets` key
  - Test: each bucket has `win_rate`, `edge_pp`, `n`
  - Test: bucket with `edge_pp < 0` has `negative_edge: true`

  **Must NOT do**:
  - Don't write passing test — RED phase

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: TDD test for API endpoint

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with Tasks 22-25)
  - **Blocks**: None
  - **Blocked By**: Task 24

  **References**:
  - `backend/api/calibration_routes.py` — will be new file
  - `backend/tests/test_api.py` — existing API test patterns

  **Acceptance Criteria**:
  - [ ] Test file created
  - [ ] All tests FAIL before T24 implementation

  **QA Scenarios**:
  ```
  Scenario: Test runs and fails
    Tool: Bash
    Preconditions: T24 not implemented
    Steps:
      1. pytest backend/tests/test_calibration_api.py -v
    Expected Result: FAILS with 404
    Evidence: .sisyphus/evidence/task-26-red-fail.pdf
  ```

  **Commit**: YES
  - Message: `test(api): add test_calibration_api.py RED phase test`
  - Files: `backend/tests/test_calibration_api.py`

---

## Final Verification Wave

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
>
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**

- [x] F1. **Plan Compliance Audit** — `oracle`
  Must Have [18/18] | Must NOT Have [5/5] | Tasks [18/18] | VERDICT: APPROVE

- [x] F2. **Code Quality Review** — `unspecified-high`
  Ruff [PASS] | Tests [30 pass/0 fail] | Issues [0] | VERDICT: APPROVE

- [x] F3. **Real Manual QA** — `unspecified-high`
  Calibration API: 200 OK | close_stale_positions --help: PASS | All imports: PASS | VERDICT: APPROVE

- [x] F4. **Scope Fidelity Check** — `deep`
  Tasks [28/28 compliant] | Contamination [CLEAN] | Unaccounted [CLEAN] | VERDICT: APPROVE

---

## Commit Strategy

- **T1**: `feat(risk): add SideLockError and check_side_lock()`
- **T2**: `feat(risk): add EdgeFilterError and check_edge()`
- **T3**: `feat(config): wire MIN_EDGE_PP into validate_trade()`
- **T4**: `feat(circuit): add check_strategy_performance()`
- **T5**: `feat(config): add DISABLED_STRATEGIES for pause`
- **T6**: `test(risk): test_side_lock RED phase`
- **T7**: `feat(calibration): add get_bucket_win_rate()`
- **T8**: `feat(calibration): add kelly_fraction()`
- **T9**: `feat(btc_oracle): use bucket-calibrated Kelly`
- **T10**: `test(risk): test_edge_filter RED phase`
- **T11**: `test(calibration): test_bucket_kelly RED phase`
- **T12**: `feat(rate_limit): add TokenBucketRateLimiter`
- **T13**: `feat(execution): add maker-first order execution`
- **T14**: `feat(execution): integrate rate limiter into executor`
- **T15**: `test(rate_limit): test_token_bucket RED phase`
- **T16**: `test(execution): test_maker_first RED phase`
- **T17**: `feat(monitor): add position_monitor.py`
- **T18**: `feat(scheduler): add position_monitor APScheduler job`
- **T19**: `feat(capital): add close_stale_positions.py script`
- **T20**: `test(monitor): test_position_monitor RED phase`
- **T21**: `test(capital): integration test close_stale_positions`
- **T22**: `feat(models): add SignalLog table + migration`
- **T23**: `feat(btc_oracle): instrument signal logging`
- **T24**: `feat(api): add /api/v1/calibration with bucket breakdown`
- **T25**: `test(models): test_signal_log RED phase`
- **T26**: `test(api): test_calibration_api RED phase`

---

## Success Criteria

### Verification Commands
```bash
pytest backend/tests/test_side_lock.py -v        # PASS after T1
pytest backend/tests/test_edge_filter.py -v       # PASS after T3
pytest backend/tests/test_bucket_kelly.py -v     # PASS after T8
pytest backend/tests/test_token_bucket.py -v     # PASS after T12
pytest backend/tests/test_maker_first.py -v      # PASS after T13
pytest backend/tests/test_position_monitor.py -v # PASS after T17
pytest backend/tests/test_signal_log.py -v       # PASS after T23
pytest backend/tests/test_calibration_api.py -v # PASS after T24
ruff check backend/core/risk_manager.py
ruff check backend/core/calibration.py
ruff check backend/strategies/btc_oracle.py
ruff check backend/strategies/order_executor.py
ruff check backend/data/polymarket_clob.py
ruff check backend/core/position_monitor.py
alembic current  # should show single head
curl http://localhost:8102/api/v1/calibration  # bucket data
python scripts/close_stale_positions.py --dry-run  # position report
```

### Final Checklist
- [x] All 26 tasks complete
- [x] All F1-F4 reviews APPROVE
- [x] 0 new lint errors
- [x] All new tests PASS
- [x] Evidence files exist in `.sisyphus/evidence/`
- [x] PR ready to merge (if improvements are a PR, not direct to main)