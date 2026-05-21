# PolyEdge Exhaustive Audit — Living Document
> Updated: 2026-05-22

## Summary
- **60+ files** with hardcoded magic numbers
- **57 env vars** bypass ConfigRegistry
- **15+ dead Settings fields** (will crash at runtime)
- **12 AGI nodes** — zero production imports
- **29 duplicate module pairs** — confusion about canonical
- **7 strategies** registered but never executed
- **8 frontend components** — complete but unreachable
- **16 frontend pages** — dead routes

---

## Part 1: Hardcoded Values → Config

### 1.1 Fee Rates (CRITICAL — 4+ conflicting sources)

| Location | Value | Should Be |
|---|---|---|
| `config.py:994` TAKER_FEE_RATE | 0.02 | 0.01 (Polymarket actual) |
| `config.py:317` PAPER_CLOB_FEE_RATE | 0.02 | Reference TAKER_FEE_RATE |
| `settlement_helpers.py:764` fee_bps | 100 (1%) | Reference config |
| `kalshi_provider.py:29-30` | 0.07/0.0175 | Add KALSHI_TAKER_FEE_RATE to config |
| `paper_provider.py:30` | 100 bps | Reference config |
| `negrisk_arb.py:12` | 0.02 | Reference config |
| `pybroker_backtest.py:37` | 200 bps | Reference config |
| `backtesting_py_adapter.py:71` | 0.002 | Reference config |

**Fix**: Single `TAKER_FEE_RATE` in ConfigRegistry, all others reference it.

### 1.2 Kelly Fraction (7+ conflicting defaults)

| Location | Value |
|---|---|
| `api/backtest.py:43` | 0.0625 |
| `core/backtest_engine.py:77` | 0.0625 |
| `core/walk_forward.py:57` | 0.05 |
| `modules/scanners/weather_emos.py:276` | 0.15 |
| `strategies/hft_scalper.py:180` | 0.20 |
| `strategies/template_base.py:53` | 0.30 |
| `config_extensions.py:9` | 0.50 max |

**Fix**: Single `DEFAULT_KELLY_FRACTION` in ConfigRegistry with per-strategy overrides.

### 1.3 Bankroll (100 vs 1000 inconsistency)

| Location | Value |
|---|---|
| `config.py:875` INITIAL_BANKROLL | 100.0 |
| `scripts/seed_settings.py:9` | 1000.0 |
| `core/backtest_engine.py:76` | 100.0 |
| `core/backtesting.py:36` | 1000.0 |
| `core/strategy_composer.py:180` | 1000.0 |
| `models/database.py:503-557` | 100.0 (6 columns) |

**Fix**: Single `INITIAL_BANKROLL` in ConfigRegistry, all reference it.

### 1.4 Contract Addresses (duplicated 5+ places)

| Address | Locations |
|---|---|
| CTF `0x4D97DC...` | config.py:855, auto_redeem.py:32, validate_ctf_v2.py:39 |
| USDC.e `0x2791Bc...` | config.py:859, auto_redeem.py:33, 3 more |
| PUSD `0xC011a7...` | config.py:861, proxy_finder.py:26, wallet_scanner.py:25 |

**Fix**: Create `backend/constants.py`, import everywhere.

### 1.5 URLs (60+ hardcoded)

- Polymarket: 5 URLs in config, duplicated in 3 config classes
- CEX: Binance, Bybit, Coinbase, Kraken URLs hardcoded
- DEX: Lighter, Ostium, Aster, Hyperliquid URLs hardcoded
- AGI research: GitHub, ArXiv, Polymarket docs URLs hardcoded
- Monitoring: Datadog, CloudWatch URLs hardcoded

**Fix**: All URLs in ConfigRegistry with defaults.

### 1.6 Time Values (30+ hardcoded seconds)

- Circuit breaker timeouts: 60-300s in 15+ places
- Cache TTLs: 300-86400s in 20+ places
- Rate limits: 60-600s in 10+ places

**Fix**: Centralize in ConfigRegistry.

### 1.7 Scoring Weights (magic formulas)

- Performance attributor: 0.40/0.30/0.30, 0.30/0.40/0.30
- Whale scoring: 0.35/0.30/0.20/0.15
- Wash trade: 0.30/0.20/0.20/0.15/0.15
- Weather signals: 0.70/0.30
- Training: edge*3 + sentiment*0.5

**Fix**: All weights in ConfigRegistry.

---

## Part 2: Config Gaps

### 2.1 Critical — Will Crash at Runtime

| Field | Location | Issue |
|---|---|---|
| `AGI_NIGHTLY_REVIEW_OUTPUT_DIR` | Settings only, not ConfigRegistry | `AttributeError` at runtime |
| `AGI_NIGHTLY_REVIEW_LOOKBACK_DAYS` | Settings only | `AttributeError` at runtime |
| `GEMINI_ENABLED` | Settings only | Always `False` via `getattr` |
| `KALSHI_API_KEY` | Read via `os.getenv` | Different from `KALSHI_API_KEY_ID` in config |

### 2.2 High — Security/Correctness

| Field | Issue |
|---|---|
| `RISK_PROFILE` | Read via `os.environ.get`, not in ConfigRegistry |
| `WALLET_PRIVATE_KEY` | Read via `os.getenv` in 4 clients, not in ConfigRegistry |
| `LLM_OPENAI_API_KEY` | Read via `getattr`, always `None` |
| `CLAUDE_MODEL` vs `ANTHROPIC_MODEL` | Different names for same concept |
| `DASHBOARD_PASSWORD` | Set in .env, no code reads it |
| `AUTH_TOKEN` | Set in .env, no code reads it |

