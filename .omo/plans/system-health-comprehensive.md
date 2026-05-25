# System Health Comprehensive Plan — 100% Operational

## TL;DR

> **Goal**: Fix ALL blockers preventing trading + apply research-backed profitability enhancements (maker/taker dynamics, YES/NO asymmetry, execution speed, category-awareness).
> 
> **Deliverables**: 21 tasks, 7 waves, ~8 days estimated.
> 
> **Critical Path**: T1 (apply_profile startup) → T2 (confidence rescale) → T5/T6 (loss config) → T9 → T10 → T11 → T12 (scan interval) → T13 (NO bias) → T14 (HFT pipeline) → T15 (maker mode) → T19 (BotState race)
>
> **Root Cause**: 7 independent issues all blocking trades simultaneously. Each alone would reduce trading. Together they create 100% rejection rate.

---

## Context

### Current System State (from DB queries 2026-05-07)

| Metric | Paper | Live | Testnet |
|---|---|---|---|
| Bankroll | $148,112.59 | $830.67 | $100.00 |
| Total PnL | +$145,246.37 | -$185.03 | $0.00 |
| is_running | 1 | 1 | 0 |
| Last trade | May 6 05:37 | May 5 14:43 | Never |
| Trade attempts (2d) | ~22k | ~1k | ~6.8k |
| Executed (2d) | 0 | 0 | 0 |

### Research-Backed Enhancements (Becker 2026, Bloomberg, DigitalToday)

After the zero-trade fix, research reveals Polyedge operates as a **pure Taker system** — systematically paying the "optimism tax" that Becker documented at -1.12% per trade. Key insights integrated as new tasks:

| Finding | Impact | Polyedge Gap | New Task |
|---------|--------|-------------|----------|
| Makers +1.12%, Takers -1.12% | All strategies cross spread | Market maker exists but no QUOTE handler | T14, T15 |
| NO outperforms YES at 69/99 levels | 64pp edge at longshot prices | Symmetrical YES/NO treatment | T13 |
| Execution edge > Information edge | 60-75s latency, windows last seconds | HFT pipeline disconnected | T12 |
| Category efficiency varies 0.17-4.79pp | Weather 2.57pp gap exploitable | No category-awareness | T16 |
| $40M Polymarket arb | probability_arb polls every 120s | Too slow for sub-second windows | T12 |
| CLOB sync wrapper + global lock | All trades serialized | Need parallel execution | T17 |
| Trade table lacks maker/taker role | Can't optimize without tracking | HFTExecutionRecord has role, Trade doesn't | T18 |

### Comprehensive-Fix Plan Audit Gaps (found during consolidation)

An audit of the 61-task `polyedge-comprehensive-fix.md` (all marked [x]) revealed 3 items that need follow-up:

| # | Gap | Severity | Issue | New Task |
|---|-----|----------|-------|----------|
| G1 | **BotState race condition** | 🔴 P0 | T59 was DEFERRED but 47/52 files unprotected. `for_update()` is noop on SQLite. PM2 runs 3 processes = real race on bankroll/P&L | T19 |
| G2 | **nightly_archive_job not scheduled** | 🟡 P1 | `db_archiver.py` has `nightly_archive_job()` but it's never registered in `scheduler.py` — never runs | T20 |
| G3 | **NightlyReview→KG TODO** | 🟡 P2 | `nightly_review.py:52` still has `# TODO: Wire into KnowledgeGraph`. Uses event bus stopgap instead | T21 |

### The 7 Blockers (ALL must be fixed)

| # | Blocker | Severity | Impact | Root Cause |
|---|---------|----------|--------|------------|
| **B1** | RISK_PROFILE=extreme NOT applied at startup | 🔴 P0 | Drawdown 15% instead of 40%, confidence 0.50 instead of 0.20 | `apply_profile()` only called via API, never at boot |
| **B2** | 5/11 strategies CANNOT produce 0.50 confidence | 🔴 P0 | weather, prob_arb, cross_arb, cex_leadlag, btc_oracle permanently blocked | Confidence scales misaligned — using raw edge/profit, not probability |
| **B3** | copy_trader direction="buy" BUG | 🔴 P0 | 930 HIGH-confidence (0.65) trades rejected for invalid direction | Direction mapping: "buy" not in {up, down, YES, yes} |
| **B4** | copy_trader sizing overflow | 🟡 P1 | $4,000+ calculated positions vs $100-$200 max | Kelly fraction mis-scaled for copy_trader |
| **B5** | Loss floors NOT in risk profile | 🟡 P1 | Daily -10% floor overrides extreme's 40% drawdown | `check_drawdown_floors()` not controlled by profile |
| **B6** | Daily loss limit $40 flat (not %) | 🟡 P1 | On $830 = 4.8% daily loss cap | Extreme profile uses flat $40, not % of bankroll |
| **B7** | Auto-disable cron kills too aggressively | 🟡 P1 | btc_oracle + general_scanner permanently disabled | WR<30% in 1-hour window → disabled, no re-enable path |

---

## Work Objectives

### Core Objective
Fix all 7 zero-trade blockers AND apply research-backed profitability enhancements to transform Polyedge from a systematic Taker (paying -1.12%/trade optimism tax) into a competitive Maker/Taker hybrid with execution edge.

### Concrete Deliverables
- `apply_profile()` called at startup → extreme profile actually applied
- Per-strategy confidence normalization → 0.50 threshold meaningful for all
- copy_trader direction mapping fixed → 930 fewer rejections
- copy_trader Kelly sizing capped → no $4k positions
- Loss floors configurable via risk profile → extreme = -40%/-60%
- Daily loss limit as % of bankroll → scales with capital
- Auto-disable with rehabilitation path → strategies can recover
- Reduce scan interval 60s→5-10s → capture sub-minute windows
- NO-bias weighting at longshot prices → exploit YES/NO asymmetry
- HFT pipeline connected to main strategies → <5s latency path
- Market maker QUOTE handler → capture +1.12%/trade maker edge
- Category-aware confidence adjustment → exploit category efficiency gaps
- Parallel CLOB execution → remove global trade lock
- Trade table includes role field → track maker/taker performance

### Must Have
- System executing trades within 24h of fixes deployed
- auto_trader live trades firing (highest confidence strategy)
- copy_trader passing validation (direction + sizing fixed)
- RISK_PROFILE=extreme threshold values actually in effect
- Scan interval reduced to ≤10s (from 60s)
- NO-bias weight applied at longshot price ranges (1-20¢)
- Market maker QUOTE decisions executable (not just logged)
- Main strategies can use WebSocket-fed data (not REST-only)

### Must NOT Have (Guardrails)
- NO lowering confidence below 0.20 (even extreme has limits)
- NO disabling drawdown breaker entirely (safety net stays)
- NO removing auto-disable cron (just add rehabilitation)
- NO removing loss floors (just make them profile-configurable)
- NO removing YES trades entirely (NO bias is a weight, not a filter)
- NO bypassing risk checks for speed (HFT path still goes through RiskManager)
- NO removing the global trade lock without replacing it with per-asset locks
- NO connecting HFT pipeline to LIVE mode until paper-mode validation passes

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: YES (pytest + backend/tests/)
- **Automated tests**: Tests-after (fixes first, then add regression tests)
- **Framework**: pytest

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (P0 Critical — 4 tasks, MAX PARALLEL):
├── T1:  apply_profile() at startup (backend/core/orchestrator.py)
├── T2:  Normalize confidence scales for 5 strategies
├── T3:  Fix copy_trader direction mapping ("buy" → "YES")
└── T4:  Fix copy_trader Kelly sizing overflow

Wave 2 (P1 Config — 4 tasks, after Wave 1):
├── T5:  Make loss floors configurable via risk profile
├── T6:  Convert daily_loss_limit from flat $ to % of bankroll
├── T7:  Add auto-disable rehabilitation path (cooldown + re-enable)
└── T8:  Re-enable killed strategies (btc_oracle + general_scanner)

Wave 3 (Validation — 3 tasks, after Wave 2):
├── T9:  Verify extreme profile thresholds applied correctly
├── T10: End-to-end trade execution test (paper mode)
└── T11: Live mode dry-run verification (signal → risk → not blocked)

