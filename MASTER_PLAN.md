# PolyEdge Master Plan — Consolidated
> Single source of truth. Replaces: COMPREHENSIVE_INTEGRATION_PLAN.md, PNL_WALLET_FIX_PLAN.md, EXHAUSTIVE_AUDIT.md

## North Star
Zero hardcoded values. Zero unwired features. Zero dead code. Everything configurable with sensible defaults.

---

## Phase 1: Foundation — Config & Constants (Day 1)

### 1.1 Create `backend/constants.py`
Extract all contract addresses, chain IDs, and zero addresses into one file:
- CTF_ADDRESS, USDC_E_ADDRESS, USDC_NATIVE_ADDRESS, PUSD_ADDRESS
- CHAIN_IDS: Polygon=137, Base=8453, Gnosis=100, Arbitrum=42161, Aster=1666
- ZERO_ADDRESS
- Import everywhere, delete duplicates from auto_redeem.py, proxy_finder.py, wallet_scanner.py, clob_event_indexer.py

### 1.2 Consolidate ConfigRegistry
- Add 57 missing env vars (WALLET_PRIVATE_KEY, RISK_PROFILE, KALSHI_API_KEY, SAFETY_*, etc.)
- Add crash-risk fields: AGI_NIGHTLY_REVIEW_OUTPUT_DIR, AGI_NIGHTLY_REVIEW_LOOKBACK_DAYS, GEMINI_ENABLED
- Remove 20+ duplicate fields (AUTO_REDEEM_INTERVAL_SECONDS x2, USDC_*_TOKENS, RSS_FEEDS, HFT_*_CONFIG)
- Fix GROQ_MODEL mismatch (config says 8b, provider uses 70b)
- Fix CLAUDE_MODEL vs ANTHROPIC_MODEL naming
- Delete dead Settings class (never instantiated)

### 1.3 Sync .env.example
Regenerate from ConfigRegistry defaults. Fix 15+ mismatched values (bond scanner, market maker, order executor weights).

### 1.4 Create `backend/fee_config.py`
Single source of truth for all fee rates:
```python
TAKER_FEE_RATE = 0.01          # Polymarket actual
MAKER_FEE_RATE = 0.00
KALSHI_TAKER_FEE_RATE = 0.07
KALSHI_MAKER_FEE_RATE = 0.0175
FEE_USE_STORED = True          # Prefer trade.fee
FEE_FALLBACK_RATE = 0.01
```
Replace all 8+ hardcoded fee locations.

### 1.5 Create `backend/risk_config.py`
Single source of truth for risk parameters:
```python
DEFAULT_KELLY_FRACTION = 0.25
DEFAULT_MAX_DRAWDOWN_PCT = 0.20
DEFAULT_MAX_POSITION_USD = 50.0
DEFAULT_MAX_DAILY_LOSS_USD = 100.0
INITIAL_BANKROLL = 1000.0
```
Replace all 7+ kelly defaults, 6+ bankroll defaults, 5+ drawdown limits.

---

## Phase 2: PnL Unification (Day 2)

### 2.1 Unified `calculate_pnl()`
Refactor `backend/core/settlement/settlement_helpers.py`:
- Use `FEE_USE_STORED` / `FEE_FALLBACK_RATE` from config
- Use `SETTLEMENT_USE_FILLED` to prefer filled_size/fill_price
- No hardcoded `fee_bps = 100`

### 2.2 Fix BTC 5-min Settlement
`backend/core/settlement/settlement.py:84-108`: Replace inline 2% formula with `calculate_pnl()` call.

### 2.3 Fix Bankroll Double-Count
`backend/core/settlement/settlement.py:825`: Remove `- fee` term (PnL already includes fee).

### 2.4 Fix Genome Formula
`backend/repositories/genome_repository.py:249-274`: Replace inline formula with `calculate_pnl()`.

### 2.5 Fix Shadow Runner
`backend/application/strategy/shadow_runner.py:118-134`: Replace inline formula with `calculate_pnl()`.

### 2.6 Fix Backtest Commission
Replace hardcoded `commission_bps=200` and `commission=0.002` with config references.

### 2.7 Migration
Run `recalculate_expired_pnl.py` to fix historical trades.

---

## Phase 3: Wire Wallet System (Day 3)

### 3.1 Config
Add `WALLET_ENCRYPTION_KEY`, `WALLET_ROUTER_ENABLED`, `COPY_POLICY_ENABLED` to ConfigRegistry.

### 3.2 Instantiate WalletRouter
In `backend/api/lifespan.py`: Create `WalletRouter(db_session, fernet_key)` at startup.

### 3.3 Wire to AutoTrader
Pass `wallet_router` to `AutoTrader` constructor. The conditional at `auto_trader.py:164` activates.

### 3.4 Wire CopyPolicyEngine
Connect between copy-trade signal generation and AutoTrader execution.

### 3.5 Frontend: Dynamic Strategy List
`WalletMatrix.tsx:39`: Replace hardcoded `['btc_oracle', 'market_maker', 'line_movement_detector']` with API fetch.

### 3.6 Frontend: Create Wallet/Allocation UI
Add forms for creating TradingWallet and WalletAllocation rows.

