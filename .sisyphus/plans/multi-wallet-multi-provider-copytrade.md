# Multi-Wallet × Multi-Provider × Copy-Trade Plan

## TL;DR

> **Quick Summary**: Extend 1ai-poly-trader (post PR #95 merge) with three interlocking features:
> (1) N↔N wallet-strategy allocation matrix with weighted order fan-out,
> (2) full six-platform provider plugin conformance to the `MarketProviderPlugin` abstraction — Polymarket, Kalshi, **predict.fun (Azuro)**, **bookmaker.xyz (Azuro)**, **limitless.exchange**, and **sx.bet**,
> (3) a copy-trade subsystem with on-chain leaderboard and internal cross-strategy signal sources, governed by per-source `CopyPolicy`.
>
> **Deliverables**:
> - `TradingWallet` ORM + `WalletAllocation` ORM + `CopyPolicy` ORM + Alembic migration
> - `WalletRouter` service (weighted fan-out, min-size guard, per-wallet circuit breaker)
> - `PolymarketProvider` + `KalshiProvider` plugin classes conforming to `MarketProviderPlugin`
> - `AzuroClient` shared GraphQL/Web3 client + `PredictFunProvider` + `BookmakerXyzProvider` plugins
> - `LimitlessClient` REST/WS client + `LimitlessProvider` plugin
> - `SXBetClient` REST client + `SXBetProvider` plugin
> - `CopySource` ABC + `LeaderboardCopySource` + `InternalMirrorSource` implementations
> - `CopyPolicyEngine` (filter/scale/validate per policy)
> - Extended `AutoTrader` fan-out hook + `BankrollAllocator` per-wallet cap
> - REST API extensions: wallet-allocation CRUD, copy-policy CRUD, copy-trade mutations
> - Frontend: WalletMatrix panel, CopyPolicy panel, ProviderStatus panel (6 providers)
> - 1 Alembic migration covering all new tables
>
> **Estimated Effort**: XL (increased from original — +4 providers adds ~8 tasks)
> **Parallel Execution**: YES — 6 waves (Wave 2 expanded)
> **Critical Path**: Task 1 → Task 3 → Task 7a → Task 8 → Task 14 → Task 20 → Task 23 → F1-F4

---

## Context

### Original Request
> "help me make a high quality and comprehensive planning to make sure this codebase supports: multi wallet per strategy / multi market provider / copy trades / this new features will be using this PR as the base, so it require this PR to be merged first: https://github.com/oyi77/1ai-poly-trader/pull/95"
>
> **Updated scope (post-plan review)**: Add four additional market providers — predict.fun, limitless.exchange, bookmaker.xyz, sx.bet — to the provider plugin system.

### Interview Summary
**Key Discussions**:
- PR #95 (plugin-system-refactoring) must be merged before any work begins; plan assumes its contracts are available
- `WalletConfig` (line 727 `database.py`) is a watch-list (address + metadata only), NOT a credential store — a new `TradingWallet` ORM is required for credentials
- N↔N means every strategy can fan-out to multiple wallets proportional to allocation weight; per-wallet min-size guard (~$1 on PM)
- Provider abstraction = PM + Kalshi + predict.fun + bookmaker.xyz + limitless.exchange + sx.bet conform to `MarketProviderPlugin`
- Copy sources = on-chain PM leaderboard + internal cross-strategy mirroring; each source has its own `CopyPolicy` (size cap, confidence floor, cooldown)
- Copy-trade signals enter the standard pipeline (risk check → sandbox gate → order fan-out)
- `BotState.active_wallet` becomes a fallback/view (highest-weight wallet), not a routing source

**Research Findings — New Providers**:
- **predict.fun** — Frontend built on **Azuro Protocol** (Gnosis Chain / Polygon). Data via The Graph GraphQL subgraph (`https://api.thegraph.com/subgraphs/name/azuro-protocol/azuro-subgraph-xdai`). Order placement requires EVM wallet + smart contract call (no REST trading API). Auth: wallet address + Web3 signing. Requires `web3` Python library + RPC node URL.
- **bookmaker.xyz** — Also built on **Azuro Protocol** (same on-chain contracts and GraphQL endpoint as predict.fun). Share a single `AzuroClient`; distinguish providers by frontend URL / `platform` tag only.
- **limitless.exchange** — CLOB + AMM prediction market on **Base blockchain**. REST API: `https://api.limitless.exchange` (Swagger at `/api-v1`). WebSocket: `wss://ws.limitless.exchange`. Public reads (markets, orderbook) need no auth. Trading requires EIP-712 wallet signature.
- **sx.bet** — Peer-to-peer sports prediction market on **Polygon**. REST API: `https://api.sx.bet`. Public reads (sports, leagues, fixtures, markets, orders) need no auth. Order placement requires EIP-712 wallet signature. Supported operations: maker orders (post) + taker fills.

**Research Findings — Shared Infrastructure**:
- predict.fun + bookmaker.xyz share all on-chain data — one `AzuroClient` wraps The Graph GraphQL queries and serves both providers
- limitless.exchange and sx.bet each need a dedicated REST client; both use async `httpx` + EIP-712 signing
- EIP-712 signing for limitless.exchange and sx.bet: use `eth_account` from `web3` library (already a transitive dependency via `py-clob-client`)
- New `chain` values for `TradingWallet.chain`: extend enum to `"polymarket" | "kalshi" | "azuro" | "limitless" | "sxbet"`
- ENV vars required: `AZURO_GRAPH_URL`, `AZURO_RPC_URL`, `AZURO_CHAIN_ID`, `LIMITLESS_API_URL`, `LIMITLESS_WS_URL`, `SXBET_API_URL`, `WEB3_PRIVATE_KEY_AZURO`, `WEB3_PRIVATE_KEY_LIMITLESS`, `WEB3_PRIVATE_KEY_SXBET`

### Metis Review
**Identified Gaps** (addressed):
- Secret storage for wallet credentials: defaulting to Fernet symmetric encryption (env key `WALLET_FERNET_KEY`), same pattern as existing API key storage
- On-chain leader discovery: PM Data API `/data-api/v2/activity?user={addr}` + leaderboard endpoint; polled every 5 min via scheduler
- Copy latency budget: best-effort async; no hard SLA; `CopyPolicy.max_delay_seconds` soft gate
- `BotState.active_wallet` migration: additive only — existing field preserved as fallback
- **[Added v2]** predict.fun + bookmaker.xyz integration: Azuro Protocol only exposes read-only GraphQL; order placement requires Web3 smart contract transactions — `is_read_only` flag on providers that cannot yet execute live orders
- **[Added v2]** `TradingWallet.chain` must be an enum-like string to support all 5 chains; validated at ORM level; API docs updated to reflect all valid chain values
- **[Added v2]** The Graph free tier rate-limits at 1000 req/day — `AzuroClient` must implement local TTL cache (default 60 s) and respect `Retry-After`
- **[Added v2]** `web3` library is already a transitive dependency (`py-clob-client → web3`); no new top-level dependency needed; verify with `pip show web3`

---

## Work Objectives

### Core Objective
Add N↔N wallet routing, six-platform provider plugin conformance (PM, Kalshi, predict.fun, bookmaker.xyz, limitless.exchange, sx.bet), and a copy-trade subsystem to the post-PR-#95 codebase without breaking existing single-wallet, single-provider, or manual-trade flows.

### Concrete Deliverables
- `backend/models/trading_wallet.py` — `TradingWallet`, `WalletAllocation`, `CopyPolicy` ORMs
- `alembic/versions/XXXX_multi_wallet_copytrade.py` — migration for all 3 new tables
- `backend/core/wallet_router.py` — `WalletRouter` (weighted fan-out, circuit breaker per wallet)
- `backend/plugins/providers/polymarket_provider.py` — `PolymarketProvider(MarketProviderPlugin)`
- `backend/plugins/providers/kalshi_provider.py` — `KalshiProvider(MarketProviderPlugin)`
- `backend/clients/azuro_client.py` — shared Azuro GraphQL/Web3 client (TTL cache, rate-limit guard)
- `backend/plugins/providers/predict_fun_provider.py` — `PredictFunProvider(MarketProviderPlugin)` — read+order via Azuro
- `backend/plugins/providers/bookmaker_xyz_provider.py` — `BookmakerXyzProvider(MarketProviderPlugin)` — thin Azuro wrapper
- `backend/clients/limitless_client.py` — async REST + WS client for limitless.exchange
- `backend/plugins/providers/limitless_provider.py` — `LimitlessProvider(MarketProviderPlugin)`
- `backend/clients/sxbet_client.py` — async REST client for sx.bet
- `backend/plugins/providers/sxbet_provider.py` — `SXBetProvider(MarketProviderPlugin)`
- `backend/core/copy_engine.py` — `CopySource` ABC, `LeaderboardCopySource`, `InternalMirrorSource`, `CopyPolicyEngine`
- `backend/core/auto_trader.py` — extended with `WalletRouter` fan-out
- `backend/core/bankroll_allocator.py` — extended with per-wallet allocation awareness
- `backend/api/wallet_allocations.py` — CRUD for `TradingWallet` + `WalletAllocation`
- `backend/api/copy_policy.py` — CRUD for `CopyPolicy`
- `backend/api/copy_trading.py` — extended with mutation routes (enable/disable source, update policy)
- `frontend/src/components/WalletMatrix.tsx` — N↔N allocation grid
- `frontend/src/components/CopyPolicyPanel.tsx` — per-source policy editor
- `frontend/src/components/ProviderStatusPanel.tsx` — live status for all 6 providers
- `docs/architecture/adr-007-multi-wallet-routing.md`
- `docs/architecture/adr-008-copy-trade-architecture.md`
- `docs/architecture/adr-009-extended-provider-integration.md` — Azuro/limitless/sxbet integration decisions
- `AGENTS.md` updates (root + backend/ + frontend/)

### Definition of Done
- [ ] `pytest` passes with 0 failures from project root
- [ ] `cd frontend && npm run build` exits 0
- [ ] All new REST endpoints return 200/201 on happy path (verified via curl)
- [ ] `WalletRouter` fan-out confirmed: 2 wallets × 1 signal → 2 child orders in DB
- [ ] All 6 providers listed in `GET /api/v1/markets/providers`
- [ ] Copy signal from leaderboard source creates `CopyTraderEntry` row
- [ ] `IMMUTABLE_SAFETY_RULES` not modified anywhere in diff
- [ ] `AzuroClient` health check returns `True` (GraphQL endpoint reachable)
- [ ] `LimitlessProvider` and `SXBetProvider` listed with `is_read_only=False` (live order capable)

### Must Have
- `TradingWallet` stores encrypted private key (Fernet); key never logged
- Per-wallet allocation weight validated: sum of weights per strategy must not exceed 1.0
- `WalletRouter` respects `IMMUTABLE_SAFETY_RULES` and `BankrollAllocator` caps per wallet
- Min-order guard: child order < $1 (PM/Azuro/Limitless/SXBet) or $0.01 (Kalshi) → skip + log, never reject parent signal
- `CopyPolicy` gates: size cap, confidence floor, max_delay_seconds, enabled flag
- All copy signals pass through `SandboxManager.run_strategy_in_sandbox()` validation gate
- Existing `WalletConfig` (watch-list) untouched — no column drops or renames
- Existing `BotState.active_wallet` preserved as fallback
- `AzuroClient` implements TTL cache (default 60 s) — do not hammer The Graph free tier
- `LimitlessProvider` and `SXBetProvider` must expose `is_read_only=False` to confirm live-order capability
- `PredictFunProvider` and `BookmakerXyzProvider` must expose `is_read_only=True` until smart-contract order execution is fully implemented and tested

### Must NOT Have (Guardrails)
- No modification to `IMMUTABLE_SAFETY_RULES` dict
- No removal of existing single-wallet code paths (additive only)
- No hardcoded private keys or secrets in source files
- No direct DB writes bypassing ORM layer
- No AI slop: no `data`/`result`/`item`/`temp` variable names, no empty except blocks, no `as Any` casts
- No `WalletConfig` column drops or schema changes (read-only from new code)
- No synchronous HTTP calls inside signal hot path (use async throughout)
- No uncached calls to The Graph API in hot paths (must go through `AzuroClient.cached_query()`)
- No new Python top-level dependencies unless strictly necessary (`web3` and `eth_account` are already available)

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: YES (pytest + pytest.ini at root; vitest/playwright in frontend)
- **Automated tests**: Tests-after (implementation first, then test tasks in same wave or next)
- **Framework**: `pytest` (backend), `vitest` (frontend unit), `playwright` (e2e)

### QA Policy
Every task includes agent-executed QA scenarios. Evidence saved to `.sisyphus/evidence/task-{N}-{slug}.{ext}`.

- **API endpoints**: `curl` — assert status + response shape
- **ORM/DB**: `bun`/`python -c` REPL — import, create row, assert columns
- **Frontend**: Playwright — navigate, interact, assert DOM
- **Integration**: `pytest` run scoped to new test files

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation — start immediately, all independent):
├── Task 1:  TradingWallet + WalletAllocation + CopyPolicy ORMs         [quick]
├── Task 2:  Alembic migration for all 3 new tables                     [quick]
├── Task 3:  CopySource ABC + CopyPolicy dataclass                      [quick]
├── Task 4:  ADR-007 multi-wallet routing doc                           [writing]
├── Task 5:  ADR-008 copy-trade architecture doc                        [writing]
└── Task 5b: ADR-009 extended provider integration doc                  [writing]

