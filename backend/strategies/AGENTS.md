<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/strategies

## Purpose
Alpha strategy implementations — all `BaseStrategy` subclasses that generate independent market signals from analysis. Each strategy implements `run_cycle(ctx) -> CycleResult` and self-registers in `STRATEGY_REGISTRY` on class creation.

Infrastructure modules that mirror or relay signals (copy trading, whale tracking, weather feeds) live in `backend/modules/`, not here.

## Key Files

| File | Description |
|------|-------------|
| `base.py` | `BaseStrategy` ABC, `StrategyContext`, `CycleResult`, `MarketInfo` — the contract all strategies must implement |
| `registry.py` | `STRATEGY_REGISTRY` dict, `_auto_register`, `is_strategy_enabled`, `get_strategy` — strategy lookup and instantiation |
| `agi_meta_strategy.py` | `AGIMetaStrategy` (`agi_orchestrator`) — coordinates signal generation across all active strategies |
| `btc_oracle.py` | `BtcOracleStrategy` (`btc_oracle`) — BTC price prediction using multi-source aggregation |
| `universal_scanner.py` | `UniversalScanner` (`universal_scanner`) — broad market opportunity scanner |
| `bond_scanner.py` | `BondScannerStrategy` (`bond_scanner`) — near-certain outcome detection for high-probability trades |
| `cex_pm_leadlag.py` | `CexPmLeadLagStrategy` (`cex_pm_leadlag`) — CEX→Polymarket price lag arbitrage |
| `cross_market_arb.py` | `CrossMarketArb` (`cross_market_arb`) — Polymarket↔Kalshi price gap detection and execution |
| `line_movement_detector.py` | `LineMovementDetectorStrategy` (`line_movement_detector`) — detects sharp price moves (5%+ in 1h) indicating informed money |
| `market_maker.py` | `MarketMakerStrategy` (`market_maker`) — two-sided quoting with dynamic spread adjustment |
| `btc_momentum.py` | `BtcMomentumStrategy` (`btc_momentum`) — deprecated BTC momentum strategy |
| `probability_arb.py` | `ProbabilityArb` (`probability_arb`) — probability arbitrage (disabled) |
| `realtime_scanner.py` | `RealtimeScanner` (`realtime_scanner`) — realtime market scanner (disabled) |
| `general_market_scanner.py` | `GeneralMarketScanner` (`general_scanner`) — general scanner (disabled, 10% WR) |
| `arb_executor.py` | Arbitrage execution utilities shared by arb strategies |
| `order_executor.py` | Order execution helpers |
| `wallet_sync.py` | Wallet synchronization utilities |
| `types_hft.py` | HFT-specific type definitions |

## Strategy Governance

The authoritative enabled/disabled state is in `StrategyConfig` in the database. The list below is a snapshot — always check the DB for current state.

| Strategy name | File | Status | Notes |
|---|---|---|---|
| `agi_orchestrator` | `agi_meta_strategy.py` | Active | Coordinates all other strategies |
| `btc_oracle` | `btc_oracle.py` | Disabled | 43.9% WR, -$341 PnL — disabled after probability-bounds fix |
| `universal_scanner` | `universal_scanner.py` | Active | |
| `bond_scanner` | `bond_scanner.py` | Active | |
| `cex_pm_leadlag` | `cex_pm_leadlag.py` | Active | |
| `cross_market_arb` | `cross_market_arb.py` | Active | |
| `line_movement_detector` | `line_movement_detector.py` | Active | |
| `market_maker` | `market_maker.py` | Active | |
| `general_scanner` | `general_market_scanner.py` | Disabled | 10% WR — auto-killed by health check |
| `btc_momentum` | `btc_momentum.py` | Disabled | Deprecated |
| `realtime_scanner` | `realtime_scanner.py` | Disabled | |
| `probability_arb` | `probability_arb.py` | Disabled | |

**Killed strategies must not be manually re-enabled.** The AGI health check (`agi_health_check.py`) auto-kills strategies with <30% win rate after sufficient trades. Re-enabling a killed strategy bypasses this governance.

## For AI Agents

### Working In This Directory
- **Every new strategy must subclass `BaseStrategy` and implement `run_cycle(ctx) -> CycleResult`** — the registry auto-registers on class creation via `__init_subclass__`.
- **Strategies must not import from `backend/api/`** — the dependency direction is strategies → core → models/data.
- **Do not add infrastructure modules here** — copy trading, whale tracking, weather feeds belong in `backend/modules/`.
- `StrategyContext` carries everything a strategy needs: `ctx.db`, `ctx.clob`, `ctx.settings`, `ctx.params`, `ctx.mode`, `ctx.providers`.
- Strategy parameters are stored in `StrategyConfig.params` (JSON) in the DB — read via `ctx.params`, never hardcode thresholds.

### Adding a New Strategy
1. Create `backend/strategies/my_strategy.py` subclassing `BaseStrategy`
2. Set `name = "my_strategy"` as a class attribute (triggers auto-registration)
3. Implement `run_cycle(ctx: StrategyContext) -> CycleResult`
4. Add a `StrategyConfig` row via `scripts/configure_strategies.py` or a migration
5. Update this file's strategy table

### Testing Requirements
- Mock `StrategyContext` with an in-memory DB session and mock CLOB client
- Test `run_cycle` returns a valid `CycleResult` for both signal and no-signal cases
- Test with `mode="paper"` — never use `mode="live"` in tests

## Dependencies

### Internal
- `backend.config` — `settings`
- `backend.data` — market data clients
- `backend.core.signals` — signal creation
- `backend.monitoring` — metrics

### External
- `httpx` — async HTTP for external data
- `pydantic` — data validation