Wave 4 (Research: Execution Edge — 3 tasks, after Wave 3):
├── T12: Reduce scan interval 60s→10s, connect WebSocket data to scan loop
├── T13: Add NO-bias weighting for longshot contracts (1-20¢ price range)
└── T14: Wire HFT pipeline to main strategies (WebSocket → signal → order <5s)

Wave 5 (Research: Profitability — 3 tasks, after Wave 4):
├── T15: Implement market_maker QUOTE handler in strategy_executor
├── T16: Add category-aware confidence adjustment (Finance=1.0x, Entertainment=0.7x)
└── T17: Replace global trade_execution_lock with per-asset locks + parallel CLOB

Wave 6 (Research: Observability — 1 task, after Wave 5):
└── T18: Add maker/taker role tracking to Trade table + per-role P&L dashboard

Wave 7 (Audit Gaps — 3 tasks, after Wave 6):
├── T19: Fix BotState race condition (for_update + WAL mode for SQLite)
├── T20: Register nightly_archive_job in scheduler + wire NightlyReview to KnowledgeGraph
└── T21: Clean up blockchain_indexer/ClobEvent stale references

Wave FINAL (After ALL tasks — 4 parallel reviews):
├── F1: Plan compliance audit
├── F2: Code quality review
├── F3: Real QA — trigger trades, verify execution + profitability metrics
└── F4: Scope fidelity check
→ Present results → User okay
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| T1 | — | T5, T6, T9 |
| T2 | — | T9, T10 |
| T3 | — | T10 |
| T4 | — | T10 |
| T5 | T1 | T9, T10 |
| T6 | T1 | T9, T10 |
| T7 | — | T8 |
| T8 | T7 | T10 |
| T9 | T1, T5, T6 | T10 |
| T10 | All T1-T8 | T11 |
| T11 | T10 | T12, T13, T14 |
| T12 | T11 | T14, T15 |
| T13 | T11 | — |
| T14 | T12 | T15 |
| T15 | T14 | T17 |
| T16 | T11 | — |
| T17 | T15 | T18 |
| T18 | T17 | T19 |
| T19 | T18 | T20, T21, F1-F4 |
| T20 | T19 | F1-F4 |
| T21 | T19 | F1-F4 |

Critical Path: T1 → T5/T6 → T9 → T10 → T11 → T12 → T14 → T15 → T17 → T18 → T19 → F1-F4
Parallel Speedup: T2/T3/T4 run with T1; T7/T8 run with T5/T6; T13/T16 run with T12; T20/T21 run with T19

---

## TODOs

- [x] 1. Apply RISK_PROFILE at Startup

  **What to do**:
  - In `backend/core/orchestrator.py` startup sequence, add call to `apply_profile()` from `backend/core/risk_profiles.py`
  - Call it AFTER settings are loaded but BEFORE strategies are initialized
  - Read `RISK_PROFILE` env var (already read by `get_active_profile_name()`)
  - This will apply extreme profile thresholds: drawdown 40%/60%, confidence 0.20, edge 0.05, etc.
  - Add logging: "Applied risk profile '{name}': drawdown={dd}%, confidence={conf}, edge={edge}"

  **Must NOT do**:
  - Do NOT remove the API endpoint for profile changes (keep it for runtime changes)
  - Do NOT hardcode "extreme" — read from env var

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T2, T3, T4)
  - **Parallel Group**: Wave 1
  - **Blocks**: T5, T6, T9
  - **Blocked By**: None

  **References**:
  - `backend/core/risk_profiles.py:247` — `apply_profile()` function
  - `backend/core/risk_profiles.py:134` — `get_active_profile_name()` reads `RISK_PROFILE` env var
  - `backend/core/risk_profiles.py:101-108` — extreme profile thresholds
  - `backend/api/settings.py:773` — current API-only call site
  - `backend/core/orchestrator.py` — add `apply_profile()` call in startup

  **Acceptance Criteria**:
  - [ ] `apply_profile()` called during `orchestrator.start()` or `main()`
  - [ ] Log message shows "Applied risk profile 'extreme'" on startup
  - [ ] `settings.DAILY_DRAWDOWN_LIMIT_PCT == 0.40` after startup
  - [ ] `settings.AUTO_APPROVE_MIN_CONFIDENCE == 0.20` after startup

  **QA Scenarios**:
  ```
  Scenario: Profile applied at startup
    Tool: Bash (grep log)
    Preconditions: RISK_PROFILE=extreme in .env
    Steps:
      1. Start the bot
      2. Grep logs for "Applied risk profile 'extreme'"
      3. Query settings object: assert DAILY_DRAWDOWN_LIMIT_PCT == 0.40
    Expected Result: Profile applied, thresholds match extreme
    Failure Indicators: Log says "normal" or thresholds are 0.15/0.50
    Evidence: .sisyphus/evidence/task-1-profile-startup.log
  ```

  **Commit**: YES
  - Message: `fix(core): apply risk profile at startup, not just via API`
  - Files: `backend/core/orchestrator.py`

- [x] 2. Normalize Strategy Confidence Scales

  **What to do**:
  Fix 5 strategies whose confidence formula produces values incompatible with the 0.50 auto-approve threshold:

  1. **weather_emos** (`backend/modules/scanners/weather_emos.py`):
     - Current: `confidence = min(1.0, abs(edge))` — a 5% edge = 0.05 confidence
     - Fix: `confidence = min(1.0, abs(edge) / MIN_EDGE_THRESHOLD)` where MIN_EDGE_THRESHOLD=0.05 → 5% edge = 1.0, 2.5% edge = 0.50
     - OR: `confidence = min(1.0, abs(edge) * (1.0 / MIN_EDGE_THRESHOLD))` to normalize against threshold

  2. **probability_arb** (`backend/strategies/probability_arb.py`):
     - Current: `confidence = min(profit * 10.0, 1.0)` — $0.03 profit = 0.30, needs $0.05 for 0.50
     - Fix: `confidence = min(1.0, profit / MIN_PROFIT_TARGET)` where MIN_PROFIT_TARGET=0.03 → $0.03 = 1.0, $0.015 = 0.50

  3. **cross_market_arb** (`backend/strategies/cross_market_arb.py`):
     - Same formula as probability_arb — apply same fix

  4. **cex_pm_leadlag** (`backend/strategies/cex_pm_leadlag.py`):
     - Current: `confidence = max(0.05, edge + min_edge)` where min_edge=0.05
     - Problem: oracle_implied clamped to [0.40, 0.60] → max edge ≈ 0.10 → confidence ≈ 0.15
     - Fix: Scale confidence by edge magnitude: `confidence = min(1.0, abs(edge) / 0.10)` where 0.10 = typical max edge → 10% edge = 1.0, 5% = 0.50
     - OR: Remove [0.40, 0.60] clamp if it's artificially limiting the model

  5. **btc_oracle** (`backend/strategies/btc_oracle.py`):
     - Same formula as cex_pm_leadlag — apply same fix or remove clamp

  **Must NOT do**:
  - Do NOT change `AUTO_APPROVE_MIN_CONFIDENCE` to accommodate broken scales
  - Do NOT add fake confidence boosts (e.g., +0.30 offset)
  - Keep each strategy's confidence range meaningful (0 = no edge, 1.0 = max edge)

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T1, T3, T4)
  - **Parallel Group**: Wave 1
  - **Blocks**: T9
  - **Blocked By**: None

  **References**:
  - `backend/modules/scanners/weather_emos.py` — weather confidence calculation
  - `backend/strategies/probability_arb.py` — arb confidence: `min(profit * 10, 1.0)`
  - `backend/strategies/cross_market_arb.py` — cross-arb same formula
  - `backend/strategies/cex_pm_leadlag.py:115` — hardcoded `implied_prob = 1.0`, confidence formula
  - `backend/strategies/btc_oracle.py` — oracle confidence, same clamping issue
  - `backend/core/risk_manager.py:170-173` — where confidence threshold is checked
  - `backend/config.py:AUTO_APPROVE_MIN_CONFIDENCE` — current 0.50 (normal) / 0.20 (extreme)

  **Acceptance Criteria**:
  - [ ] weather_emos: 5% edge → confidence ≥ 0.50
  - [ ] probability_arb: $0.03 profit → confidence ≥ 0.50
  - [ ] cross_market_arb: same as probability_arb
  - [ ] cex_pm_leadlag: 5% edge → confidence ≥ 0.50
  - [ ] btc_oracle: 5% edge → confidence ≥ 0.50

  **QA Scenarios**:
  ```
  Scenario: Weather confidence at 5% edge
    Tool: Bash (python)
    Steps:
      1. Import weather_emos confidence calculation
      2. Call with edge=0.05
      3. Assert confidence >= 0.50
    Evidence: .sisyphus/evidence/task-2-confidence-scales.txt

  Scenario: Prob arb confidence at $0.03 profit
    Tool: Bash (python)
    Steps:
      1. Import probability_arb confidence calculation
      2. Call with profit=0.03
      3. Assert confidence >= 0.50
    Evidence: .sisyphus/evidence/task-2-prob-arb-confidence.txt
  ```

  **Commit**: YES
  - Message: `fix(strategies): normalize confidence scales across 5 strategies`
  - Files: weather_emos.py, probability_arb.py, cross_market_arb.py, cex_pm_leadlag.py, btc_oracle.py