Wave 2 (Core provider plugins + wallet router — after Wave 1):
├── Task 6:  WalletRouter (weighted fan-out, min-size guard, CB)        [unspecified-high]
├── Task 7:  PolymarketProvider plugin (MarketProviderPlugin)           [unspecified-high]
├── Task 7a: KalshiProvider plugin (MarketProviderPlugin)               [unspecified-high]
├── Task 7b: AzuroClient shared client (GraphQL + TTL cache)            [unspecified-high]
├── Task 7c: PredictFunProvider plugin (wraps AzuroClient, read-only)   [unspecified-high]
├── Task 7d: BookmakerXyzProvider plugin (wraps AzuroClient, read-only) [unspecified-high]
├── Task 7e: LimitlessClient + LimitlessProvider plugin                 [unspecified-high]
├── Task 7f: SXBetClient + SXBetProvider plugin                         [unspecified-high]
├── Task 8 → renumbered to 8:  LeaderboardCopySource implementation     [unspecified-high]
└── Task 9 → renumbered to 9:  InternalMirrorSource implementation      [unspecified-high]

Wave 3 (Integration — after Wave 2):
├── Task 10: CopyPolicyEngine (filter/scale/validate)                   [unspecified-high]
├── Task 11: AutoTrader fan-out extension (WalletRouter hook)           [unspecified-high]
├── Task 12: BankrollAllocator per-wallet cap extension                 [unspecified-high]
├── Task 13: API — wallet_allocations.py (TradingWallet + WalletAllocation CRUD) [unspecified-high]
└── Task 14: API — copy_policy.py CRUD + copy_trading.py mutations      [unspecified-high]

Wave 4 (Tests + Frontend — after Wave 3):
├── Task 15: pytest — WalletRouter unit tests                           [unspecified-high]
├── Task 16: pytest — CopyPolicyEngine + CopySource unit tests          [unspecified-high]
├── Task 17: pytest — all 6 provider plugin tests (PM+Kalshi+Azuro+Limitless+SXBet) [unspecified-high]
├── Task 18: pytest — API integration tests (wallet_allocations, copy_policy) [unspecified-high]
├── Task 19: Frontend — WalletMatrix.tsx                                [visual-engineering]
├── Task 20: Frontend — CopyPolicyPanel.tsx                             [visual-engineering]
└── Task 21: Frontend — ProviderStatusPanel.tsx (6 providers)           [visual-engineering]

Wave 5 (Docs + Cleanup — after Wave 4):
├── Task 22: Update AGENTS.md (root + backend/ + frontend/)             [writing]
├── Task 23: Update IMPLEMENTATION_GAPS.md                              [writing]
└── Task 24: Update .env.example (WALLET_FERNET_KEY + all new provider vars) [quick]

Wave FINAL (4 parallel reviews):
├── Task F1: Plan compliance audit                                       [oracle]
├── Task F2: Code quality review                                         [unspecified-high]
├── Task F3: Real QA execution                                           [unspecified-high]
└── Task F4: Scope fidelity check                                        [deep]
→ Present results → get explicit user okay
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1 | — | 2, 6, 8, 9, 10, 11, 12, 13, 14 |
| 2 | 1 | (migration must run before tests) |
| 3 | — | 8, 9, 10 |
| 4 | — | 22 |
| 5 | — | 22 |
| 5b | — | 22 |
| 6 | 1 | 11, 15 |
| 7 | PR#95 merged | 17 |
| 7a | PR#95 merged | 17 |
| 7b | — | 7c, 7d, 17 |
| 7c | 7b | 17 |
| 7d | 7b | 17 |
| 7e | PR#95 merged | 17 |
| 7f | PR#95 merged | 17 |
| 8 | 1, 3 | 10, 16 |
| 9 | 1, 3 | 10, 16 |
| 10 | 8, 9 | 16, 18 |
| 11 | 6, 1 | 15, 18 |
| 12 | 1 | 15, 18 |
| 13 | 1 | 18 |
| 14 | 1, 3 | 18 |
| 15 | 11, 12 | F1-F4 |
| 16 | 10 | F1-F4 |
| 17 | 7, 7a, 7c, 7d, 7e, 7f | F1-F4 |
| 18 | 13, 14, 11 | F1-F4 |
| 19 | 13 | F1-F4 |
| 20 | 14 | F1-F4 |
| 21 | 7, 7a, 7c, 7d, 7e, 7f | F1-F4 |
| 22 | 19, 20, 21 | F4 |
| 23 | 22 | F4 |
| 24 | 1 | F1 |

### Agent Dispatch Summary

- **Wave 1**: 6 agents — T1,T2→`quick`; T4,T5,T5b→`writing`; T3→`quick`
- **Wave 2**: 10 agents — T6–T9→`unspecified-high`; T7a–T7f→`unspecified-high`
- **Wave 3**: 5 agents — T10–T14→`unspecified-high`
- **Wave 4**: 7 agents — T15–T18→`unspecified-high`; T19–T21→`visual-engineering`
- **Wave 5**: 3 agents — T22,T23→`writing`; T24→`quick`
- **FINAL**: 4 agents — F1→`oracle`; F2,F3→`unspecified-high`; F4→`deep`

---

## TODOs

---

- [ ] 1. TradingWallet + WalletAllocation + CopyPolicy ORMs

  **What to do**:
  - Create `backend/models/trading_wallet.py` with three SQLAlchemy 2.0 ORM models:
    1. `TradingWallet`: `id` (int PK), `label` (str unique), `chain` (str — one of `"polymarket"`, `"kalshi"`, `"azuro"`, `"limitless"`, `"sxbet"`), `address` (str unique), `encrypted_private_key` (Text, nullable — Fernet encrypted), `api_key` (str nullable — for Kalshi), `encrypted_api_secret` (Text nullable — Fernet encrypted), `enabled` (bool default True), `is_paper` (bool default False), `created_at` (DateTime), `notes` (Text nullable)
    2. `WalletAllocation`: `id` (int PK), `strategy_name` (str FK→`strategy_configs.strategy_name`), `wallet_id` (int FK→`trading_wallets.id`), `weight` (Float, 0.0–1.0), `max_exposure_usd` (Float nullable), `enabled` (bool default True), `updated_at` (DateTime). UniqueConstraint on (`strategy_name`, `wallet_id`).
    3. `CopyPolicy`: `id` (int PK), `source_name` (str unique — e.g. "leaderboard", "internal_mirror"), `enabled` (bool default True), `max_size_usd` (Float default 50.0), `confidence_floor` (Float default 0.6), `max_delay_seconds` (int default 30), `size_scale_factor` (Float default 1.0), `cooldown_seconds` (int default 60), `updated_at` (DateTime)
  - Use `Base` from `backend/models/database.py` (do NOT create a new Base)
  - Add `__tablename__` values: `trading_wallets`, `wallet_allocations`, `copy_policies`
  - Export all three from `backend/models/__init__.py` (or create it if absent)

  **Must NOT do**:
  - Do NOT modify `WalletConfig` model at all
  - Do NOT create a second `Base` — reuse existing one from `database.py`
  - Do NOT add relationships that create circular imports

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4, 5)
  - **Blocks**: Tasks 2, 6, 9, 10, 11, 12, 13, 14, 15
  - **Blocked By**: None (can start immediately)

  **References**:
  - `backend/models/database.py:1-50` — import pattern, `Base` declaration, existing ORM style
  - `backend/models/database.py:727-742` — `WalletConfig` model to NOT modify but mirror style
  - `backend/models/database.py:426-460` — `BotState` as style reference
  - `backend/models/database.py:743-760` — `StrategyConfig` for FK target `strategy_configs.strategy_name`
  - `backend/models/genome_registry.py` — example of separate model file using shared `Base`

  **Acceptance Criteria**:
  - [ ] `python -c "from backend.models.trading_wallet import TradingWallet, WalletAllocation, CopyPolicy; print('OK')"` → `OK`
  - [ ] All three classes have correct `__tablename__` values

  **QA Scenarios**:
  ```
  Scenario: Import all three ORMs
    Tool: Bash
    Steps:
      1. cd /home/openclaw/projects/1ai-poly-trader
      2. python -c "from backend.models.trading_wallet import TradingWallet, WalletAllocation, CopyPolicy; print(TradingWallet.__tablename__, WalletAllocation.__tablename__, CopyPolicy.__tablename__)"
    Expected Result: prints "trading_wallets wallet_allocations copy_policies"
    Evidence: .sisyphus/evidence/task-1-orm-import.txt

  Scenario: No modification to WalletConfig
    Tool: Bash
    Steps:
      1. git diff backend/models/database.py | grep -E "^[-+].*WalletConfig"
    Expected Result: empty (no lines changed)
    Evidence: .sisyphus/evidence/task-1-walletconfig-unchanged.txt
  ```

  **Commit**: YES (groups with Task 2)
  - Message: `feat(models): add TradingWallet, WalletAllocation, CopyPolicy ORMs`
  - Files: `backend/models/trading_wallet.py`, `backend/models/__init__.py`

---

