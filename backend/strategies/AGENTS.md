# TRADING STRATEGIES
<!-- Parent: ../AGENTS.md -->

**Module**: `backend/strategies/` — 12 alpha-generating trading strategies

## PURPOSE

Independent strategy implementations: market analysis, signal generation, trade decisions. Governed by AGI health checks; auto-kill at <30% win rate.

## STRATEGY ROSTER

### Active (Alpha Generators)

| Strategy | File | Status | Win Rate | PnL | Notes |
|----------|------|--------|----------|-----|-------|
| agi_orchestrator | agi_orchestrator.py (743 LOC) | ACTIVE | — | — | Meta-strategy; orchestrates genomes |
| universal_scanner | universal_scanner.py | ACTIVE | — | — | Market-wide signals |
| bond_scanner | bond_scanner.py | ACTIVE | — | — | Bond market alpha |
| cex_pm_leadlag | cex_pm_leadlag.py | ACTIVE | — | — | CEX/Polymarket lead-lag |
| unified_pm_arb | unified_pm_arb.py (537 LOC) | ACTIVE | — | — | Unified arb (replaces cross_market_arb + arb_scanner + hft_cross_arb) |
| line_movement_detector | line_movement_detector.py | ACTIVE | — | — | Order book kinetics |
| market_maker | market_maker.py | ACTIVE | — | — | Market making, liquidity provision |
| btc_oracle | btc_oracle.py | DISABLED | 43.9% | -$341 | Auto-killed (low WR) |
| general_scanner | general_scanner.py | DISABLED | 10% | — | Auto-killed (critically low WR) |
| btc_momentum | btc_momentum.py | DEPRECATED | — | — | Legacy; don't use |
| realtime_scanner | realtime_scanner.py | DISABLED | — | — | Unstable; disabled |
| probability_arb | probability_arb.py | DISABLED | — | — | Research-phase; disabled |

### Additional Active Strategies

| Strategy | File | Status | Notes |
|----------|------|--------|-------|
| crypto_oracle | crypto_oracle.py (37K) | PAPER | BTC/ETH/SOL 5-min markets |
| general_market_scanner | general_market_scanner.py (41K) | ACTIVE | Market-wide opportunity scanner |
| longshot_bias | longshot_bias.py | ACTIVE | Longshot bias exploitation |
| order_executor | order_executor.py (17K) | ACTIVE | Order execution helper |
| cross_dex_arb | cross_dex_arb.py | ACTIVE | DEX arb detection (Hyperliquid, Ostium, Aster, Lighter) |
| agi_meta_strategy | agi_meta_strategy.py | ACTIVE | AGI meta-strategy wrapper |
| template_base | template_base.py | TEMPLATE | Strategy template for new strategies |
| registry | registry.py | INFRA | Strategy registry and loader |

### Deprecated / Legacy

| Strategy | File | Status | Notes |
|----------|------|--------|-------|
| general_scanner | general_scanner.py | DISABLED | Auto-killed (10% WR) |
| btc_momentum | btc_momentum.py | DEPRECATED | Legacy; don't use |
| realtime_scanner | realtime_scanner.py | DISABLED | Unstable |
| probability_arb | probability_arb.py | DISABLED | Research-phase |

### Signal Infrastructure (backend/modules/)

Not alpha strategies; source external signals (leaderboard, on-chain, weather APIs):

- `copy_trader`: Mirror top traders
- `weather_emos`: Weather-driven emotions
- `whale_frontrun`: Whale transaction tracking
- `whale_pnl_tracker`: Whale PnL analysis

Still governed same as alpha strategies (auto-kill at <30% WR).

## CRITICAL RULES

### Governance (AGI Auto-Kill)
- AGI health checks run every 15min (AGI_HEALTH_CHECK_ENABLED)
- Auto-kill triggers: win rate < 30% after sufficient trades
- Disabled state lives in `StrategyConfig` DB table, NOT code
- **NEVER manually re-enable killed strategies** (DB is source of truth)

### Win Rate Calculation
- Calculated from settled ShadowTrades
- Minimum trade sample required before evaluation (prevents false kills)
- Kills are permanent until manually overridden in DB (intentional friction)

## STRUCTURE

```
backend/strategies/
├── agi_orchestrator.py     # Meta-strategy, genome composition
├── universal_scanner.py    # Market-wide signals
├── bond_scanner.py         # Bond market alpha
├── cex_pm_leadlag.py       # CEX/Polymarket lead-lag
├── cross_market_arb.py     # Cross-exchange arbitrage
├── line_movement_detector.py  # Order book kinetics
├── market_maker.py         # Market making
├── btc_oracle.py           # DISABLED: 43.9% WR, -$341 PnL
├── general_scanner.py      # DISABLED: 10% WR (auto-killed)
├── btc_momentum.py         # DEPRECATED
├── realtime_scanner.py     # DISABLED
└── probability_arb.py      # DISABLED
```

### Utility Modules (Not Strategies)

| Module | File | Purpose |
|--------|------|---------|
| `fingerprint` | `fingerprint.py` | 14-dimension strategy profiling from position history |
| `replication` | `replication.py` | Extract decision logic from profitable wallets, paper simulation |
| `opportunity_detector` | `opportunity_detector.py` | Multi-type opportunity scanning (arb, momentum, liquidity gap, emotional) |

These are NOT BaseStrategy subclasses — they are utility modules used by the wallet intelligence pipeline.

## ANTI-PATTERNS

- ❌ Manual enabling of auto-killed strategies (DB-driven governance only)
- ❌ Strategy override without DB StrategyConfig update
- ❌ Win rate evaluation without settled trades
- ❌ FIXME/TODO in production strategy code

## TESTING

```bash
pytest backend/tests/test_strategy_executor.py -v
pytest backend/tests/ -k "strategy" -v
```


## Strategy Governance (May 2026)

### Gate Enforcement
Every strategy passes through StrategyGate before live orders. Checked in strategy_executor.py.

### Currently DISABLED
- `line_movement_detector` — was destroying capital
- `btc_oracle` — was losing money

### Currently PAPER (safe)
- `crypto_oracle` — BTC/ETH/SOL 5-min markets
- `whale_frontrun`, `cex_pm_leadlag`, `bond_scanner`