- [x] 3. Fix copy_trader Direction Mapping

  **What to do**:
  - `copy_trader` sends `direction="buy"` but `TradeValidator.validate_trade_data()` at `strategy_executor.py:453-465` expects direction in {"up", "down", "YES", "yes"}
  - Find where copy_trader sets direction to "buy" and change to "YES" (or appropriate market direction)
  - Also check `bond_scanner.py:271` which sets `trade_direction = "buy"` — same bug
  - Fix BOTH strategies

  **Must NOT do**:
  - Do NOT change the validator to accept "buy" — the CLOB API expects YES/NO for prediction markets
  - "up"/"down" for crypto markets, "YES"/"NO" for prediction markets — these are the correct values

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T1, T2, T4)
  - **Parallel Group**: Wave 1
  - **Blocks**: T10
  - **Blocked By**: None

  **References**:
  - `backend/modules/execution/copy_trader.py` — find where direction="buy" is set
  - `backend/strategies/bond_scanner.py:271` — `trade_direction = "buy"`
  - `backend/core/strategy_executor.py:453-465` — `TradeValidator.validate_trade_data()` rejects "buy"
  - DB evidence: 930 REJECTED_TRADE_VALIDATION "direction must be one of {'up', 'down', 'YES', 'yes'}"

  **Acceptance Criteria**:
  - [ ] copy_trader direction field is "YES" or "NO" (not "buy")
  - [ ] bond_scanner direction field is "YES" or "NO" (not "buy")
  - [ ] Zero REJECTED_TRADE_VALIDATION for invalid direction

  **QA Scenarios**:
  ```
  Scenario: copy_trader generates valid direction
    Tool: Bash (grep)
    Steps:
      1. Grep copy_trader.py for 'direction.*buy' — should return 0 results
      2. Grep for 'direction.*YES' or 'direction.*NO' — should find matches
    Evidence: .sisyphus/evidence/task-3-direction-fix.txt
  ```

  **Commit**: YES
  - Message: `fix(copy_trader,bond_scanner): use YES/NO direction instead of buy`
  - Files: copy_trader.py, bond_scanner.py

- [x] 4. Fix copy_trader Kelly Sizing Overflow

  **What to do**:
  - copy_trader is producing position sizes of $1,000–$5,000 while max position is $100-$200
  - Root cause: Kelly fraction applied to paper bankroll ($148k) instead of mode-specific bankroll
  - In extreme profile: KELLY_FRACTION=0.80, MAX_POSITION_FRACTION=0.25, MAX_TRADE_SIZE=$50
  - With $148k paper bankroll: 0.80 × 0.25 × $148k = $29,600 (insane)
  - Need to cap position size at MAX_TRADE_SIZE ($50 for extreme) BEFORE Kelly calculation
  - Also: ensure copy_trader uses the MODE bankroll (paper: $148k for paper, live: $830 for live), not the paper bankroll for live trades

  **Must NOT do**:
  - Do NOT remove Kelly sizing — just cap it
  - Do NOT increase MAX_TRADE_SIZE beyond what risk profile allows

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T1, T2, T3)
  - **Parallel Group**: Wave 1
  - **Blocks**: T10
  - **Blocked By**: None

  **References**:
  - `backend/modules/execution/copy_trader.py` — find where size is calculated
  - `backend/core/risk_manager.py:205-210` — MAX_POSITION_FRACTION check
  - `backend/core/risk_manager.py:274-289` — MIN_ORDER_USDC check
  - `backend/core/risk_profiles.py:103` — extreme MAX_TRADE_SIZE=$50
  - DB evidence: REJECTED_TRADE_VALIDATION "Trade size 4017.17 exceeds max position size 100.0"

  **Acceptance Criteria**:
  - [ ] copy_trader calculated size <= MAX_TRADE_SIZE (from active risk profile)
  - [ ] copy_trader calculated size <= bankroll * MAX_POSITION_FRACTION
  - [ ] Live mode uses live bankroll, not paper bankroll

  **QA Scenarios**:
  ```
  Scenario: copy_trader size capped at MAX_TRADE_SIZE
    Tool: Bash (python)
    Steps:
      1. Call copy_trader sizing with bankroll=$830 (live), MAX_TRADE_SIZE=$50
      2. Assert calculated size <= $50
    Evidence: .sisyphus/evidence/task-4-sizing-cap.txt
  ```

  **Commit**: YES
  - Message: `fix(copy_trader): cap position size at risk profile limits`
  - Files: copy_trader.py

- [x] 5. Make Loss Floors Configurable via Risk Profile

  **What to do**:
  - `check_drawdown_floors()` at `risk_manager.py:477-601` enforces daily -10% and weekly -20% loss floors REGARDLESS of risk profile
  - Extreme profile sets drawdown limits to 40%/60% but floors stay at 10%/20%
  - Add `daily_loss_floor_pct` and `weekly_loss_floor_pct` fields to `RiskProfile` dataclass in `risk_profiles.py`
  - Set extreme profile: daily_floor=-0.40, weekly_floor=-0.60 (matching drawdown limits)
  - Add these to `apply_profile()` so they override `DAILY_LOSS_FLOOR_PCT` and `WEEKLY_LOSS_FLOOR_PCT` in settings
  - Update `check_drawdown_floors()` to use `settings.DAILY_LOSS_FLOOR_PCT` and `settings.WEEKLY_LOSS_FLOOR_PCT`

  **Must NOT do**:
  - Do NOT remove loss floors — they're a critical safety net
  - Do NOT set floors to -1.0 (disable) even for extreme

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T6, T7, T8)
  - **Parallel Group**: Wave 2 (depends on T1 being done for profile structure familiarity)
  - **Blocks**: T9
  - **Blocked By**: T1 (need to understand profile structure)

  **References**:
  - `backend/core/risk_profiles.py:25-55` — RiskProfile dataclass
  - `backend/core/risk_profiles.py:101-108` — extreme profile values
  - `backend/core/risk_profiles.py:247-265` — `apply_profile()` mutation
  - `backend/core/risk_manager.py:477-601` — `check_drawdown_floors()` enforcement
  - `backend/config.py:DAILY_LOSS_FLOOR_PCT` — current hardcoded -0.10
  - `backend/config.py:WEEKLY_LOSS_FLOOR_PCT` — current hardcoded -0.20

  **Acceptance Criteria**:
  - [ ] RiskProfile has `daily_loss_floor_pct` and `weekly_loss_floor_pct` fields
  - [ ] Extreme profile: daily_floor=-0.40, weekly_floor=-0.60
  - [ ] `apply_profile()` sets settings.DAILY_LOSS_FLOOR_PCT and WEEKLY_LOSS_FLOOR_PCT
  - [ ] `check_drawdown_floors()` reads from settings (not hardcoded)

  **QA Scenarios**:
  ```
  Scenario: Extreme profile sets loss floors
    Tool: Bash (python)
    Steps:
      1. Call apply_profile("extreme")
      2. Assert settings.DAILY_LOSS_FLOOR_PCT == -0.40
      3. Assert settings.WEEKLY_LOSS_FLOOR_PCT == -0.60
    Evidence: .sisyphus/evidence/task-5-loss-floor-config.txt
  ```

  **Commit**: YES
  - Message: `feat(risk): make loss floors configurable via risk profile`
  - Files: risk_profiles.py, config.py, risk_manager.py