- [ ] 2. Alembic migration for TradingWallet + WalletAllocation + CopyPolicy

  **What to do**:
  - Run `alembic revision --autogenerate -m "add_trading_wallets_wallet_allocations_copy_policies"` after Task 1 ORMs are importable
  - Verify generated migration creates all 3 tables with correct columns, constraints, and indices
  - Add index on `wallet_allocations.strategy_name` and `wallet_allocations.wallet_id` for fast fan-out lookups
  - Run `alembic upgrade head` and verify 0 errors
  - Add FK constraint: `wallet_allocations.strategy_name` → `strategy_configs.strategy_name` ON DELETE CASCADE

  **Must NOT do**:
  - Do NOT manually edit existing migration files
  - Do NOT drop or alter any existing table

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on Task 1)
  - **Parallel Group**: Sequential after Task 1
  - **Blocks**: Integration tests (Tasks 16–19)
  - **Blocked By**: Task 1

  **References**:
  - `alembic/versions/` — naming convention of existing migrations
  - `alembic/env.py` — target_metadata import pattern
  - `backend/models/database.py:1-30` — Base + engine setup

  **Acceptance Criteria**:
  - [ ] `alembic upgrade head` exits 0 (no ERROR lines in output)
  - [ ] `alembic current` shows the new revision head (not "None")
  - [ ] All 3 tables visible: `sqlite3 polyedge.db ".tables"` output includes `trading_wallets`, `wallet_allocations`, `copy_policies`
  - [ ] `sqlite3 polyedge.db "PRAGMA table_info(trading_wallets);"` returns ≥ 8 columns

  **QA Scenarios**:
  ```
  Scenario: Migration runs clean
    Tool: Bash
    Steps:
      1. cd /home/openclaw/projects/1ai-poly-trader
      2. alembic upgrade head 2>&1
    Expected Result: exit 0, no ERROR lines
    Evidence: .sisyphus/evidence/task-2-migration.txt

  Scenario: Tables exist post-migration
    Tool: Bash
    Steps:
      1. sqlite3 polyedge.db ".tables" | tr ' ' '\n' | grep -E "trading_wallets|wallet_allocations|copy_policies"
    Expected Result: all 3 table names printed
    Evidence: .sisyphus/evidence/task-2-tables.txt
  ```

  **Commit**: YES (groups with Task 1)
  - Message: `feat(db): migration for trading_wallets, wallet_allocations, copy_policies`
  - Files: `alembic/versions/XXXX_add_trading_wallets_*.py`

---

- [ ] 3. CopySource ABC + CopyPolicyConfig dataclass

  **What to do**:
  - Create `backend/core/copy_source.py` with:
    1. `@dataclass CopyPolicyConfig`: `source_name: str`, `enabled: bool`, `max_size_usd: float`, `confidence_floor: float`, `max_delay_seconds: int`, `size_scale_factor: float`, `cooldown_seconds: int`
    2. `CopySignalData`: `@dataclass` with fields `source_name: str`, `leader_address: str`, `condition_id: str`, `side: str`, `raw_size: float`, `confidence: float`, `captured_at: datetime`, `metadata: dict`
    3. `CopySource(ABC)`: abstract methods `get_name(self) -> str`, `async fetch_signals(self) -> list[CopySignalData]`, `async is_healthy(self) -> bool`
  - All types fully typed (no `Any`)
  - Export from `backend/core/__init__.py` if it exists

  **Must NOT do**:
  - Do NOT import from `backend/models/trading_wallet.py` (avoid circular at this stage)
  - Do NOT implement concrete sources here (Tasks 9, 10)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 4, 5)
  - **Blocks**: Tasks 9, 10, 11
  - **Blocked By**: None

  **References**:
  - `backend/strategies/registry.py` — `BaseStrategy(ABC)` pattern to mirror
  - `backend/core/risk_manager.py` — dataclass style (`RiskDecision`)
  - `backend/strategies/order_executor.py` — existing `CopySignal` dataclass (do NOT rename; new `CopySignalData` is separate)

  **Acceptance Criteria**:
  - [ ] `python -c "from backend.core.copy_source import CopySource, CopySignalData, CopyPolicyConfig; print('OK')"` → OK
  - [ ] `CopySource` is abstract — instantiating directly raises `TypeError`

  **QA Scenarios**:
  ```
  Scenario: CopySource is abstract
    Tool: Bash
    Steps:
      1. python -c "from backend.core.copy_source import CopySource; CopySource()" 2>&1
    Expected Result: "TypeError: Can't instantiate abstract class"
    Evidence: .sisyphus/evidence/task-3-abstract.txt
  ```

  **Commit**: YES (standalone)
  - Message: `feat(core): CopySource ABC and CopyPolicyConfig dataclasses`
  - Files: `backend/core/copy_source.py`

---

- [ ] 4. ADR-007 — Multi-Wallet Routing Architecture

  **What to do**:
  - Create `docs/architecture/adr-007-multi-wallet-routing.md`
  - Sections: Status (Accepted), Context, Decision, Consequences, Alternatives Considered
  - Decision: `WalletAllocation` table as N↔N binding; `WalletRouter` does weighted fan-out; `BotState.active_wallet` is fallback view (highest-weight wallet); min-size guard per platform; per-wallet circuit breaker; `IMMUTABLE_SAFETY_RULES` apply per child order
  - Alternatives: single-active-wallet (rejected — no parallelism), round-robin (rejected — uneven risk)

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 23 (AGENTS.md update)
  - **Blocked By**: None

  **QA Scenarios**:
  ```
  Scenario: ADR file exists and has required sections
    Tool: Bash
    Steps:
      1. grep -E "Status|Context|Decision|Consequences" docs/architecture/adr-007-multi-wallet-routing.md
    Expected Result: all 4 section headers found
    Evidence: .sisyphus/evidence/task-4-adr.txt
  ```

  **Commit**: YES (groups with Task 5)
  - Message: `docs(adr): ADR-007 multi-wallet routing`

---

- [ ] 5. ADR-008 — Copy-Trade Architecture

  **What to do**:
  - Create `docs/architecture/adr-008-copy-trade-architecture.md`
  - Sections: Status, Context, Decision, Consequences, Alternatives Considered
  - Decision: `CopySource` ABC for pluggable signal sources; `CopyPolicyEngine` applies per-source policy; copy signals enter standard pipeline (risk → sandbox → fan-out); `CopyPolicy` ORM persists policy per source; `CopySource` virtual strategy entry in `WalletAllocation` matrix for routing
  - Cover: leaderboard polling cadence (5 min), internal mirror trigger (post-settlement), sandbox gate requirement

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 23
  - **Blocked By**: None

  **QA Scenarios**:
  ```
  Scenario: ADR file exists and has required sections
    Tool: Bash
    Steps:
      1. grep -E "Status|Context|Decision|Consequences" docs/architecture/adr-008-copy-trade-architecture.md
    Expected Result: all 4 section headers found
    Evidence: .sisyphus/evidence/task-5-adr.txt
  ```

  **Commit**: YES (groups with Task 4)
  - Message: `docs(adr): ADR-008 copy-trade architecture`

---

- [ ] 5b. ADR-009 — Extended Provider Integration (Azuro / limitless / sx.bet)

  **What to do**:
  - Create `docs/architecture/adr-009-extended-provider-integration.md`
  - Sections: Status (Accepted), Context, Decision, Consequences, Alternatives Considered
  - **Context**: Four new market providers added beyond the original PM+Kalshi scope: predict.fun and bookmaker.xyz (both built on Azuro Protocol on Gnosis/Polygon); limitless.exchange (CLOB+AMM on Base, REST API); sx.bet (P2P sports on Polygon, REST API).
  - **Decision points to document**:
    - predict.fun + bookmaker.xyz share a single `AzuroClient` — no code duplication
    - Azuro order placement via Web3 smart contract transactions (not a REST API)
    - `is_read_only=False` for all four providers (live orders supported via Web3 signing)
    - The Graph free-tier rate limits require mandatory TTL cache in `AzuroClient`
    - `web3` / `eth_account` libraries are already transitively available — no new top-level deps
    - `LIMITLESS_PRIVATE_KEY`, `SXBET_PRIVATE_KEY`, `WEB3_PRIVATE_KEY_AZURO` stored encrypted (Fernet, same as `WALLET_FERNET_KEY` pattern)
  - Include a provider comparison table: name, chain, API type, auth mechanism, order cancellable

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1)
  - **Blocks**: Task 22 (AGENTS.md update references this ADR)
  - **Blocked By**: None

  **Acceptance Criteria**:
  - [ ] File exists at `docs/architecture/adr-009-extended-provider-integration.md`
  - [ ] Contains provider comparison table with all 6 providers

  **QA Scenarios**:
  ```
  Scenario: ADR file exists and has required sections
    Tool: Bash
    Steps:
      1. grep -E "^## (Status|Context|Decision|Consequences)" docs/architecture/adr-009-extended-provider-integration.md
    Expected Result: 4 matching lines
    Evidence: .sisyphus/evidence/task-5b-adr-sections.txt
  ```

  **Commit**: YES (groups with Tasks 4, 5)
  - Message: `docs(adr): ADR-009 extended provider integration (Azuro/Limitless/SXBet)`

---

- [ ] 6. WalletRouter — weighted fan-out service

  **What to do**:
  - Create `backend/core/wallet_router.py`
  - Class `WalletRouter`:
    - `__init__(self, db_session, fernet_key: bytes)`: loads `TradingWallet` + `WalletAllocation` rows
    - `async get_wallets_for_strategy(self, strategy_name: str) -> list[WalletAllocation]`: query DB, filter enabled, sort by weight desc
    - `async fan_out(self, signal: Signal, bankroll: float, strategy_name: str) -> list[ChildOrder]`: for each allocated wallet, compute `child_size = signal.size * wallet.weight`; skip if child_size < MIN_ORDER_SIZE[wallet.chain]; apply per-wallet circuit breaker; return list of `ChildOrder(wallet_id, size, chain, condition_id, side)`
    - `MIN_ORDER_SIZE = {"polymarket": 1.0, "kalshi": 0.01}`
    - Per-wallet `CircuitBreaker(f"wallet_{wallet_id}", failure_threshold=3, recovery_timeout=120.0)` — same pattern as `data_api_breaker` in `order_executor.py`
    - `decrypt_key(self, encrypted: str) -> str`: Fernet decrypt using `fernet_key`
  - `ChildOrder` dataclass: `wallet_id: int`, `wallet_address: str`, `chain: str`, `size: float`, `condition_id: str`, `side: str`, `decrypted_key: str`
  - Log skipped child orders at WARNING level (loguru)

  **Must NOT do**:
  - Do NOT bypass `IMMUTABLE_SAFETY_RULES` — check `current_exposure + child_size <= max_total_exposure * bankroll` before each child order
  - Do NOT log `decrypted_key` value

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7–10)
  - **Blocks**: Tasks 12, 16
  - **Blocked By**: Task 1

  **References**:
  - `backend/strategies/order_executor.py` — `CircuitBreaker` usage pattern (`data_api_breaker`)
  - `backend/core/risk_manager.py:IMMUTABLE_SAFETY_RULES` — exposure check values
  - `backend/models/trading_wallet.py` — `TradingWallet`, `WalletAllocation` (from Task 1)
  - `backend/core/auto_trader.py` — `execute_signal` signature to understand `Signal` shape
  - `backend/core/bankroll_allocator.py` — per-strategy cap pattern to mirror per-wallet

  **Acceptance Criteria**:
  - [ ] `python -c "from backend.core.wallet_router import WalletRouter, ChildOrder; print('OK')"` → OK
  - [ ] fan_out with 2 wallets (weights 0.6, 0.4), signal size=$10 → child sizes $6 and $4
  - [ ] child size < MIN_ORDER_SIZE → skipped, WARNING logged

  **QA Scenarios**:
  ```
  Scenario: fan_out proportional split
    Tool: Bash (pytest)
    Steps:
      1. pytest tests/test_wallet_router.py::test_fan_out_proportional -v
    Expected Result: PASSED
    Evidence: .sisyphus/evidence/task-6-fanout.txt

  Scenario: min-size guard skips small child orders
    Tool: Bash (pytest)
    Steps:
      1. pytest tests/test_wallet_router.py::test_min_size_guard -v
    Expected Result: PASSED, ChildOrder list shorter than wallet list
    Evidence: .sisyphus/evidence/task-6-minsize.txt
  ```

  **Commit**: YES (standalone)
  - Message: `feat(core): WalletRouter with weighted fan-out and per-wallet circuit breaker`
  - Files: `backend/core/wallet_router.py`

---