---

## Phase 4: Wire AGI System (Day 4)

### 4.1 Wire AGI Nodes
In orchestrator lifespan: `node_registry.auto_discover("backend.agi.nodes")` — activates 12 modules.

### 4.2 Wire AGI Graphs
Register forensics_graph, market_analysis_graph, strategy_evolution_graph with GraphEngine.

### 4.3 Wire AGI Research
Import github_scanner, paper_scanner, competitor_monitor, whale_tracker in agi_jobs.py.

### 4.4 Wire RL Trainer
Add nightly scheduled job for `backend.rl.trainer`.

### 4.5 Wire Data Feeds
Import `backend.data.providers` and `backend.data.crypto_feeds` in data pipeline.

### 4.6 Wire Notification Providers
Register Slack/Discord/Webhook in notification registry (Telegram only wired now).

---

## Phase 5: Wire Strategies (Day 5)

### 5.1 Dynamic Strategy Execution
Scheduler iterates `StrategyConfig` from DB instead of hardcoding `["btc_oracle", "weather_emos", "copy_trader"]`.

### 5.2 Wire Orphaned Strategies
Ensure cex_pm_leadlag, bond_scanner, market_maker, fingerprint, replication, opportunity_detector are in execution loop.

### 5.3 Wire Backtesting Framework
Refactor `backend/api/backtest.py` to use `backend.backtesting.registry` instead of reimplementing.

---

## Phase 6: Consolidate Duplicates (Day 6)

### 6.1 Decide Canonical Paths
For 29 duplicate module pairs, keep subdirectory versions (core/learning/, core/risk/, core/wallet/, core/settlement/, core/scheduling/).

### 6.2 Update Imports
Change all production imports to use canonical paths.

### 6.3 Delete Dead Copies
Remove top-level duplicates: core/calibration.py, core/risk_manager.py, core/scheduler.py, etc.

---

## Phase 7: Frontend Wiring (Day 7)

### 7.1 Wire 8 Orphaned Components
VenueMonitor, PluginStatusPanel, SandboxMonitor, CalibrationPanel, MicrostructurePanel, EdgeDistribution, AGIGraphRunner, WeatherPanel → Dashboard tabs.

### 7.2 Route 16 Dead Pages
Either register in App.tsx routes or remove the files.

### 7.3 WalletMatrix Enhancements
Dynamic strategy list, create wallet form, create allocation form.

---

## Phase 8: Verification (Day 8)

### 8.1 Unit Tests
- `calculate_pnl()` with stored vs calculated fee
- WalletRouter fan-out with config
- All providers register
- All strategies execute

### 8.2 Integration Tests
- PnL matches Polymarket data (btc-5m-1779370200: $19.49)
- Wallet fan-out produces correct ChildOrders
- No double-counting in bankroll

### 8.3 Full Suite
- `pytest tests/` — target 0 failures, 0 errors
- `grep -rn "0.02" backend/ --include="*.py"` — no hardcoded fee rates remain
- `grep -rn "fee_bps" backend/ --include="*.py"` — no inline fee constants

### 8.4 Smoke Test
- Start orchestrator, verify all providers register
- Trigger a signal, verify fan-out
- Check settlement, verify PnL accuracy

---

## Files Modified (Estimated)

| Phase | New Files | Modified Files | Deleted Files |
|---|---|---|---|
| 1 | 3 (constants, fee_config, risk_config) | 50+ (config, all clients, all providers) | 0 |
| 2 | 0 | 5 (settlement, genome, shadow, backtest) | 0 |
| 3 | 0 | 4 (lifespan, auto_trader, orchestrator, WalletMatrix) | 0 |
| 4 | 0 | 4 (lifespan, agi_jobs, orchestrator, scheduler) | 0 |
| 5 | 0 | 3 (scheduler, api/backtest, strategy_executor) | 0 |
| 6 | 0 | 29 (import updates) | 29 (dead copies) |
| 7 | 0 | 10 (App.tsx, Dashboard, 8 components) | 0 |
| 8 | 0 | 0 | 0 |
| **Total** | **3** | **~105** | **~29** |

---

## Dependencies Between Phases

```
Phase 1 (Config) ← ALL other phases depend on this
    ↓
Phase 2 (PnL) ← Phase 3 (Wallet) needs fee config
    ↓
Phase 3 (Wallet) ← Phase 5 (Strategies) needs wallet router
    ↓
Phase 4 (AGI) ← independent, can parallel with 3
    ↓
Phase 5 (Strategies) ← needs Phase 3
    ↓
Phase 6 (Duplicates) ← needs all imports stable
    ↓
Phase 7 (Frontend) ← needs backend APIs stable
    ↓
Phase 8 (Verification) ← needs everything done
```

---

## Risk Mitigation

| Risk | Mitigation |
|---|---|
| Breaking existing trades | Run PnL migration in dry-run first |
| Breaking strategy execution | Keep old scheduler as fallback |
| Breaking wallet encryption | Test Fernet encrypt/decrypt before deploying |
| Breaking AGI startup | Wrap auto_discover in try/except |
| Breaking imports | Run `python -c "import backend"` after each phase |