- [x] 6. Convert Daily Loss Limit to Percentage

  **What to do**:
  - Extreme profile sets `daily_loss_limit = 40.0` (flat dollar)
  - On $830 bankroll, $40 = 4.8% — trips WAY before 40% drawdown limit
  - Add `daily_loss_limit_pct` field to RiskProfile OR make `daily_loss_limit` dynamic
  - Option A: Add percentage-based daily loss limit that scales with bankroll
  - Option B: In `apply_profile()`, compute `daily_loss_limit = bankroll * daily_loss_limit_pct`
  - Extreme profile: `daily_loss_limit_pct = 0.40` → on $830 = $332 (matches drawdown)
  - Update `_daily_loss_exceeded()` in risk_manager.py to accept dynamic limit

  **Must NOT do**:
  - Do NOT remove the daily loss limit check
  - Do NOT set limit to 0 (unlimited)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T5, T7, T8)
  - **Parallel Group**: Wave 2
  - **Blocks**: T9
  - **Blocked By**: T1

  **References**:
  - `backend/core/risk_profiles.py:104` — extreme `daily_loss_limit=40.0`
  - `backend/core/risk_manager.py:175-181` — `_daily_loss_exceeded()` check
  - `backend/core/risk_manager.py:141` — `DAILY_LOSS_LIMIT` setting

  **Acceptance Criteria**:
  - [ ] Daily loss limit scales with current bankroll
  - [ ] On $830 bankroll with extreme: limit = $332 (40%)
  - [ ] On $100 bankroll with extreme: limit = $40 (40%)

  **QA Scenarios**:
  ```
  Scenario: Daily loss limit scales with bankroll
    Tool: Bash (python)
    Steps:
      1. Apply extreme profile
      2. Call _daily_loss_exceeded() with bankroll=$830, loss=$100
      3. Assert NOT exceeded (100 < 332)
      4. Call with bankroll=$830, loss=$400
      5. Assert exceeded (400 > 332)
    Evidence: .sisyphus/evidence/task-6-dynamic-loss-limit.txt
  ```

  **Commit**: YES
  - Message: `fix(risk): make daily loss limit percentage-based, scale with bankroll`
  - Files: risk_profiles.py, risk_manager.py

- [x] 7. Add Auto-Disable Rehabilitation Path

  **What to do**:
  - `auto_disable_losing_strategies()` (scheduler.py:778-818) disables strategies with WR<30% or PnL<-$50 in last hour
  - Once disabled, there's NO path to re-enable (except `strategy_rehabilitator.py` which requires 50% WR + 7-day cooldown)
  - Add a lighter rehabilitation path: after 1-hour cooldown, auto-re-enable strategy in PAPER mode only
  - If strategy performs well in paper for next hour (WR>30%), keep enabled
  - If still bad, re-disable for 4 hours
  - Also: exempt strategies with <10 recent trades (sample too small to judge reliably)

  **Must NOT do**:
  - Do NOT remove auto-disable (it's protecting capital)
  - Do NOT auto-re-enable in LIVE mode (paper only)
  - Do NOT shorten cooldown below 1 hour

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T5, T6, T8)
  - **Parallel Group**: Wave 2
  - **Blocks**: T8 (re-enable killed strategies requires this)
  - **Blocked By**: None

  **References**:
  - `backend/core/scheduler.py:778-818` — `auto_disable_losing_strategies()`
  - `backend/core/strategy_rehabilitator.py` — existing rehabilitator (too strict)
  - `backend/core/strategy_health.py:258-276` — `_disable_strategy()` in health monitor
  - `backend/models/database.py:StrategyConfig` — enabled field

  **Acceptance Criteria**:
  - [ ] After 1h of being disabled, strategy auto-re-enables in paper mode
  - [ ] If WR<30% in re-enable hour, strategy is re-disabled for 4h
  - [ ] Strategies with <10 trades in last hour are EXEMPT from auto-disable

  **QA Scenarios**:
  ```
  Scenario: Strategy rehabilitated after cooldown
    Tool: Bash (python)
    Steps:
      1. Disable a strategy
      2. Wait 1h (or mock time)
      3. Assert strategy re-enabled (paper mode only)
    Evidence: .sisyphus/evidence/task-7-rehabilitation.txt
  ```

  **Commit**: YES
  - Message: `feat(scheduler): add auto-rehabilitation path for disabled strategies`
  - Files: scheduler.py

- [x] 8. Re-enable Killed Strategies

  **What to do**:
  - btc_oracle: killed by strategy_health (WR=27%, Sharpe=-4.06, DD=766B% [bug!], Brier=0.73)
  - general_scanner: killed by strategy_health (WR=10%, 1 win out of 10 trades)
  - After T7 rehabilitation path exists, re-enable both strategies
  - Set them to paper mode initially (not live) until they prove themselves
  - Note: btc_oracle's drawdown of 766B% is clearly a calculation bug (`max_drawdown` field overflow)
  - This drawdown bug in strategy_health may have caused premature killing

  **Must NOT do**:
  - Do NOT re-enable in live mode directly
  - Do NOT clear their health history (keep for forensics)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on T7)
  - **Parallel Group**: Wave 2 (after T7)
  - **Blocks**: T10
  - **Blocked By**: T7

  **References**:
  - `backend/models/database.py:StrategyConfig` — enabled field
  - `backend/core/strategy_health.py` — killed status
  - DB: strategy_health table shows btc_oracle WR=27%, general_scanner WR=10%
  - DB: btc_oracle max_drawdown=766937296051.968 (clearly a calculation bug, should be <1.0)

  **Acceptance Criteria**:
  - [ ] btc_oracle StrategyConfig.enabled = True
  - [ ] general_scanner StrategyConfig.enabled = True
  - [ ] Both start in paper-only mode

  **QA Scenarios**:
  ```
  Scenario: Strategies re-enabled
    Tool: Bash (sqlite3)
    Steps:
      1. Query strategy_config: SELECT enabled FROM strategy_config WHERE strategy_name='btc_oracle'
      2. Assert enabled = 1
      3. Same for general_scanner
    Evidence: .sisyphus/evidence/task-8-reenable.txt
  ```

  **Commit**: YES
  - Message: `fix(strategies): re-enable btc_oracle and general_scanner in paper mode`
  - Files: migration script or API call

- [x] 9. Verify Extreme Profile Applied Correctly

  **What to do**:
  - After T1, T5, T6 are deployed, start the bot and verify:
  - DAILY_DRAWDOWN_LIMIT_PCT = 0.40
  - WEEKLY_DRAWDOWN_LIMIT_PCT = 0.60
  - AUTO_APPROVE_MIN_CONFIDENCE = 0.20
  - MIN_EDGE_THRESHOLD = 0.05
  - MAX_TRADE_SIZE = $50
  - DAILY_LOSS_FLOOR_PCT = -0.40
  - WEEKLY_LOSS_FLOOR_PCT = -0.60
  - DAILY_LOSS_LIMIT = $332 (40% of $830)
  - KELLY_FRACTION = 0.80

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (must wait for T1, T5, T6)
  - **Parallel Group**: Wave 3
  - **Blocks**: T10
  - **Blocked By**: T1, T5, T6

  **References**:
  - `backend/core/risk_profiles.py:101-108` — extreme profile values
  - `backend/core/risk_manager.py:175-193` — where thresholds are checked

  **Acceptance Criteria**:
  - [ ] All extreme profile values verified via settings object or API

  **QA Scenarios**:
  ```
  Scenario: Full extreme profile verification
    Tool: Bash (curl + python)
    Steps:
      1. Start bot with RISK_PROFILE=extreme
      2. Call GET /api/settings/risk-profile
      3. Assert all values match extreme specification
    Evidence: .sisyphus/evidence/task-9-profile-verify.txt
  ```

  **Commit**: NO (verification only)

