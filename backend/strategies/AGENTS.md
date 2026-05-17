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
| cross_market_arb | cross_market_arb.py | ACTIVE | — | — | Cross-exchange arbitrage |
| line_movement_detector | line_movement_detector.py | ACTIVE | — | — | Order book kinetics |
| market_maker | market_maker.py | ACTIVE | — | — | Market making, liquidity provision |
| btc_oracle | btc_oracle.py | DISABLED | 43.9% | -$341 | Auto-killed (low WR) |
| general_scanner | general_scanner.py | DISABLED | 10% | — | Auto-killed (critically low WR) |
| btc_momentum | btc_momentum.py | DEPRECATED | — | — | Legacy; don't use |
| realtime_scanner | realtime_scanner.py | DISABLED | — | — | Unstable; disabled |
| probability_arb | probability_arb.py | DISABLED | — | — | Research-phase; disabled |

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