- [ ] 7. PolymarketProvider — MarketProviderPlugin implementation

  **What to do**:
  - Create `backend/plugins/providers/polymarket_provider.py`
  - Class `PolymarketProvider` decorated with `@market_registry.plugin` (from PR #95 `MarketProviderRegistry`)
  - Implements all abstract methods of `MarketProviderPlugin`:
    - `get_name(self) -> str` → `"polymarket"`
    - `async get_balance(self, wallet_address: str) -> float` — call PM CLOB API `/balance` with wallet creds
    - `async get_positions(self, wallet_address: str) -> list[Position]` — PM Data API positions
    - `async place_order(self, order: OrderRequest) -> OrderResult` — PM CLOB API order placement; use existing `OrderExecutor` internals where possible
    - `async cancel_order(self, order_id: str) -> bool` — PM CLOB cancel
    - `async get_markets(self, query: str = "") -> list[MarketInfo]` — PM Gamma API markets
    - `is_paper(self) -> bool` — based on `SHADOW_MODE` env var
  - Pull base URL from `CLOB_API_URL`, `GAMMA_API_URL`, `DATA_API_URL` env vars (already in `backend/config.py`)
  - Wrap network calls in `data_api_breaker` circuit breaker (reuse existing instance)

  **Must NOT do**:
  - Do NOT duplicate existing `OrderExecutor` logic — delegate or extract; refactor is preferred
  - Do NOT hardcode any URL or key

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6, 8, 9, 10)
  - **Blocks**: Task 18, Task 22
  - **Blocked By**: PR #95 merged (assumes `MarketProviderPlugin` ABC available)

  **References**:
  - `.sisyphus/plans/plugin-system-refactoring.md` tasks 23–32 — `MarketProviderPlugin` ABC definition
  - `backend/strategies/order_executor.py` — existing PM order placement logic
  - `backend/config.py` — `CLOB_API_URL`, `GAMMA_API_URL`, `DATA_API_URL`
  - `backend/strategies/order_executor.py:data_api_breaker` — circuit breaker to reuse

  **Acceptance Criteria**:
  - [ ] `python -c "from backend.plugins.providers.polymarket_provider import PolymarketProvider; print(PolymarketProvider().get_name())"` → `polymarket`
  - [ ] `GET /api/v1/markets/providers` includes `{"name": "polymarket", ...}` in response

  **QA Scenarios**:
  ```
  Scenario: Provider registered and listed
    Tool: Bash (curl)
    Steps:
      1. curl -s http://localhost:8100/api/v1/markets/providers | python -m json.tool | grep polymarket
    Expected Result: "polymarket" appears in response
    Evidence: .sisyphus/evidence/task-7-provider-list.txt

  Scenario: get_name returns correct value
    Tool: Bash
    Steps:
      1. python -c "from backend.plugins.providers.polymarket_provider import PolymarketProvider; print(PolymarketProvider().get_name())"
    Expected Result: "polymarket"
    Evidence: .sisyphus/evidence/task-7-getname.txt
  ```

  **Commit**: YES (groups with Task 8)
  - Message: `feat(plugins): PolymarketProvider conforming to MarketProviderPlugin`
  - Files: `backend/plugins/providers/polymarket_provider.py`

---

- [ ] 8. KalshiProvider — MarketProviderPlugin implementation

  **What to do**:
  - Create `backend/plugins/providers/kalshi_provider.py`
  - Class `KalshiProvider` decorated with `@market_registry.plugin`
  - Implements all abstract methods of `MarketProviderPlugin`:
    - `get_name(self) -> str` → `"kalshi"`
    - `async get_balance(self, wallet_address: str) -> float` — Kalshi REST API
    - `async get_positions(self, wallet_address: str) -> list[Position]` — Kalshi positions endpoint
    - `async place_order(self, order: OrderRequest) -> OrderResult` — Kalshi order API
    - `async cancel_order(self, order_id: str) -> bool`
    - `async get_markets(self, query: str = "") -> list[MarketInfo]` — Kalshi markets search
    - `is_paper(self) -> bool`
  - Pull base URL from `KALSHI_API_URL` env var (add to `backend/config.py` if absent)
  - Auth: `KALSHI_API_KEY` + `KALSHI_API_SECRET` (already in `.env.example` or add them)

  **Must NOT do**:
  - Do NOT duplicate any Polymarket-specific logic

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6, 7, 9, 10)
  - **Blocks**: Task 18, Task 22
  - **Blocked By**: PR #95 merged

  **References**:
  - `.sisyphus/plans/plugin-system-refactoring.md` tasks 23–32 — `MarketProviderPlugin` ABC
  - `backend/config.py` — existing env var patterns
  - `backend/plugins/providers/polymarket_provider.py` (Task 7) — mirror structure

  **Acceptance Criteria**:
  - [ ] `python -c "from backend.plugins.providers.kalshi_provider import KalshiProvider; print(KalshiProvider().get_name())"` → `kalshi`
  - [ ] `GET /api/v1/markets/providers` includes `{"name": "kalshi", ...}`

  **QA Scenarios**:
  ```
  Scenario: Provider registered and listed
    Tool: Bash (curl)
    Steps:
      1. curl -s http://localhost:8100/api/v1/markets/providers | python -m json.tool | grep kalshi
    Expected Result: "kalshi" in response
    Evidence: .sisyphus/evidence/task-8-provider-list.txt
  ```

  **Commit**: YES (groups with Task 7)
  - Message: `feat(plugins): KalshiProvider conforming to MarketProviderPlugin`
  - Files: `backend/plugins/providers/kalshi_provider.py`, `backend/config.py` (if KALSHI_API_URL added)

---

- [ ] 7b. AzuroClient — shared Azuro Protocol GraphQL client

  **What to do**:
  - Create `backend/clients/azuro_client.py`
  - Class `AzuroClient`:
    - `__init__(self, graph_url: str, rpc_url: str, chain_id: int)` — read from `AZURO_GRAPH_URL`, `AZURO_RPC_URL`, `AZURO_CHAIN_ID`
    - `async cached_query(self, gql: str, variables: dict = None) -> dict` — send GraphQL POST to `AZURO_GRAPH_URL`; cache result in `_cache: dict[str, (float, dict)]` with TTL from `AZURO_CACHE_TTL_SECONDS` (default 60); respect `Retry-After` header on 429
    - `async get_markets(self, limit: int = 200, active_only: bool = True) -> list[dict]` — query Azuro subgraph for active events/outcomes; normalize to `MarketEntry`-compatible dict keys: `market_id`, `question`, `current_price`, `volume_24h`, `status`, `platform`
    - `async health_check(self) -> bool` — introspection query `{__typename}` to verify endpoint reachable
    - `async sign_and_send_bet(self, private_key: str, condition_id: str, outcome_index: int, amount_wei: int) -> str` — use `web3.py` + `eth_account` to sign and broadcast bet tx to RPC; return tx hash
  - Default graph URL: `https://api.thegraph.com/subgraphs/name/azuro-protocol/azuro-subgraph-xdai`
  - All network I/O via `httpx.AsyncClient`; rate-limit guard: max 1 req/s to The Graph

  **Must NOT do**:
  - Do NOT call The Graph in hot paths without going through `cached_query()`
  - Do NOT store private keys in memory beyond the call scope of `sign_and_send_bet()`
  - Do NOT hardcode chain IDs or graph URLs — all from env vars

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (standalone client, no PR #95 dependency)
  - **Parallel Group**: Wave 2 (alongside Tasks 7, 7a, 7e, 7f)
  - **Blocks**: Tasks 7c, 7d
  - **Blocked By**: None

  **References**:
  - `backend/data/polymarket_clob.py` — async httpx client pattern to mirror
  - `backend/data/kalshi_client.py` — credential + circuit-breaker pattern
  - Azuro subgraph: `https://api.thegraph.com/subgraphs/name/azuro-protocol/azuro-subgraph-xdai`

  **Acceptance Criteria**:
  - [ ] `python -c "from backend.clients.azuro_client import AzuroClient; print('OK')"` → OK
  - [ ] `await AzuroClient().health_check()` returns `True` in integration test with mock httpx

  **QA Scenarios**:
  ```
  Scenario: health_check returns True with mock endpoint
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_azuro_client.py::test_health_check_ok -v
    Expected Result: PASSED
    Evidence: .sisyphus/evidence/task-7b-health-check.txt

  Scenario: cached_query caches result
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_azuro_client.py::test_cache_ttl -v
    Expected Result: PASSED — second call within TTL returns cached dict without HTTP
    Evidence: .sisyphus/evidence/task-7b-cache.txt
  ```

  **Commit**: YES (standalone)
  - Message: `feat(clients): AzuroClient shared GraphQL/Web3 client for Azuro Protocol`
  - Files: `backend/clients/azuro_client.py`, `backend/config.py` (add AZURO_* vars)

---

- [ ] 7c. PredictFunProvider — Azuro-backed MarketProviderPlugin (read + order)

  **What to do**:
  - Create `backend/plugins/providers/predict_fun_provider.py`
  - Class `PredictFunProvider` decorated with `@market_registry.plugin`
  - Wraps `AzuroClient` (injected in `__init__` or constructed from env vars)
  - Implements `MarketProviderPlugin`:
    - `get_name(self) -> str` → `"predict_fun"`
    - `async get_markets(self, query: str = "") -> list[MarketInfo]` — delegate to `AzuroClient.get_markets()`; tag `platform="predict_fun"`
    - `async get_balance(self, wallet_address: str) -> float` — query ERC-20 balance of LP token on Azuro pool via `AzuroClient` Web3
    - `async place_order(self, order: OrderRequest) -> OrderResult` — call `AzuroClient.sign_and_send_bet()`; on success return `OrderResult(order_id=tx_hash, status="submitted")`
    - `async cancel_order(self, order_id: str) -> bool` — Azuro bets are not cancellable; raise `OrderRejectedError("Azuro bets are final")`
    - `is_paper(self) -> bool`
    - `is_read_only(self) -> bool` → `False` (supports live orders via smart contract)
  - Propagate `platform_url = "https://predict.fun"` in manifest

  **Must NOT do**:
  - Do NOT duplicate `AzuroClient` HTTP logic — delegate 100%
  - Do NOT implement cancel as no-op — raise the correct error

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2, same group as 7d)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 17
  - **Blocked By**: Task 7b (AzuroClient), PR #95 merged

  **References**:
  - `backend/plugins/providers/polymarket_provider.py` (Task 7) — structure to mirror
  - `backend/clients/azuro_client.py` (Task 7b)
  - `.sisyphus/plans/plugin-system-refactoring.md` tasks 23–32 — `MarketProviderPlugin` interface

  **Acceptance Criteria**:
  - [ ] `GET /api/v1/markets/providers` includes `{"name": "predict_fun", "is_read_only": false}`
  - [ ] `cancel_order()` raises `OrderRejectedError`

  **QA Scenarios**:
  ```
  Scenario: provider listed with is_read_only=false
    Tool: Bash (curl)
    Steps:
      1. curl -s http://localhost:8100/api/v1/markets/providers | python -m json.tool | grep -A5 predict_fun
    Expected Result: name=predict_fun, is_read_only=false
    Evidence: .sisyphus/evidence/task-7c-provider-list.txt
  ```

  **Commit**: YES (groups with Task 7d)
  - Message: `feat(plugins): PredictFunProvider via Azuro Protocol`
  - Files: `backend/plugins/providers/predict_fun_provider.py`

---