- [x] 10. End-to-End Trade Execution Test (Paper Mode)

  **What to do**:
  - After all fixes, verify trades can execute in paper mode:
  1. auto_trader produces signals with confidence 0.82-0.84 → should auto-approve at 0.20 threshold
  2. copy_trader produces signals with confidence 0.35-0.65 → 0.35 below 0.20? No, 0.35 > 0.20 → should approve
  3. Weather/prob_arb signals with confidence ≥0.50 (after normalization)
  4. Verify NO drawdown breaker rejections (loss floors should be -40%/-60%)
  5. Verify trade_attempts table shows EXECUTED entries within 1 hour

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (must wait for all T1-T8)
  - **Parallel Group**: Wave 3
  - **Blocks**: T11
  - **Blocked By**: T9

  **Acceptance Criteria**:
  - [ ] At least 5 EXECUTED trade_attempts in paper mode within 1 hour
  - [ ] Zero REJECTED_LOW_CONFIDENCE for strategies with confidence > 0.20
  - [ ] Zero REJECTED_DRAWDOWN_BREAKER for paper mode (already disabled per config)

  **QA Scenarios**:
  ```
  Scenario: Paper trades executing
    Tool: Bash (sqlite3)
    Steps:
      1. Wait 1 hour after restart
      2. Query: SELECT COUNT(*) FROM trade_attempts WHERE status='EXECUTED' AND created_at > datetime('now', '-1 hour')
      3. Assert count >= 5
    Evidence: .sisyphus/evidence/task-10-e2e-paper.txt
  ```

  **Commit**: NO (integration test)

- [x] 11. Live Mode Dry-Run Verification

  **What to do**:
  - Verify that live mode signals are NOT blocked by drawdown breaker or loss floors
  - Use the CLOB circuit breaker status to check API health first
  - Run 5 minutes in live mode with SHADOW_MODE behavior (log but don't execute)
  - Verify signal → risk → approval pipeline completes without REJECTED status

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3
  - **Blocked By**: T10

  **Acceptance Criteria**:
  - [ ] Live trade_attempts show < 10% REJECTED_DRAWDOWN_BREAKER rate
  - [ ] High-confidence signals (0.80+) pass risk validation
  - [ ] CLOB circuit breaker is CLOSED (API healthy)

  **QA Scenarios**:
  ```
  Scenario: Live signals not blocked by breaker
    Tool: Bash (curl + sqlite3)
    Steps:
      1. Run system for 5 min in live mode
      2. Query: SELECT status, COUNT(*) FROM trade_attempts WHERE mode='live' AND created_at > datetime('now', '-5 minutes') GROUP BY status
      3. Assert no REJECTED_DRAWDOWN_BREAKER entries
    Evidence: .sisyphus/evidence/task-11-live-dryrun.txt
  ```

  **Commit**: NO (verification only)

- [x] 12. Reduce Scan Interval + Connect WebSocket Data to Scan Loop

  **What to do**:
  - Change `SCAN_INTERVAL_SECONDS` default from 60 to 10 (config.py)
  - Change `WEATHER_SCAN_INTERVAL_SECONDS` default from 300 to 60 (config.py)
  - Change `ARBITRAGE_SCAN_INTERVAL_SECONDS` default from 120 to 30 (config.py)
  - In `scheduling_strategies.py:scan_and_trade_job()`, replace REST market data fetch with `OrderbookCache` lookup (already populated by WebSocket)
  - Pre-warm `OrderbookCache` on startup so first scan doesn't pay REST penalty
  - Reduce `copy_trader` whale polling from 60s to 15s
  - Add `LATENCY_OPTIMIZER_ENABLED=true` env var to activate existing `latency_optimizer.py`

  **Must NOT do**:
  - Do NOT remove REST fallback — keep it for when WebSocket disconnects
  - Do NOT reduce below 5s scan interval (API rate limits)
  - Do NOT skip risk validation for speed

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T13)
  - **Parallel Group**: Wave 4
  - **Blocks**: T14
  - **Blocked By**: T11 (system must be trading first)

  **References**:
  - `backend/config.py` — `SCAN_INTERVAL_SECONDS=60`, `WEATHER_SCAN_INTERVAL_SECONDS=300`, `ARBITRAGE_SCAN_INTERVAL_SECONDS=120`
  - `backend/core/scheduling_strategies.py` — `scan_and_trade_job()` uses REST calls
  - `backend/data/orderbook_cache.py` — In-memory cache with 30s TTL, WebSocket-fed
  - `backend/data/polymarket_websocket.py` — Real-time WebSocket client (exists, not connected to scan path)
  - `backend/data/ws_client.py` — `CLOBWebSocket` auto-reconnecting (exists, not primary)
  - `backend/infrastructure/market_stream/orderbook_router.py` — Routes WS data (exists, not used in scan)
  - `backend/core/latency_optimizer.py` — Exists but unused in critical path

  **Acceptance Criteria**:
  - [ ] `SCAN_INTERVAL_SECONDS` default = 10
  - [ ] `scan_and_trade_job()` reads from `OrderbookCache` instead of REST when cache is fresh (<30s)
  - [ ] Copy trader polls every 15s (down from 60s)
  - [ ] First scan after startup completes within 15s (pre-warmed cache)

  **QA Scenarios**:
  ```
  Scenario: Scan completes within 15s with cached data
    Tool: Bash (python)
    Steps:
      1. Start bot with WebSocket connection
      2. Wait for OrderbookCache to have >10 entries
      3. Trigger scan_and_trade_job()
      4. Measure time from trigger to completion
      5. Assert < 15s total
    Expected Result: Scan completes within 15s using cached data
    Failure Indicators: Scan takes >60s or falls back to REST on every call
    Evidence: .sisyphus/evidence/task-12-scan-speed.txt

  Scenario: REST fallback works when WebSocket disconnects
    Tool: Bash (curl + python)
    Steps:
      1. Disconnect WebSocket
      2. Trigger scan_and_trade_job()
      3. Verify it falls back to REST fetch
      4. Reconnect WebSocket
      5. Verify it switches back to cache
    Expected Result: Graceful fallback without errors
    Evidence: .sisyphus/evidence/task-12-rest-fallback.txt
  ```

  **Commit**: YES
  - Message: `perf(scan): reduce scan intervals and use WebSocket-fed cache`
  - Files: config.py, scheduling_strategies.py
  - Pre-commit: pytest

- [x] 13. Add NO-Bias Weighting for Longshot Contracts

  **What to do**:
  Becker research: NO contracts outperform YES at 69/99 price levels, with 64pp gap at 1¢. Currently Polyedge treats YES/NO symmetrically. Add a configurable bias weight that favors NO contracts at longshot prices.

  - Add `LONGSHOT_NO_BIAS_WEIGHT` config param (default: 0.15 in extreme profile, 0.10 in normal)
  - In `risk_manager.py:validate_trade()`, when `signal.direction == "NO"` and `signal.price <= 20` (cents), apply confidence boost: `adjusted_confidence = confidence * (1 + LONGSHOT_NO_BIAS_WEIGHT)`
  - When `signal.direction == "YES"` and `signal.price <= 20`, apply confidence penalty: `adjusted_confidence = confidence * (1 - LONGSHOT_NO_BIAS_WEIGHT * 0.5)`
  - In extreme profile: `longshot_no_bias_weight = 0.15` (NO gets +15% confidence lift, YES gets -7.5% penalty at longshot prices)
  - Log the bias application: "Applied NO-bias: {direction} @ {price}¢ → {original:.2f} → {adjusted:.2f}"
  - Add to `apply_profile()` so it's profile-configurable

  **Must NOT do**:
  - Do NOT filter out YES trades entirely (just weight them)
  - Do NOT apply bias at prices > 20¢ (research shows effect concentrated at longshot range)
  - Do NOT apply in paper mode verification (T10/T11) — enable after validation passes
  - Do NOT bypass risk validation even with NO bias

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T12)
  - **Parallel Group**: Wave 4
  - **Blocks**: —
  - **Blocked By**: T11 (system trading first)

  **References**:
  - `backend/core/risk_manager.py:453-465` — `TradeValidator.validate_trade_data()` where confidence is checked
  - `backend/core/risk_profiles.py:101-108` — extreme profile values (add NO bias weight here)
  - `backend/core/risk_profiles.py:247-265` — `apply_profile()` mutation
  - `backend/config.py` — add `LONGSHOT_NO_BIAS_WEIGHT` config
  - Becker research: "NO contracts outperform YES at 69 of 99 price levels" with 64pp divergence at 1¢

  **Acceptance Criteria**:
  - [ ] NO contracts at price ≤20¢ get confidence boost of `1 + LONGSHOT_NO_BIAS_WEIGHT`
  - [ ] YES contracts at price ≤20¢ get confidence penalty of `1 - LONGSHOT_NO_BIAS_WEIGHT * 0.5`
  - [ ] No bias applied at price >20¢
  - [ ] Extreme profile: `longshot_no_bias_weight = 0.15`
  - [ ] Log messages show bias application

  **QA Scenarios**:
  ```
  Scenario: NO-bias applied at longshot price
    Tool: Bash (python)
    Steps:
      1. Apply extreme profile
      2. Create signal: direction="NO", price=5¢, confidence=0.40
      3. Validate trade → assert adjusted_confidence ≈ 0.46 (0.40 * 1.15)
    Expected Result: NO longshot gets 15% confidence boost
    Failure Indicators: No boost, or boost applied at price >20¢
    Evidence: .sisyphus/evidence/task-13-no-bias.txt

  Scenario: NO-bias NOT applied at mid-range price
    Tool: Bash (python)
    Steps:
      1. Apply extreme profile
      2. Create signal: direction="NO", price=50¢, confidence=0.60
      3. Validate trade → assert adjusted_confidence == 0.60 (unchanged)
    Expected Result: No bias applied at mid-range prices
    Failure Indicators: Bias applied at 50¢
    Evidence: .sisyphus/evidence/task-13-no-bias-midrange.txt
  ```

  **Commit**: YES
  - Message: `feat(risk): add NO-bias weighting for longshot contracts per microstructure research`
  - Files: risk_manager.py, risk_profiles.py, config.py
  - Pre-commit: pytest