### 2.3 Duplicate Fields (20+)

- `AUTO_REDEEM_INTERVAL_SECONDS` declared twice (lines 573, 688)
- `USDC_E_ADDRESS` vs `USDC_E_ADDRESS_TOKENS`
- `RSS_FEED_URLS` vs `RSS_FEEDS`
- `BK_BRAIN_URL` vs `BRAIN_API_URL`
- `HFT_*` vs `HFT_*_CONFIG` (10+ duplicates)

### 2.4 .env.example Out of Sync (15+ fields)

Bond scanner, market maker, order executor weights, paper slippage, forensics — all have different defaults in .env.example vs ConfigRegistry.

---

## Part 3: Unwired Features

### 3.1 CRITICAL — AGI System (19 dead modules)

| Module | Count | Status |
|---|---|---|
| `backend/agi/nodes/` | 12 files | Zero production imports |
| `backend/agi/research/` | 4 files | Zero production imports |
| `backend/agi/graphs/` | 3 files | Zero production imports |

**Fix**: Call `node_registry.auto_discover()` in orchestrator lifespan.

### 3.2 HIGH — Strategies Never Executed (7 strategies)

| Strategy | Issue |
|---|---|
| `cex_pm_leadlag` | Zero production imports |
| `bond_scanner` | Only string reference |
| `fingerprint` | Only CLI import |
| `replication` | Only CLI import |
| `opportunity_detector` | Only CLI import |
| `order_executor` | Only copy_trader import |
| `market_maker` | Only string reference |

**Fix**: Scheduler should iterate `StrategyConfig` from DB, not hardcode names.

### 3.3 HIGH — Duplicate Modules (29 pairs)

Top-level `core/` files duplicate subdirectory equivalents:
- `core/calibration.py` vs `core/learning/calibration.py`
- `core/risk_manager.py` vs `core/risk/risk_manager.py`
- `core/scheduler.py` vs `core/scheduling/scheduler.py`
- 26 more pairs...

**Fix**: Decide canonical path, delete the other.

### 3.4 HIGH — Dead Backtesting Framework

`backend/backtesting/` (registry, adapters, metrics, runners) — zero production imports. API endpoint `backend/api/backtest.py` reimplements everything.

**Fix**: Refactor API to use `backend.backtesting.registry`.

### 3.5 HIGH — RL Trainer Never Runs

`backend/rl/trainer.py` — zero production imports. No scheduled job, no API endpoint.

**Fix**: Add as nightly scheduled job.

### 3.6 MEDIUM — Dead Frontend (16 pages, 8 components)

Pages: Backtest, DecisionLog, EdgeTracker, MarketIntel, PendingApprovals, Settlements, TradingTerminal, WhaleTracker — not in App.tsx routes.

Components: VenueMonitor, PluginStatusPanel, SandboxMonitor, CalibrationPanel, MicrostructurePanel, EdgeDistribution, AGIGraphRunner, WeatherPanel — zero imports.

**Fix**: Wire into Dashboard/Admin tabs or remove.

### 3.7 MEDIUM — Dead Data Providers

- `backend/data/providers/` package — zero strategy imports
- `backend/data/crypto_feeds/` — 5 providers registered but unused
- Notification: Slack/Discord/Webhook providers — only Telegram wired

### 3.8 MEDIUM — WalletRouter Never Instantiated

N:N wallet system fully built but WalletRouter never created at startup. AutoTrader always receives `wallet_router=None`.

**Fix**: Instantiate in lifespan, pass to AutoTrader.

---

## Part 4: Execution Plan

### Phase 1: Config Consolidation (Day 1)
1. Create `backend/constants.py` for contract addresses, chain IDs
2. Add 57 missing env vars to ConfigRegistry
3. Remove duplicate fields (20+)
4. Fix .env.example to match ConfigRegistry
5. Delete dead `Settings` class

### Phase 2: Fee/PnL Unification (Day 2)
1. Single `TAKER_FEE_RATE` = 0.01 in config
2. Single `DEFAULT_KELLY_FRACTION` in config
3. Single `INITIAL_BANKROLL` in config
4. Unified `calculate_pnl()` using config
5. Fix BTC 5-min, genome, shadow formulas
6. Fix bankroll double-count

### Phase 3: Wire AGI System (Day 3)
1. `node_registry.auto_discover()` in lifespan
2. Register graphs with GraphEngine
3. Wire research modules into AGI jobs
4. Wire RL trainer as nightly job

### Phase 4: Wire Wallet System (Day 4)
1. Add `WALLET_ENCRYPTION_KEY` to config
2. Instantiate WalletRouter in lifespan
3. Pass to AutoTrader
4. Wire CopyPolicyEngine

### Phase 5: Wire Strategies (Day 5)
1. Scheduler iterates StrategyConfig from DB
2. Remove hardcoded strategy name lists
3. Wire orphaned strategies into execution loop

### Phase 6: Consolidate Duplicates (Day 6)
1. Decide canonical paths for 29 duplicate pairs
2. Update all imports
3. Delete dead copies

### Phase 7: Frontend Wiring (Day 7)
1. Wire 8 orphaned components into Dashboard tabs
2. Fix WalletMatrix dynamic strategy list
3. Add create wallet/allocation UI
4. Remove or route 16 dead pages

### Phase 8: Verification (Day 8)
1. Full test suite — target 0 failures
2. Verify all providers register
3. Verify all strategies execute
4. Verify PnL matches Polymarket
5. Verify wallet fan-out works