- [ ] 7d. BookmakerXyzProvider — Azuro-backed MarketProviderPlugin

  **What to do**:
  - Create `backend/plugins/providers/bookmaker_xyz_provider.py`
  - Class `BookmakerXyzProvider` decorated with `@market_registry.plugin`
  - Identical structure to `PredictFunProvider` but:
    - `get_name(self) -> str` → `"bookmaker_xyz"`
    - `platform_url = "https://bookmaker.xyz"`
    - Sports market tag applied to `MarketInfo.category` field (Azuro sports events)
  - Shares the same `AzuroClient` instance (pass via DI or registry singleton)

  **Must NOT do**:
  - Do NOT create a second `AzuroClient` class or copy-paste client code
  - Do NOT use a different graph URL unless bookmaker.xyz launches its own subgraph

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (same Wave 2 group as 7c)
  - **Blocks**: Task 17
  - **Blocked By**: Task 7b, PR #95 merged

  **References**:
  - `backend/plugins/providers/predict_fun_provider.py` (Task 7c) — copy structure, change name/URL
  - `backend/clients/azuro_client.py` (Task 7b)

  **Acceptance Criteria**:
  - [ ] `GET /api/v1/markets/providers` includes `{"name": "bookmaker_xyz", ...}`
  - [ ] Both `predict_fun` and `bookmaker_xyz` share `AzuroClient` singleton (confirmed by identity check in test)

  **QA Scenarios**:
  ```
  Scenario: provider listed
    Tool: Bash (curl)
    Steps:
      1. curl -s http://localhost:8100/api/v1/markets/providers | python -m json.tool | grep bookmaker_xyz
    Expected Result: name=bookmaker_xyz in response
    Evidence: .sisyphus/evidence/task-7d-provider-list.txt
  ```

  **Commit**: YES (groups with Task 7c)
  - Message: `feat(plugins): BookmakerXyzProvider via shared AzuroClient`
  - Files: `backend/plugins/providers/bookmaker_xyz_provider.py`

---

- [ ] 7e. LimitlessClient + LimitlessProvider — limitless.exchange plugin

  **What to do**:
  - Create `backend/clients/limitless_client.py`:
    - Class `LimitlessClient`:
      - Base URL from `LIMITLESS_API_URL` (default `https://api.limitless.exchange`)
      - `async get_markets(self, limit: int = 100) -> list[dict]` — `GET /markets`
      - `async get_orderbook(self, market_id: str) -> dict` — `GET /orderbook?marketId={market_id}`
      - `async get_portfolio(self, wallet_address: str) -> dict` — `GET /portfolio/{wallet_address}`
      - `async place_order(self, market_id: str, side: str, size: float, price: float, private_key: str) -> dict` — sign EIP-712 order with `eth_account.sign_typed_data()` then `POST /orders`
      - `async cancel_order(self, order_id: str, private_key: str) -> bool` — `DELETE /orders/{order_id}` with signed payload
      - `async health_check(self) -> bool` — `GET /markets?limit=1`; return True on 200
  - Create `backend/plugins/providers/limitless_provider.py`:
    - Class `LimitlessProvider` decorated with `@market_registry.plugin`
    - Implements full `MarketProviderPlugin`; pulls `LIMITLESS_PRIVATE_KEY` from env for signing
    - `get_name(self) -> str` → `"limitless"`
    - `is_read_only(self) -> bool` → `False`

  **Must NOT do**:
  - Do NOT log or persist the private key string at any point
  - Do NOT use synchronous `requests` — use async `httpx` throughout

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2, independent of Azuro tasks)
  - **Blocks**: Task 17, Task 21
  - **Blocked By**: PR #95 merged

  **References**:
  - `backend/clients/kalshi_client.py` — async httpx + auth pattern
  - `backend/plugins/providers/kalshi_provider.py` (Task 7a) — plugin structure
  - Limitless API Swagger: `https://api.limitless.exchange/api-v1`

  **Acceptance Criteria**:
  - [ ] `GET /api/v1/markets/providers` includes `{"name": "limitless", "is_read_only": false}`
  - [ ] `LimitlessClient.health_check()` returns True (mocked in test)

  **QA Scenarios**:
  ```
  Scenario: LimitlessProvider listed and healthy
    Tool: Bash (curl)
    Steps:
      1. curl -s http://localhost:8100/api/v1/markets/providers | python -m json.tool | grep limitless
    Expected Result: name=limitless in response
    Evidence: .sisyphus/evidence/task-7e-provider-list.txt

  Scenario: LimitlessClient.get_markets returns list
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_limitless_client.py::test_get_markets_mock -v
    Expected Result: PASSED
    Evidence: .sisyphus/evidence/task-7e-get-markets.txt
  ```

  **Commit**: YES (standalone)
  - Message: `feat(clients,plugins): LimitlessClient + LimitlessProvider for limitless.exchange`
  - Files: `backend/clients/limitless_client.py`, `backend/plugins/providers/limitless_provider.py`, `backend/config.py` (add LIMITLESS_API_URL, LIMITLESS_PRIVATE_KEY)

---

- [ ] 7f. SXBetClient + SXBetProvider — sx.bet plugin

  **What to do**:
  - Create `backend/clients/sxbet_client.py`:
    - Class `SXBetClient`:
      - Base URL from `SXBET_API_URL` (default `https://api.sx.bet`)
      - `async get_sports(self) -> list[dict]` — `GET /sports`
      - `async get_markets(self, sport_ids: list[int] = None, limit: int = 200) -> list[dict]` — `GET /markets/active`; normalize to `market_id`, `question`, `current_price`, `volume_24h`, `status`, `platform="sxbet"`
      - `async get_orderbook(self, market_hash: str) -> dict` — `GET /orders?marketHashes={market_hash}`
      - `async place_maker_order(self, market_hash: str, outcome_index: int, odds: float, stake_wei: int, private_key: str) -> dict` — build EIP-712 maker order, sign with `eth_account.sign_typed_data()`, `POST /orders/new`
      - `async fill_taker_order(self, order_hash: str, stake_wei: int, private_key: str) -> dict` — `POST /orders/fill`
      - `async health_check(self) -> bool` — `GET /sports`; True on 200
  - Create `backend/plugins/providers/sxbet_provider.py`:
    - Class `SXBetProvider` decorated with `@market_registry.plugin`
    - Implements full `MarketProviderPlugin`; pulls `SXBET_PRIVATE_KEY` from env
    - `get_name(self) -> str` → `"sxbet"`
    - `is_read_only(self) -> bool` → `False`
    - `async get_positions(self, wallet_address: str) -> list[Position]` — query Polygon chain for open SX positions via `GET /orders?maker={wallet_address}`

  **Must NOT do**:
  - Do NOT log private key
  - Do NOT block event loop with synchronous Web3 calls

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2, independent)
  - **Blocks**: Task 17, Task 21
  - **Blocked By**: PR #95 merged

  **References**:
  - `backend/clients/limitless_client.py` (Task 7e) — similar REST + EIP-712 pattern
  - SX.Bet API docs: `https://docs.sx.bet/`

  **Acceptance Criteria**:
  - [ ] `GET /api/v1/markets/providers` includes `{"name": "sxbet", "is_read_only": false}`
  - [ ] `SXBetClient.health_check()` returns True in test

  **QA Scenarios**:
  ```
  Scenario: SXBetProvider listed
    Tool: Bash (curl)
    Steps:
      1. curl -s http://localhost:8100/api/v1/markets/providers | python -m json.tool | grep sxbet
    Expected Result: name=sxbet in response
    Evidence: .sisyphus/evidence/task-7f-provider-list.txt
  ```

  **Commit**: YES (standalone)
  - Message: `feat(clients,plugins): SXBetClient + SXBetProvider for sx.bet`
  - Files: `backend/clients/sxbet_client.py`, `backend/plugins/providers/sxbet_provider.py`, `backend/config.py` (add SXBET_API_URL, SXBET_PRIVATE_KEY)

---

- [ ] 8. (formerly 7a) KalshiProvider — MarketProviderPlugin implementation

  **What to do**:
  - Create `backend/core/copy_sources/leaderboard_source.py`
  - Class `LeaderboardCopySource(CopySource)`:
    - `get_name(self) -> str` → `"leaderboard"`
    - `async fetch_signals(self) -> list[CopySignalData]`:
      - Call PM Data API: `GET {DATA_API_URL}/data-api/v2/activity?limit=50` to get recent trades
      - Filter by tracked wallet addresses from `WalletConfig` (existing watch-list) where `source="leaderboard"` and `enabled=True`
      - Map each trade to `CopySignalData` with `confidence` = `whale_score / 100.0` (from `WalletConfig.whale_score`)
      - Apply `CopyPolicy.max_delay_seconds` — skip signals older than policy window
    - `async is_healthy(self) -> bool`: ping Data API; return True if 200
  - Polling cadence: called by scheduler every 5 min (register in `backend/core/agi_jobs.py` as `copy_leaderboard_poll_job`)
  - Use `data_api_breaker` circuit breaker for Data API call

  **Must NOT do**:
  - Do NOT store raw API responses in DB — only persist `CopyTraderEntry` rows after policy engine approval

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: Tasks 11, 17
  - **Blocked By**: Tasks 1, 3

  **References**:
  - `backend/strategies/order_executor.py` — existing `CopySignal`, `LeaderboardScorer` to understand current leaderboard logic
  - `backend/strategies/wallet_sync.py` — `WalletWatcher` for watch-list access pattern
  - `backend/core/agi_jobs.py` — scheduler job registration pattern
  - `backend/core/copy_source.py` (Task 3) — `CopySource` ABC + `CopySignalData`
  - `backend/config.py` — `DATA_API_URL`

  **Acceptance Criteria**:
  - [ ] `python -c "from backend.core.copy_sources.leaderboard_source import LeaderboardCopySource; s = LeaderboardCopySource(None, None); print(s.get_name())"` → `leaderboard`

  **QA Scenarios**:
  ```
  Scenario: get_name() returns correct identifier
    Tool: Bash
    Steps:
      1. python -c "from backend.core.copy_sources.leaderboard_source import LeaderboardCopySource; src = LeaderboardCopySource([]); print(src.get_name())"
    Expected Result: output is "leaderboard" (or equivalent non-empty string matching the ABC contract)
    Evidence: .sisyphus/evidence/task-9-import.txt
  ```

  **Commit**: YES (groups with Task 10)
  - Message: `feat(core): LeaderboardCopySource polling PM Data API`

---

- [ ] 10. InternalMirrorSource implementation

  **What to do**:
  - Create `backend/core/copy_sources/internal_mirror_source.py`
  - Class `InternalMirrorSource(CopySource)`:
    - `get_name(self) -> str` → `"internal_mirror"`
    - `async fetch_signals(self) -> list[CopySignalData]`:
      - Query `Trade` table for recent settled trades (last N seconds, configurable via `CopyPolicy.max_delay_seconds`)
      - Filter by strategy names listed in `InternalMirrorSource.followed_strategies` (configurable list stored in `CopyPolicy.metadata` JSON or constructor param)
      - Map each settled trade to `CopySignalData` with `confidence` = original signal confidence from `TradeContext`
      - Skip trades already mirrored (check `CopyTraderEntry` for existing (`wallet`, `condition_id`, `side`) row)
    - `async is_healthy(self) -> bool` → always True (internal DB access)
  - Trigger point: called post-settlement hook in `OrderExecutor` (or scheduled every 60s)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: Tasks 11, 17
  - **Blocked By**: Tasks 1, 3

  **References**:
  - `backend/models/database.py:613` — `CopyTraderEntry` (dedup check)
  - `backend/models/database.py:764` — `TradeContext` (confidence source)
  - `backend/core/copy_source.py` (Task 3) — `CopySource` ABC

  **Acceptance Criteria**:
  - [ ] Import succeeds: `from backend.core.copy_sources.internal_mirror_source import InternalMirrorSource`
  - [ ] `get_name()` → `"internal_mirror"`

  **QA Scenarios**:
  ```
  Scenario: Import and name check
    Tool: Bash
    Steps:
      1. python -c "from backend.core.copy_sources.internal_mirror_source import InternalMirrorSource; print(InternalMirrorSource(None, []).get_name())"
    Expected Result: "internal_mirror"
    Evidence: .sisyphus/evidence/task-10-import.txt
  ```

  **Commit**: YES (groups with Task 9)
  - Message: `feat(core): InternalMirrorSource cross-strategy signal mirroring`