- [x] 14. Wire HFT Pipeline to Main Strategies

  **What to do**:
  The HFT subsystem exists (`hft_executor.py`, `hft_signal_gen.py`, `orderbook_hft_ws.py`, `config_hft.py`) but is DISCONNECTED from the main trading pipeline. All 14 strategies go through the 60s-polling `scan_and_trade_job()`. This task connects the HFT pipeline.

  - In `strategy_executor.py:execute_decision()`, add a "fast path" that uses `HFTExecutor` for strategies with `HFTLatencyConfig.MAX_EXECUTION_LATENCY_MS=50`
  - Replace `asyncio.to_thread(self._clob_client.create_order, ...)` with direct async call using `httpx.AsyncClient` (eliminate ~500ms thread pool overhead)
  - Remove `_trade_execution_lock` from strategy_executor.py (line 34) and replace with per-asset `asyncio.Lock()` dict to allow concurrent multi-asset execution
  - Connect `OrderbookRouter` output to `scan_and_trade_job()` so price updates trigger immediate re-evaluation instead of waiting for next poll cycle
  - Add `HFT_ENABLED=true` env var to gate the fast path (default: true, disable for safety)

  **Must NOT do**:
  - Do NOT remove the slow path (REST polling) — keep as fallback
  - Do NOT bypass RiskManager in the fast path
  - Do NOT enable HFT path in LIVE mode until T11 passes
  - Do NOT remove idempotency check

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on T12)
  - **Parallel Group**: Wave 4 (after T12)
  - **Blocks**: T15
  - **Blocked By**: T12 (scan interval reduced + WebSocket connected)

  **References**:
  - `backend/core/hft_executor.py` — HFT executor with <50ms target (exists, unused)
  - `backend/core/hft_signal_gen.py` — HFT signal generator with 1s dedup (exists, unused)
  - `backend/core/config_hft.py` — `HFTLatencyConfig` with latency budgets (exists, unused)
  - `backend/core/latency_optimizer.py` — LatencyOptimizer class (exists, unused)
  - `backend/core/strategy_executor.py:34` — `_trade_execution_lock` (global, serializes all trades)
  - `backend/core/strategy_executor.py:358` — `place_limit_order` call site (asyncio.to_thread)
  - `backend/data/polymarket_clob.py:621-628` — sync CLOB wrapper (asyncio.to_thread wrapping)
  - `backend/data/orderbook_hft_ws.py` — HFT orderbook WebSocket (exists)
  - `backend/infrastructure/market_stream/orderbook_router.py` — OrderbookRouter (exists, not in scan path)

  **Acceptance Criteria**:
  - [ ] Strategies marked as HFT-eligible use the fast execution path
  - [ ] `asyncio.to_thread(create_order)` replaced with async httpx call for HFT path
  - [ ] Per-asset locks replace global `_trade_execution_lock`
  - [ ] OrderbookRouter price updates trigger immediate strategy re-evaluation
  - [ ] HFT_ENABLED env var controls fast/slow path
  - [ ] Signal → order latency < 5s for HFT strategies (measured)

  **QA Scenarios**:
  ```
  Scenario: HFT path executes within 5s
    Tool: Bash (python + timing)
    Steps:
      1. Enable HFT_ENABLED=true
      2. Generate synthetic signal
      3. Measure time from signal creation to order placement
      4. Assert < 5s total latency
    Expected Result: HFT path completes in <5s
    Failure Indicators: Latency > 10s, or HFT path falls back to slow path
    Evidence: .sisyphus/evidence/task-14-hft-latency.txt

  Scenario: Slow path still works when HFT disabled
    Tool: Bash (python)
    Steps:
      1. Set HFT_ENABLED=false
      2. Generate synthetic signal
      3. Verify it goes through standard scan_and_trade path
    Expected Result: Standard path works as before
    Failure Indicators: Errors when HFT_ENABLED=false
    Evidence: .sisyphus/evidence/task-14-slow-path-fallback.txt
  ```

  **Commit**: YES
  - Message: `feat(execution): wire HFT pipeline to main strategies, replace global lock`
  - Files: strategy_executor.py, polymarket_clob.py, scheduling_strategies.py
  - Pre-commit: pytest

- [x] 15. Implement Market Maker QUOTE Handler

  **What to do**:
  `market_maker.py` generates `QUOTE` decisions but `strategy_executor.py` has no handler for them. This means the system's maker strategy is entirely inactive. Add a QUOTE handler that places and maintains resting limit orders on both sides of the spread.

  - In `strategy_executor.py`, add `execute_quote()` method alongside existing `execute_decision()`
  - `execute_quote()` should place a GTC (Good Till Cancelled) limit order at the quoted price on both YES and NO sides
  - Add `cancel_quote()` method to remove resting orders when market moves away from quote price
  - Add `replace_quote()` method to re-place at new price when spread shifts (>1¢ from current quote)
  - In the main loop, when `market_maker` produces a `QUOTE` decision, call `execute_quote()` instead of `execute_decision()`
  - Track maker fills separately in `Trade` table (add `role` column: `'maker'`/`'taker'`)
  - Add `MARKET_MAKER_ENABLED=true` env var

  **Must NOT do**:
  - Do NOT enable maker mode in LIVE until T11 passes (paper only first)
  - Do NOT remove existing taker strategies — this is additive
  - Do NOT place maker orders without inventory limits (max position per market)
  - Do NOT skip risk checks even for maker orders

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on T14 for fast execution)
  - **Parallel Group**: Wave 5 (after T14)
  - **Blocks**: T17
  - **Blocked By**: T14 (need HFT path for timely quote updates)

  **References**:
  - `backend/strategies/market_maker.py:34-45` — two-sided quoting logic with dynamic spread
  - `backend/strategies/market_maker.py:120` — "no orders are placed; that is the executor's responsibility"
  - `backend/strategies/market_maker.py:205` — `QUOTE` decision with calculated prices
  - `backend/core/strategy_executor.py:693` — `execute_decisions()` loops through decisions (no QUOTE handler)
  - `backend/core/trade_forensics.py:19` — `classify_trade_role()` (exists for analysis)
  - `backend/models/database.py:214` — `HFTExecutionRecord` has `role` column (but `Trade` doesn't)
  - `backend/data/polymarket_clob.py:509` — `place_limit_order()` (use GTC for maker orders)

  **Acceptance Criteria**:
  - [ ] `execute_quote()` handler exists in strategy_executor.py
  - [ ] Quote decisions produce resting GTC limit orders on both YES and NO sides
  - [ ] Quotes are replaced when spread shifts >1¢
  - [ ] Quotes are cancelled when market moves away from quote price
  - [ ] `Trade` table includes `role` column with 'maker'/'taker' values
  - [ ] Paper-mode maker orders execute without errors

  **QA Scenarios**:
  ```
  Scenario: Maker QUOTE produces resting orders
    Tool: Bash (python + sqlite3)
    Steps:
      1. Enable MARKET_MAKER_ENABLED=true in paper mode
      2. Wait for market_maker QUOTE decision
      3. Check Trade table for role='maker' entries
      4. Verify YES side at ask price, NO side at bid price
    Expected Result: Two resting orders per market, both marked 'maker'
    Failure Indicators: No maker entries, or ERROR status
    Evidence: .sisyphus/evidence/task-15-maker-quotes.txt

  Scenario: Maker quotes replaced on spread shift
    Tool: Bash (python)
    Steps:
      1. Place initial quote at spread=2¢
      2. Simulate spread shift to 4¢
      3. Verify old quote cancelled, new quote placed
    Expected Result: Quote replacement within one scan cycle
    Failure Indicators: Stale quotes remain, or duplicate orders
    Evidence: .sisyphus/evidence/task-15-quote-replacement.txt
  ```

  **Commit**: YES
  - Message: `feat(strategy): implement market maker QUOTE handler with resting limit orders`
  - Files: strategy_executor.py, market_maker.py, models/database.py
  - Pre-commit: pytest

- [x] 16. Add Category-Aware Confidence Adjustment

  **What to do**:
  Becker research shows category efficiency varies hugely: Finance 0.17pp gap (nearly efficient, hard to beat), Sports 2.23pp, Entertainment 4.79pp (highly exploitable). Currently Polyedge's confidence scores don't account for category.

  - Add `CATEGORY_CONFIDENCE_MULTIPLIER` mapping in config:
    - `finance: 0.85` (tight spreads, hard to beat — reduce confidence)
    - `politics: 0.95` (moderate edge)
    - `sports: 1.10` (large gap — boost confidence)
    - `crypto: 1.10` (similar to sports)
    - `weather: 1.15` (2.57pp gap — boost confidence significantly)
    - `entertainment: 1.15` (4.79pp gap — boost confidence)
    - `default: 1.00` (no adjustment)
  - In `risk_manager.py:validate_trade()`, after NO-bias adjustment (T13), apply category multiplier: `final_confidence = adjusted_confidence * CATEGORY_CONFIDENCE_MULTIPLIER[category]`
  - Map each market's `category_slug` to the multiplier using Polymarket's category data (already in `market_universe`)
  - Add `CATEGORY_CONFIDENCE_ENABLED=true` env var

  **Must NOT do**:
  - Do NOT change the signal generation — only adjust confidence at validation time
  - Do NOT apply multiplier to categories we don't have mapping for (use default=1.00)
  - Do NOT reduce finance confidence below the minimum threshold (0.20 in extreme)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T12, T13, T14)
  - **Parallel Group**: Wave 5
  - **Blocks**: —
  - **Blocked By**: T11 (system trading first)

  **References**:
  - `backend/core/risk_manager.py:453-465` — confidence validation
  - `backend/data/market_universe.py` — market discovery with category data
  - `backend/config.py` — add `CATEGORY_CONFIDENCE_MULTIPLIER` config
  - Becker research: Finance=0.17pp gap, Sports=2.23pp, Entertainment=4.79pp, Weather=2.57pp

  **Acceptance Criteria**:
  - [ ] Category multiplier mapping exists with at least 6 categories
  - [ ] Weather markets get +15% confidence boost
  - [ ] Finance markets get -15% confidence reduction
  - [ ] Unknown categories default to 1.00 (no adjustment)
  - [ ] Multiplier applied AFTER NO-bias (T13), BEFORE risk threshold check

  **QA Scenarios**:
  ```
  Scenario: Category multiplier applied to weather market
    Tool: Bash (python)
    Steps:
      1. Create signal: category="weather", confidence=0.40
      2. Validate → assert adjusted_confidence ≈ 0.46 (0.40 * 1.15)
    Expected Result: Weather gets 15% boost
    Evidence: .sisyphus/evidence/task-16-category-weather.txt

  Scenario: Category multiplier reduces finance market confidence
    Tool: Bash (python)
    Steps:
      1. Create signal: category="finance", confidence=0.30
      2. Validate → assert adjusted_confidence ≈ 0.255 (0.30 * 0.85)
    Expected Result: Finance gets 15% reduction
    Evidence: .sisyphus/evidence/task-16-category-finance.txt
  ```

  **Commit**: YES
  - Message: `feat(risk): add category-aware confidence adjustment based on microstructure research`
  - Files: risk_manager.py, config.py
  - Pre-commit: pytest

- [x] 17. Replace Global Trade Lock with Per-Asset Parallel CLOB

  **What to do**:
  The global `_trade_execution_lock` in `strategy_executor.py:34` serializes ALL trades across ALL strategies. This means btc_oracle can't execute while auto_trader is placing an order. Replace with per-asset locks that allow concurrent execution across different markets.

  - Replace `_trade_execution_lock = asyncio.Lock()` with `_trade_locks: Dict[str, asyncio.Lock]` keyed by market token/condition_id
  - In `execute_decision()`, acquire lock for specific market only, not global lock
  - Add `MAX_CONCURRENT_TRADES=3` config to limit total concurrent trade executions
  - Use `asyncio.Semaphore(MAX_CONCURRENT_TRADES)` for global concurrency limit
  - Batch related orders (YES + NO for same market) within single lock acquisition

  **Must NOT do**:
  - Do NOT remove ALL locking — we still need per-asset serialization for order book consistency
  - Do NOT remove idempotency checks — these prevent double-execution
  - Do NOT set MAX_CONCURRENT_TRADES > 5 (API rate limits)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on T14, T15)
  - **Parallel Group**: Wave 5 (after T15)
  - **Blocks**: T18
  - **Blocked By**: T15 (maker mode must have proper locking first)

  **References**:
  - `backend/core/strategy_executor.py:34` — `_trade_execution_lock` (global asyncio.Lock)
  - `backend/core/strategy_executor.py:693` — `execute_decisions()` loops sequentially
  - `backend/core/hft_executor.py:196` — `asyncio.gather` pattern (correct parallel pattern to follow)
  - `backend/config.py` — add `MAX_CONCURRENT_TRADES` config

  **Acceptance Criteria**:
  - [ ] No global trade lock — only per-asset locks
  - [ ] Multiple strategies can execute simultaneously on DIFFERENT markets
  - [ ] Same-market orders still serialized (no race conditions)
  - [ ] Total concurrent trades limited by `MAX_CONCURRENT_TRADES` semaphore
  - [ ] No idempotency violations

  **QA Scenarios**:
  ```
  Scenario: Parallel execution on different markets
    Tool: Bash (python + timing)
    Steps:
      1. Generate 3 signals for 3 different markets
      2. Submit all 3 simultaneously
      3. Measure total execution time
      4. Assert total < 3 * single_execution_time (proves parallelism)
    Expected Result: Execution time reduced by at least 2x vs serial
    Failure Indicators: Total time = 3 * single (still serial)
    Evidence: .sisyphus/evidence/task-17-parallel-execution.txt

  Scenario: Same-market orders still serialized
    Tool: Bash (python)
    Steps:
      1. Generate 3 signals for SAME market
      2. Submit all 3 simultaneously
      3. Verify no race condition (no duplicate orders in Trade table)
    Expected Result: Exactly 3 trades, no duplicates
    Failure Indicators: Duplicate orders or idempotency violations
    Evidence: .sisyphus/evidence/task-17-asset-lock-serialization.txt
  ```

  **Commit**: YES
  - Message: `perf(execution): replace global trade lock with per-asset parallel execution`
  - Files: strategy_executor.py, config.py
  - Pre-commit: pytest