---

- [ ] 11. CopyPolicyEngine — filter, scale, validate

  **What to do**:
  - Create `backend/core/copy_engine.py`
  - Class `CopyPolicyEngine`:
    - `__init__(self, db_session, sandbox_manager: SandboxManager)`: loads `CopyPolicy` rows; builds `{source_name: CopyPolicyConfig}` cache; refresh every 5 min
    - `async process(self, signals: list[CopySignalData], source_name: str) -> list[CopySignalData]`: apply policy pipeline per signal:
      1. Check `policy.enabled` — drop if False
      2. Check `signal.confidence >= policy.confidence_floor` — drop if below
      3. Check signal age: `(now - signal.captured_at).seconds <= policy.max_delay_seconds` — drop if stale
      4. Check cooldown: last signal from same `leader_address` within `cooldown_seconds` — drop if cooling
      5. Scale size: `signal.raw_size * policy.size_scale_factor`, then cap at `policy.max_size_usd`
      6. Sandbox gate: call `sandbox_manager.run_strategy_in_sandbox(signal_as_code, scenario, 1)` — drop if fails
    - Return filtered + scaled signals
    - `async update_policy(self, source_name: str, updates: dict) -> CopyPolicy`: upsert DB row + refresh cache

  **Must NOT do**:
  - Do NOT bypass sandbox gate — every copy signal must pass it

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 12–15)
  - **Blocks**: Tasks 17, 19
  - **Blocked By**: Tasks 9, 10 (CopySource implementations needed to understand signal shape)

  **References**:
  - `backend/core/copy_source.py` (Task 3) — `CopySignalData`, `CopyPolicyConfig`
  - `backend/models/trading_wallet.py` (Task 1) — `CopyPolicy` ORM
  - `.sisyphus/plans/plugin-system-refactoring.md` task 38–43 — `SandboxManager` API
  - `backend/core/agi_jobs.py` — scheduler pattern for cache refresh

  **Acceptance Criteria**:
  - [ ] `python -c "from backend.core.copy_engine import CopyPolicyEngine; print('OK')"` → OK
  - [ ] Signal below confidence_floor is dropped
  - [ ] Stale signal (age > max_delay_seconds) is dropped
  - [ ] Signal size capped at max_size_usd

  **QA Scenarios**:
  ```
  Scenario: Confidence floor filter
    Tool: Bash (pytest)
    Steps:
      1. pytest tests/test_copy_engine.py::test_confidence_floor_filter -v
    Expected Result: PASSED
    Evidence: .sisyphus/evidence/task-11-confidence.txt

  Scenario: Size scaling and cap
    Tool: Bash (pytest)
    Steps:
      1. pytest tests/test_copy_engine.py::test_size_scale_and_cap -v
    Expected Result: PASSED
    Evidence: .sisyphus/evidence/task-11-size.txt
  ```

  **Commit**: YES (standalone)
  - Message: `feat(core): CopyPolicyEngine with filter/scale/sandbox pipeline`
  - Files: `backend/core/copy_engine.py`

---

- [ ] 12. AutoTrader fan-out extension

  **What to do**:
  - Modify `backend/core/auto_trader.py`:
    - Inject `WalletRouter` into `AutoTrader.__init__` (optional; fallback to legacy single-wallet path if `WalletRouter` is None or no allocations exist)
    - In `execute_signal()`: after risk check passes, call `wallet_router.fan_out(signal, bankroll, strategy_name)` → get `list[ChildOrder]`
    - If `ChildOrder` list is non-empty: dispatch each via `OrderExecutor` with child's wallet credentials; aggregate `ExecutionResult` list
    - If `ChildOrder` list is empty (no allocations or all skipped): fall back to existing `active_wallet` single-execution path
    - Persist each child order attempt to `TradeAttempt` ledger with `wallet_id` field (add nullable column if absent)
    - Update `BotState.active_wallet` to highest-weight wallet for the strategy (view-only update)

  **Must NOT do**:
  - Do NOT remove the legacy single-wallet path
  - Do NOT mutate historical `Trade` rows

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: Tasks 16, 19
  - **Blocked By**: Tasks 1, 6

  **References**:
  - `backend/core/auto_trader.py` — existing `execute_signal` method (full read before edit)
  - `backend/core/wallet_router.py` (Task 6) — `WalletRouter.fan_out` signature
  - `docs/architecture/adr-003-trade-attempt-observability.md` — `TradeAttempt` ledger rules
  - `docs/architecture/adr-004-bounded-autonomous-sizing.md` — sizing constraints

  **Acceptance Criteria**:
  - [ ] Single-wallet fallback still works when no `WalletAllocation` rows exist
  - [ ] With 2 wallet allocations: `execute_signal` produces 2 `TradeAttempt` rows
  - [ ] `pytest` passes (no regressions in existing auto_trader tests)

  **QA Scenarios**:
  ```
  Scenario: Fan-out to 2 wallets
    Tool: Bash (pytest)
    Steps:
      1. pytest tests/test_auto_trader.py::test_fanout_two_wallets -v
    Expected Result: PASSED, 2 TradeAttempt rows created
    Evidence: .sisyphus/evidence/task-12-fanout.txt

  Scenario: Fallback when no allocations
    Tool: Bash (pytest)
    Steps:
      1. pytest tests/test_auto_trader.py::test_single_wallet_fallback -v
    Expected Result: PASSED, uses existing active_wallet path
    Evidence: .sisyphus/evidence/task-12-fallback.txt
  ```

  **Commit**: YES (standalone)
  - Message: `feat(core): AutoTrader wallet fan-out via WalletRouter with single-wallet fallback`
  - Files: `backend/core/auto_trader.py`

---

- [ ] 13. BankrollAllocator per-wallet cap extension

  **What to do**:
  - Modify `backend/core/bankroll_allocator.py`:
    - After computing per-strategy allocation, further split allocation across wallets proportional to `WalletAllocation.weight`
    - Each wallet's share = `strategy_allocation * wallet_weight`; cap at `WalletAllocation.max_exposure_usd` if set
    - Expose `get_wallet_allocation(strategy_name: str) -> dict[int, float]` (wallet_id → dollar amount)
    - Existing per-strategy 50% cap is applied BEFORE wallet split (wallet splits are sub-allocations within strategy budget)
    - `crazy` profile 1% cap still applies at strategy level

  **Must NOT do**:
  - Do NOT change existing allocation output shape when no `WalletAllocation` rows exist

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: Tasks 16, 19
  - **Blocked By**: Task 1

  **References**:
  - `backend/core/bankroll_allocator.py` — full read before edit
  - `backend/core/risk_profiles.py` — `RISK_TIER_MAX_ALLOCATION`, `crazy` profile
  - `backend/models/trading_wallet.py` (Task 1) — `WalletAllocation` ORM

  **Acceptance Criteria**:
  - [ ] `get_wallet_allocation("strategy_a")` returns `{wallet_id_1: X, wallet_id_2: Y}` summing to strategy's total budget
  - [ ] Sum of wallet allocations ≤ strategy's BankrollAllocator output

  **QA Scenarios**:
  ```
  Scenario: Per-wallet split sums to strategy budget
    Tool: Bash (pytest)
    Steps:
      1. pytest tests/test_bankroll_allocator.py::test_per_wallet_split -v
    Expected Result: PASSED
    Evidence: .sisyphus/evidence/task-13-alloc.txt
  ```

  **Commit**: YES (standalone)
  - Message: `feat(core): BankrollAllocator per-wallet allocation splits`
  - Files: `backend/core/bankroll_allocator.py`

---

- [ ] 14. API — wallet_allocations.py (TradingWallet + WalletAllocation CRUD)

  **What to do**:
  - Create `backend/api/wallet_allocations.py` with FastAPI router prefix `/api/v1/wallet-allocations`
  - Endpoints:
    - `GET /wallets` — list all `TradingWallet` rows (mask `encrypted_private_key`: return `"***"`)
    - `POST /wallets` — create `TradingWallet`; accept `private_key` plaintext in body, Fernet-encrypt before DB write; return row without key
    - `PUT /wallets/{wallet_id}` — update label/notes/enabled; never accept key updates (force re-create)
    - `DELETE /wallets/{wallet_id}` — soft delete (set `enabled=False`)
    - `GET /allocations` — list all `WalletAllocation` rows; supports `?strategy_name=X` filter
    - `POST /allocations` — create binding; validate weight ∈ (0, 1]; validate sum of weights per strategy ≤ 1.0
    - `PUT /allocations/{allocation_id}` — update weight/max_exposure/enabled
    - `DELETE /allocations/{allocation_id}` — hard delete
  - Register router in `backend/api/main.py`
  - Admin auth required (same `admin_session` cookie check as other routes)

  **Must NOT do**:
  - Do NOT return plaintext `encrypted_private_key` in any response
  - Do NOT accept key update via PUT (security boundary)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: Tasks 19, 20
  - **Blocked By**: Task 1

  **References**:
  - `backend/api/wallets.py` — existing CRUD pattern, `_row_to_dict`, auth pattern
  - `backend/api/main.py` — router registration pattern
  - `backend/models/trading_wallet.py` (Task 1) — ORM models

  **Acceptance Criteria**:
  - [ ] `POST /api/v1/wallet-allocations/wallets` → 201, returns wallet without key
  - [ ] `GET /api/v1/wallet-allocations/wallets` → 200, `encrypted_private_key` masked
  - [ ] `POST /api/v1/wallet-allocations/allocations` with weight=1.5 → 422 validation error
  - [ ] Sum-of-weights > 1.0 across strategy → 400 error

  **QA Scenarios**:
  ```
  Scenario: Create wallet, key masked in response
    Tool: Bash (curl)
    Steps:
      1. curl -s -X POST http://localhost:8100/api/v1/wallet-allocations/wallets \
           -H "Content-Type: application/json" \
           -d '{"label":"test","chain":"polymarket","address":"0xABC","private_key":"secret"}' | python -m json.tool
    Expected Result: response has "encrypted_private_key": "***", no plaintext key
    Evidence: .sisyphus/evidence/task-14-create-wallet.json

  Scenario: Weight validation
    Tool: Bash (curl)
    Steps:
      1. curl -s -X POST http://localhost:8100/api/v1/wallet-allocations/allocations \
           -d '{"strategy_name":"test","wallet_id":1,"weight":1.5}' | python -m json.tool
    Expected Result: 422 Unprocessable Entity
    Evidence: .sisyphus/evidence/task-14-weight-validation.json
  ```

  **Commit**: YES (groups with Task 15)
  - Message: `feat(api): wallet-allocations CRUD endpoints`
  - Files: `backend/api/wallet_allocations.py`, `backend/api/main.py`

---