- [x] 18. Add Maker/Taker Role Tracking to Trade Table + Dashboard

  **What to do**:
  `HFTExecutionRecord` has a `role` column, but the main `Trade` table doesn't. This makes it impossible to track maker vs taker P&L over time or optimize strategy mix.

  - Add `role` column to `Trade` model: `role = Column(String(10), default='taker')` with values 'maker'/'taker'
  - Add Alembic migration for the new column
  - In `strategy_executor.execute_decision()`, set `role='taker'` for taker orders
  - In `strategy_executor.execute_quote()`, set `role='maker'` for maker orders (from T15)
  - Add `maker_taker_ratio()` method to dashboard API endpoint `/api/stats/maker-taker`
  - Add frontend Dashboard card showing: Maker P&L, Taker P&L, Maker ratio (% of total trades)
  - Per-strategy maker/taker breakdown

  **Must NOT do**:
  - Do NOT remove existing P&L calculations — add role dimension
  - Do NOT backfill `role` for historical trades (NULL = unknown)

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on T15, T17)
  - **Parallel Group**: Wave 6 (after T17)
  - **Blocks**: F1-F4
  - **Blocked By**: T17 (need role data flowing)

  **References**:
  - `backend/models/database.py:140` — `Trade` class (add `role` column here)
  - `backend/models/database.py:214` — `HFTExecutionRecord` has `role` (reference implementation)
  - `backend/core/trade_forensics.py:19` — `classify_trade_role()` (existing analysis logic)
  - `backend/api/main.py` — add `/api/stats/maker-taker` endpoint
  - `frontend/src/components/` — add MakerTakerCard component

  **Acceptance Criteria**:
  - [ ] `Trade` table has `role` column with default 'taker'
  - [ ] Alembic migration created and applies cleanly
  - [ ] All taker trades record role='taker'
  - [ ] All maker trades (from T15) record role='maker'
  - [ ] `/api/stats/maker-taker` endpoint returns maker/taker P&L split
  - [ ] Frontend shows maker/taker ratio card

  **QA Scenarios**:
  ```
  Scenario: Trade records include role
    Tool: Bash (sqlite3)
    Steps:
      1. Execute a taker trade and a maker trade (paper mode)
      2. Query: SELECT role, COUNT(*) FROM trades GROUP BY role
      3. Assert both 'maker' and 'taker' entries exist
    Evidence: .sisyphus/evidence/task-18-role-tracking.txt

  Scenario: Maker/Taker API endpoint returns P&L split
    Tool: Bash (curl)
    Steps:
      1. Call GET /api/stats/maker-taker
      2. Assert response contains maker_pnl and taker_pnl
      3. Assert maker_pnl + taker_pnl ≈ total_pnl
    Evidence: .sisyphus/evidence/task-18-api-endpoint.txt
  ```

  **Commit**: YES
  - Message: `feat(trades): add maker/taker role tracking and dashboard`
  - Files: database.py, alembic migration, main.py, frontend component
  - Pre-commit: pytest + alembic upgrade head

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run pytest + linter. Review all changed files for: `as any`, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop.
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high` (+ `playwright` skill if UI)
  Start from clean state. Execute EVERY QA scenario from EVERY task. Test cross-task integration. Save evidence.
  Output: `Scenarios [N/N pass] | Integration [N/N] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff. Verify 1:1 — everything in spec was built, nothing beyond spec was built.
  Output: `Tasks [N/N compliant] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

| Commit | Message | Files | Pre-commit |
|--------|---------|-------|------------|
| 1 | `fix(core): apply risk profile at startup` | orchestrator.py | pytest |
| 2 | `fix(strategies): normalize confidence scales` | weather_emos.py, probability_arb.py, cross_market_arb.py, cex_pm_leadlag.py, btc_oracle.py | pytest |
| 3 | `fix(copy_trader,bond_scanner): use YES/NO direction` | copy_trader.py, bond_scanner.py | pytest |
| 4 | `fix(copy_trader): cap position size at risk profile limits` | copy_trader.py | pytest |
| 5 | `feat(risk): make loss floors configurable via risk profile` | risk_profiles.py, config.py, risk_manager.py | pytest |
| 6 | `fix(risk): make daily loss limit percentage-based` | risk_profiles.py, risk_manager.py | pytest |
| 7 | `feat(scheduler): add auto-rehabilitation path` | scheduler.py | pytest |
| 8 | `fix(strategies): re-enable btc_oracle and general_scanner` | DB migration | sqlite3 verify |
| 9 | `perf(scan): reduce scan intervals and use WebSocket-fed cache` | config.py, scheduling_strategies.py | pytest |
| 10 | `feat(risk): add NO-bias weighting for longshot contracts` | risk_manager.py, risk_profiles.py, config.py | pytest |
| 11 | `feat(execution): wire HFT pipeline to main strategies` | strategy_executor.py, polymarket_clob.py, scheduling_strategies.py | pytest |
| 12 | `feat(strategy): implement market maker QUOTE handler` | strategy_executor.py, market_maker.py, database.py | pytest |
| 13 | `feat(risk): add category-aware confidence adjustment` | risk_manager.py, config.py | pytest |
| 14 | `perf(execution): replace global trade lock with per-asset parallel execution` | strategy_executor.py, config.py | pytest |
| 15 | `feat(trades): add maker/taker role tracking and dashboard` | database.py, alembic migration, main.py, frontend | pytest + alembic |
| 16 | `fix(core): fix BotState race condition with WAL mode and proper locking` | database.py, strategy_executor.py, scheduler.py, 47 files | pytest |
| 17 | `fix(scheduler): register nightly_archive_job and wire NightlyReview to KG` | scheduler.py, nightly_review.py | pytest |
| 18 | `fix(data): clean up blockchain_indexer/ClobEvent stale references` | models/database.py, registry.py | pytest |

---

## Success Criteria

### Verification Commands
```bash
# 1. Profile applied
python -c "from backend.config import settings; assert settings.DAILY_DRAWDOWN_LIMIT_PCT == 0.40"

# 2. Confidence normalized
python -c "from backend.modules.scanners.weather_emos import *; # assert confidence(0.05) >= 0.50"

# 3. No direction="buy" in strategies
grep -r 'direction.*=.*"buy"' backend/strategies/ backend/modules/  # Should return 0

# 4. Paper trades executing within 1 hour
sqlite3 tradingbot.db "SELECT COUNT(*) FROM trade_attempts WHERE status='EXECUTED' AND created_at > datetime('now', '-1 hour')"

# 5. No drawdown breaker on paper mode
sqlite3 tradingbot.db "SELECT COUNT(*) FROM trade_attempts WHERE reason_code='REJECTED_DRAWDOWN_BREAKER' AND mode='paper' AND created_at > datetime('now', '-1 hour')"

# 6. Scan interval ≤ 10s
python -c "from backend.config import settings; assert settings.SCAN_INTERVAL_SECONDS <= 10"

# 7. NO-bias applied at longshot prices
python -c "from backend.core.risk_manager import *; # NO @ 5¢ gets +15% confidence"

# 8. HFT path latency < 5s
# Measure signal → order time via timing log

# 9. Market maker producing QUOTE orders
sqlite3 tradingbot.db "SELECT COUNT(*) FROM trades WHERE role='maker' AND created_at > datetime('now', '-1 hour')"

# 10. Category confidence applied
python -c "from backend.config import settings; assert settings.CATEGORY_CONFIDENCE_MULTIPLIER['weather'] > 1.0"
```

### Final Checklist
- [ ] RISK_PROFILE=extreme actually applied at startup
- [ ] 5+ strategies producing confidence ≥ 0.20 (extreme threshold)
- [ ] copy_trader generates valid YES/NO direction
- [ ] copy_trader position size ≤ MAX_TRADE_SIZE
- [ ] Loss floors match extreme profile (-40%/-60%)
- [ ] Daily loss limit scales with bankroll
- [ ] Disabled strategies have rehabilitation path
- [ ] Paper trades executing within 1 hour of restart
- [ ] Live high-confidence signals (0.80+) not blocked by drawdown
- [ ] Scan interval ≤ 10 seconds
- [ ] NO-bias weight applied at longshot prices (≤20¢)
- [ ] HFT path completes signal → order in < 5 seconds
- [ ] Market maker QUOTE handler producing resting limit orders
- [ ] Category confidence multipliers applied (weather +15%, finance -15%)
- [ ] Per-asset locks replace global trade lock
- [ ] Trade table includes maker/taker role field