- [ ] 15. API — copy_policy.py CRUD + copy_trading.py mutations

  **What to do**:
  - Create `backend/api/copy_policy.py` with router prefix `/api/v1/copy-policy`
  - Endpoints:
    - `GET /` — list all `CopyPolicy` rows
    - `POST /` — create policy for a source; default values from `CopyPolicyConfig`
    - `PUT /{source_name}` — update policy fields (enabled, max_size_usd, confidence_floor, etc.)
    - `DELETE /{source_name}` — soft delete (enabled=False)
  - Extend `backend/api/copy_trading.py` with mutation routes:
    - `POST /sources/{source_name}/enable` — set `CopyPolicy.enabled=True`
    - `POST /sources/{source_name}/disable` — set `CopyPolicy.enabled=False`
    - `POST /signals/approve/{signal_id}` — manually approve a pending copy signal (for PendingApproval workflow)
    - `POST /signals/reject/{signal_id}` — manually reject
  - Register `copy_policy` router in `backend/api/main.py`
  - Admin auth required

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: Tasks 19, 21
  - **Blocked By**: Tasks 1, 3

  **References**:
  - `backend/api/copy_trading.py` — existing 4 GET routes to extend (full read before edit)
  - `backend/api/wallets.py` — auth + CRUD pattern
  - `backend/models/database.py:843` — `PendingApproval` model for signal approve/reject
  - `backend/models/trading_wallet.py` (Task 1) — `CopyPolicy` ORM

  **Acceptance Criteria**:
  - [ ] `GET /api/v1/copy-policy/` → 200, list of policies
  - [ ] `PUT /api/v1/copy-policy/leaderboard` → 200, updated policy returned
  - [ ] `POST /api/v1/copy-trading/sources/leaderboard/enable` → 200

  **QA Scenarios**:
  ```
  Scenario: Create and retrieve policy
    Tool: Bash (curl)
    Steps:
      1. curl -s -X POST http://localhost:8100/api/v1/copy-policy/ \
           -d '{"source_name":"leaderboard","max_size_usd":50,"confidence_floor":0.6}' | python -m json.tool
      2. curl -s http://localhost:8100/api/v1/copy-policy/ | python -m json.tool
    Expected Result: policy with source_name "leaderboard" in list
    Evidence: .sisyphus/evidence/task-15-policy.json
  ```

  **Commit**: YES (groups with Task 14)
  - Message: `feat(api): CopyPolicy CRUD and copy-trading mutation endpoints`
  - Files: `backend/api/copy_policy.py`, `backend/api/copy_trading.py`, `backend/api/main.py`

---

- [ ] 16. pytest — WalletRouter unit tests

  **What to do**:
  - Create `tests/test_wallet_router.py`
  - Tests:
    - `test_fan_out_proportional`: 2 wallets (weights 0.6, 0.4), signal size=$10 → child sizes $6, $4
    - `test_fan_out_single_wallet`: 1 wallet (weight 1.0) → 1 child order same size
    - `test_min_size_guard_polymarket`: child size $0.50 on polymarket → skipped (< $1 min)
    - `test_min_size_guard_kalshi`: child size $0.005 on kalshi → skipped (< $0.01 min)
    - `test_immutable_rules_exposure_cap`: exposure at 94% of bankroll → fan-out skipped for all wallets
    - `test_circuit_breaker_opens_after_failures`: wallet CB opens after 3 failures → wallet skipped on 4th call
    - `test_decrypt_key_roundtrip`: encrypt → store → decrypt → assert plaintext matches
  - Use `unittest.mock` / `pytest-mock` for DB session; no live DB required

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 17–22)
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 12, 13

  **References**:
  - `backend/core/wallet_router.py` (Task 6)
  - Existing test files in `tests/` — fixture and mock patterns

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_wallet_router.py -v` → all 7 tests PASSED

  **QA Scenarios**:
  ```
  Scenario: All wallet router tests pass
    Tool: Bash
    Steps:
      1. cd /home/openclaw/projects/1ai-poly-trader && pytest tests/test_wallet_router.py -v 2>&1
    Expected Result: 7 passed, 0 failed
    Evidence: .sisyphus/evidence/task-16-pytest.txt
  ```

  **Commit**: YES (groups with Task 17)
  - Message: `test(core): WalletRouter unit tests`

---

- [ ] 17. pytest — CopyPolicyEngine + CopySource unit tests

  **What to do**:
  - Create `tests/test_copy_engine.py`
  - Tests:
    - `test_confidence_floor_filter`: signal confidence=0.5, floor=0.6 → filtered out
    - `test_confidence_pass`: signal confidence=0.7, floor=0.6 → passes
    - `test_stale_signal_dropped`: signal age=40s, max_delay=30s → dropped
    - `test_size_scale_and_cap`: raw_size=200, scale=0.5, max=50 → final size=50 (capped)
    - `test_size_scale_no_cap`: raw_size=20, scale=1.0, max=50 → final size=20
    - `test_disabled_policy_drops_all`: policy enabled=False → all signals dropped
    - `test_cooldown_enforced`: same leader_address within cooldown_seconds → second signal dropped
    - `test_sandbox_gate_rejection`: sandbox_manager returns failure → signal dropped

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocks**: F1-F4
  - **Blocked By**: Task 11

  **References**:
  - `backend/core/copy_engine.py` (Task 11)
  - `backend/core/copy_source.py` (Task 3)

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_copy_engine.py -v` → all 8 tests PASSED

  **QA Scenarios**:
  ```
  Scenario: All copy engine tests pass
    Tool: Bash
    Steps:
      1. pytest tests/test_copy_engine.py -v 2>&1
    Expected Result: 8 passed, 0 failed
    Evidence: .sisyphus/evidence/task-17-pytest.txt
  ```

  **Commit**: YES (groups with Task 16)
  - Message: `test(core): CopyPolicyEngine unit tests`

---

- [ ] 17. pytest — all 6 provider plugin tests (PM + Kalshi + Azuro + Limitless + SXBet)

  **What to do**:
  - Create `tests/test_market_providers.py`
  - Tests (all using `httpx.MockTransport` or `respx` for HTTP mocking; Web3 calls mocked with `unittest.mock.patch`):
    - `test_polymarket_provider_get_name`: → `"polymarket"`
    - `test_kalshi_provider_get_name`: → `"kalshi"`
    - `test_predict_fun_provider_get_name`: → `"predict_fun"`
    - `test_bookmaker_xyz_provider_get_name`: → `"bookmaker_xyz"`
    - `test_limitless_provider_get_name`: → `"limitless"`
    - `test_sxbet_provider_get_name`: → `"sxbet"`
    - `test_polymarket_place_order_success`: mock CLOB → `OrderResult.success=True`
    - `test_kalshi_place_order_success`: mock Kalshi API → `OrderResult.success=True`
    - `test_limitless_place_order_success`: mock `LimitlessClient.place_order` → `OrderResult.success=True`
    - `test_sxbet_place_maker_order_success`: mock `SXBetClient.place_maker_order` → success
    - `test_predict_fun_cancel_raises`: `PredictFunProvider.cancel_order()` → raises `OrderRejectedError`
    - `test_bookmaker_xyz_cancel_raises`: `BookmakerXyzProvider.cancel_order()` → raises `OrderRejectedError`
    - `test_azuro_client_cache_ttl`: two sequential `cached_query()` calls → only 1 HTTP request made
    - `test_polymarket_circuit_breaker`: 5 consecutive failures → circuit opens
    - `test_all_six_providers_in_registry`: `market_registry.list()` includes all 6 names

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 7, 7a, 7b, 7c, 7d, 7e, 7f

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_market_providers.py -v` → all 15 tests PASSED

  **QA Scenarios**:
  ```
  Scenario: All 15 provider tests pass
    Tool: Bash
    Steps:
      1. pytest tests/test_market_providers.py -v 2>&1
    Expected Result: 15 passed, 0 failed
    Evidence: .sisyphus/evidence/task-17-pytest.txt
  ```

  **Commit**: YES (standalone)
  - Message: `test(plugins): all 6 provider plugin unit tests`

---

- [ ] 19. pytest — API integration tests

  **What to do**:
  - Create `tests/test_api_wallet_allocations.py` and `tests/test_api_copy_policy.py`
  - Use FastAPI `TestClient` (no live server needed)
  - `test_api_wallet_allocations.py` tests:
    - `test_create_wallet_masks_key`: POST → response has `encrypted_private_key == "***"`
    - `test_list_wallets`: GET → 200, list
    - `test_create_allocation_valid_weight`: POST weight=0.5 → 201
    - `test_create_allocation_invalid_weight`: POST weight=1.5 → 422
    - `test_allocation_weight_sum_exceeded`: two allocations summing > 1.0 → 400
  - `test_api_copy_policy.py` tests:
    - `test_create_policy`: POST → 201
    - `test_update_policy`: PUT → 200, updated fields
    - `test_enable_disable_source`: POST enable/disable → 200, policy enabled toggled

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 14, 15, 12

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_api_wallet_allocations.py tests/test_api_copy_policy.py -v` → all tests PASSED

  **QA Scenarios**:
  ```
  Scenario: All API integration tests pass
    Tool: Bash
    Steps:
      1. pytest tests/test_api_wallet_allocations.py tests/test_api_copy_policy.py -v 2>&1
    Expected Result: all passed, 0 failed
    Evidence: .sisyphus/evidence/task-19-pytest.txt
  ```

  **Commit**: YES (standalone)
  - Message: `test(api): wallet-allocations and copy-policy integration tests`

---

- [ ] 20. Frontend — WalletMatrix.tsx

  **What to do**:
  - Create `frontend/src/components/WalletMatrix.tsx`
  - N↔N allocation grid: rows = strategies (from `/api/v1/strategies`), columns = wallets (from `/api/v1/wallet-allocations/wallets`)
  - Each cell: editable weight input (0–1), enabled toggle
  - Row totals: sum of weights per strategy (highlight red if > 1.0)
  - "Save" button: PATCH/PUT to `/api/v1/wallet-allocations/allocations`
  - "Add Wallet" button: opens modal to create new `TradingWallet` (form: label, chain, address, private_key — masked after submit)
  - Polling: `VITE_POLL_SLOW_MS` interval
  - Use existing design system tokens and component patterns from dashboard

  **Must NOT do**:
  - Do NOT display or store plaintext private key after initial submission

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocks**: Tasks 23, F3
  - **Blocked By**: Task 14

  **References**:
  - `frontend/src/` — existing component patterns, hooks, polling setup
  - `frontend/src/polling.ts` — polling interval constants
  - `backend/api/wallet_allocations.py` (Task 14) — API shape

  **Acceptance Criteria**:
  - [ ] `cd frontend && npm run build` exits 0
  - [ ] WalletMatrix renders at `/dashboard/wallet-matrix` route
  - [ ] Weight sum > 1.0 highlighted in red

  **QA Scenarios**:
  ```
  Scenario: WalletMatrix renders with 2 strategies and 2 wallets
    Tool: Playwright
    Steps:
      1. Navigate to http://localhost:5173/dashboard/wallet-matrix
      2. Assert table has 2 strategy rows and 2 wallet columns
      3. Assert weight inputs are editable
    Expected Result: grid renders, no console errors
    Evidence: .sisyphus/evidence/task-20-walletmatrix.png

  Scenario: Weight sum > 1.0 highlighted
    Tool: Playwright
    Steps:
      1. Set wallet1 weight=0.7, wallet2 weight=0.5 for same strategy
      2. Assert row total cell has CSS class indicating error/red
    Expected Result: row total cell has error styling
    Evidence: .sisyphus/evidence/task-20-weightsum.png
  ```

  **Commit**: YES (groups with Tasks 21, 22)
  - Message: `feat(frontend): WalletMatrix N×N allocation grid`

---

- [ ] 21. Frontend — CopyPolicyPanel.tsx

  **What to do**:
  - Create `frontend/src/components/CopyPolicyPanel.tsx`
  - List all `CopyPolicy` rows from `GET /api/v1/copy-policy/`
  - Per-source card: source name, enabled toggle, editable fields (max_size_usd, confidence_floor, max_delay_seconds, size_scale_factor, cooldown_seconds)
  - "Save" button per card: PUT to `/api/v1/copy-policy/{source_name}`
  - Status indicator: `is_healthy` badge (green/red) polled from copy-trading status endpoint
  - Recent signals count from `GET /api/v1/copy-trading/signals`

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocks**: Tasks 23, F3
  - **Blocked By**: Task 15

  **Acceptance Criteria**:
  - [ ] `npm run build` exits 0
  - [ ] CopyPolicyPanel renders at `/dashboard/copy-policy`
  - [ ] Toggle enabled → PUT request fired

  **QA Scenarios**:
  ```
  Scenario: Policy panel renders
    Tool: Playwright
    Steps:
      1. Navigate to http://localhost:5173/dashboard/copy-policy
      2. Assert at least 1 policy card renders
    Expected Result: renders without error
    Evidence: .sisyphus/evidence/task-21-copypolicy.png
  ```

  **Commit**: YES (groups with Tasks 20, 22)
  - Message: `feat(frontend): CopyPolicyPanel per-source policy editor`

---

- [ ] 21. Frontend — ProviderStatusPanel.tsx

  **What to do**:
  - Create `frontend/src/components/ProviderStatusPanel.tsx`
  - Fetch from `GET /api/v1/markets/providers` (PR #95 endpoint)
  - Per-provider card: name, status (connected/error/read-only), aggregate balance (from `GET /api/v1/markets/balance`), open positions count, `is_read_only` badge
  - Show all 6 providers: polymarket, kalshi, predict_fun, bookmaker_xyz, limitless, sxbet
  - `is_read_only=true` providers show "Data Only" badge (no trading indicator)
  - Refresh button + auto-poll at `VITE_POLL_NORMAL_MS`
  - Error state: red badge if provider circuit breaker is open

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocks**: Tasks 22, F3
  - **Blocked By**: Tasks 7, 7a, 7b, 7c, 7d, 7e, 7f

  **Acceptance Criteria**:
  - [ ] `npm run build` exits 0
  - [ ] ProviderStatusPanel renders all 6 provider cards

  **QA Scenarios**:
  ```
  Scenario: All 6 providers shown
    Tool: Playwright
    Steps:
      1. Navigate to http://localhost:5173/dashboard/providers
      2. Assert cards with text "polymarket", "kalshi", "predict_fun", "bookmaker_xyz", "limitless", "sxbet" present
    Expected Result: 6 provider cards render
    Evidence: .sisyphus/evidence/task-21-providers.png

  Scenario: is_read_only badge shown for predict_fun and bookmaker_xyz
    Tool: Playwright
    Steps:
      1. Navigate to http://localhost:5173/dashboard/providers
      2. Assert "Data Only" badge on predict_fun and bookmaker_xyz cards
    Expected Result: 2 "Data Only" badges visible
    Evidence: .sisyphus/evidence/task-21-readonly-badges.png
  ```

  **Commit**: YES (groups with Tasks 19, 20)
  - Message: `feat(frontend): ProviderStatusPanel for all 6 market providers`

---

- [ ] 22. Update AGENTS.md files (root + backend/ + frontend/)

  **What to do**:
  - `AGENTS.md` (root): Add new files to Key Files table: `backend/models/trading_wallet.py`, `backend/core/wallet_router.py`, `backend/core/copy_engine.py`, `backend/core/copy_source.py`, `backend/core/copy_sources/leaderboard_source.py`, `backend/core/copy_sources/internal_mirror_source.py`, `backend/clients/azuro_client.py`, `backend/clients/limitless_client.py`, `backend/clients/sxbet_client.py`, `backend/plugins/providers/polymarket_provider.py`, `backend/plugins/providers/kalshi_provider.py`, `backend/plugins/providers/predict_fun_provider.py`, `backend/plugins/providers/bookmaker_xyz_provider.py`, `backend/plugins/providers/limitless_provider.py`, `backend/plugins/providers/sxbet_provider.py`, `backend/api/wallet_allocations.py`, `backend/api/copy_policy.py`. Update ADR list to include ADR-007, ADR-008, ADR-009. Update Common Patterns section with wallet routing and copy-trade notes, and note all 6 supported market provider chains.
  - `backend/AGENTS.md`: Add entries for all new backend files. Update strategy governance section to note copy signals enter standard pipeline.
  - `frontend/AGENTS.md`: Add entries for `WalletMatrix.tsx`, `CopyPolicyPanel.tsx`, `ProviderStatusPanel.tsx`.

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5
  - **Blocks**: F4
  - **Blocked By**: Tasks 20, 21, 22

  **Acceptance Criteria**:
  - [ ] `grep "trading_wallet" AGENTS.md` → found
  - [ ] `grep "ADR-007" AGENTS.md` → found

  **QA Scenarios**:
  ```
  Scenario: Key new files listed in AGENTS.md
    Tool: Bash
    Steps:
      1. grep -E "trading_wallet|wallet_router|copy_engine|polymarket_provider|kalshi_provider" AGENTS.md
    Expected Result: all 5 patterns found
    Evidence: .sisyphus/evidence/task-23-agents.txt
  ```

  **Commit**: YES (groups with Tasks 24, 25)
  - Message: `docs: update AGENTS.md for multi-wallet, providers, copy-trade`

---

- [ ] 24. Update IMPLEMENTATION_GAPS.md

  **What to do**:
  - Open `IMPLEMENTATION_GAPS.md` and mark resolved gaps (if any relate to multi-wallet or copy-trade)
  - Add new known gaps discovered during implementation (if any)
  - Add note: "Multi-wallet credential rotation not implemented (KMS integration is future work)"
  - Add note: "Copy-trade signal latency not guaranteed — best-effort async delivery"
  - Add note: "On-chain leader auto-discovery uses `WalletConfig` watch-list — manual curation required"

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5
  - **Blocks**: F4
  - **Blocked By**: Task 23

  **QA Scenarios**:
  ```
  Scenario: Gaps file updated
    Tool: Bash
    Steps:
      1. grep "Multi-wallet credential rotation" IMPLEMENTATION_GAPS.md
    Expected Result: line found
    Evidence: .sisyphus/evidence/task-24-gaps.txt
  ```

  **Commit**: YES (groups with Tasks 23, 25)
  - Message: `docs: update IMPLEMENTATION_GAPS.md for multi-wallet and copy-trade`

---

- [ ] 24. Update .env.example

  **What to do**:
  - Add to `.env.example`:
    ```
    # Multi-Wallet Credential Encryption
    WALLET_FERNET_KEY=  # base64-encoded 32-byte Fernet key; generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    # Kalshi API (if not already present)
    KALSHI_API_URL=https://trading-api.kalshi.com/trade-api/v2
    KALSHI_API_KEY=
    KALSHI_API_SECRET=

    # Azuro Protocol (predict.fun + bookmaker.xyz)
    AZURO_GRAPH_URL=https://api.thegraph.com/subgraphs/name/azuro-protocol/azuro-subgraph-xdai
    AZURO_RPC_URL=  # e.g. https://rpc.ankr.com/gnosis or https://polygon-rpc.com
    AZURO_CHAIN_ID=100  # 100=Gnosis, 137=Polygon
    AZURO_CACHE_TTL_SECONDS=60
    WEB3_PRIVATE_KEY_AZURO=  # EVM private key for Azuro order placement (Fernet-encrypted in DB; raw key in env for dev only)

    # Limitless Exchange (limitless.exchange)
    LIMITLESS_API_URL=https://api.limitless.exchange
    LIMITLESS_WS_URL=wss://ws.limitless.exchange
    LIMITLESS_PRIVATE_KEY=  # EVM private key for EIP-712 order signing

    # SX.Bet (sx.bet) — Polygon P2P sports market
    SXBET_API_URL=https://api.sx.bet
    SXBET_PRIVATE_KEY=  # EVM private key for EIP-712 order signing (Polygon)
    ```
  - Add `cryptography` to `requirements.txt` if not already present (Fernet is from `cryptography` package)
  - Verify `web3` is in `requirements.txt` (should be transitive via `py-clob-client`); add explicit line if absent

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with Tasks 22, 23)
  - **Blocks**: F4
  - **Blocked By**: None (can start at Wave 5 in parallel; no code deps)

  **QA Scenarios**:
  ```
  Scenario: All new env vars documented
    Tool: Bash
    Steps:
      1. grep -E "WALLET_FERNET_KEY|AZURO_GRAPH_URL|LIMITLESS_API_URL|SXBET_API_URL" .env.example
    Expected Result: all 4 variable names found
    Evidence: .sisyphus/evidence/task-24-env.txt
  ```

  **Commit**: YES (groups with Tasks 22, 23)
  - Message: `chore: add all new provider and wallet vars to .env.example`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
> Do NOT auto-proceed. Wait for user's explicit approval before marking work complete.

- [ ] F1. **Plan Compliance Audit** — `oracle`

  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in `.sisyphus/evidence/`. Compare deliverables list against actual files created.

  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`

  Run `pytest` (all tests). Run `cd frontend && npm run build`. Review all changed files for: `as Any`/`# type: ignore`, empty except blocks, `print()` in production paths (should be `logger.*`), commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (`data`/`result`/`item`/`temp`). Verify `IMMUTABLE_SAFETY_RULES` dict unchanged.

  Output: `Build [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high` (+ `playwright` skill for UI)

  Start from clean DB state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence to `.sisyphus/evidence/final-qa/`. Test cross-feature integration: create wallet → allocate to strategy → fire signal → verify 2 child orders. Test copy signal flow: mock leaderboard signal → policy engine → fan-out → `CopyTraderEntry` row. Test edge: no allocations → single-wallet fallback.

  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`

  For each task: read "What to do", read actual diff (`git log --oneline --stat`). Verify 1:1 — everything specified was built, nothing beyond spec. Check "Must NOT do" compliance per task. Flag any `WalletConfig` column changes. Verify `AGENTS.md` updated. Verify `IMPLEMENTATION_GAPS.md` updated. Verify `.env.example` updated.

  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

| Wave | Tasks | Commit Message |
|------|-------|---------------|
| 1 | 1+2 | `feat(models/db): TradingWallet, WalletAllocation, CopyPolicy + migration` |
| 1 | 3 | `feat(core): CopySource ABC and dataclasses` |
| 1 | 4+5 | `docs(adr): ADR-007 multi-wallet routing, ADR-008 copy-trade` |
| 2 | 6 | `feat(core): WalletRouter weighted fan-out` |
| 2 | 7+8 | `feat(plugins): PolymarketProvider + KalshiProvider` |
| 2 | 9+10 | `feat(core): LeaderboardCopySource + InternalMirrorSource` |
| 3 | 11 | `feat(core): CopyPolicyEngine` |
| 3 | 12 | `feat(core): AutoTrader wallet fan-out` |
| 3 | 13 | `feat(core): BankrollAllocator per-wallet splits` |
| 3 | 14+15 | `feat(api): wallet-allocations + copy-policy endpoints` |
| 4 | 16+17 | `test(core): WalletRouter + CopyPolicyEngine tests` |
| 4 | 18 | `test(plugins): provider tests` |
| 4 | 19 | `test(api): wallet-allocations + copy-policy integration tests` |
| 4 | 20+21+22 | `feat(frontend): WalletMatrix, CopyPolicyPanel, ProviderStatusPanel` |
| 5 | 23+24+25 | `docs/chore: AGENTS.md, IMPLEMENTATION_GAPS.md, .env.example updates` |

---

## Success Criteria

### Verification Commands
```bash
pytest --tb=short                          # Expected: 0 failures
cd frontend && npm run build               # Expected: exit 0
alembic upgrade head                       # Expected: exit 0, no errors
python -c "from backend.core.wallet_router import WalletRouter; print('OK')"  # Expected: OK
python -c "from backend.core.copy_engine import CopyPolicyEngine; print('OK')" # Expected: OK
curl -s http://localhost:8100/api/v1/markets/providers | python -m json.tool   # Expected: polymarket + kalshi listed
curl -s http://localhost:8100/api/v1/wallet-allocations/wallets                # Expected: 200
```

### Final Checklist
- [ ] All "Must Have" items implemented and verified
- [ ] All "Must NOT Have" guardrails confirmed absent (grep + oracle review)
- [ ] `IMMUTABLE_SAFETY_RULES` dict unchanged (git diff confirm)
- [ ] `WalletConfig` ORM unchanged (git diff confirm)
- [ ] All 4 final verification agents return APPROVE
- [ ] User gives explicit "okay" to complete
