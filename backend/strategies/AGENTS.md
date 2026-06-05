# TRADING STRATEGIES
<!-- Parent: ../AGENTS.md -->

**Module**: `backend/strategies/` — 12 alpha-generating trading strategies

## PURPOSE

Independent strategy implementations: market analysis, signal generation, trade decisions. Governed by AGI health checks; auto-kill at <30% win rate.

## STRATEGY ROSTER

### Active (Alpha Generators)

| Strategy | File | Status | Win Rate | PnL | Notes |
|----------|------|--------|----------|-----|-------|
| bond_scanner | bond_scanner.py | PAPER | 39.6% | +$18,711 | 35.9x win/loss ratio. Buys cheap NO shares |
| copy_trader | copy_trader_strategy.py | PAPER | — | — | Mirrors top traders |
| market_maker | market_maker.py | PAPER | — | — | Market making, liquidity provision |
| resolution_sniper | resolution_sniper.py | PAPER | — | — | Near-resolution sniping |
| probability_arb | probability_arb.py | PAPER | — | — | Cross-platform probability arbitrage |
| negrisk_strategy | negrisk_strategy.py | PAPER | — | — | Negative risk exploitation |

### Disabled (Killed by AGI or Manual)

| Strategy | File | Status | PnL | Kill Reason |
|----------|------|--------|-----|-------------|
| line_movement_detector | line_movement_detector.py | DISABLED | -$7,350 | Worst performer |
| cross_platform_arb | cross_market_arb_enhanced.py | DISABLED | -$1,450 | Net loser |
| arb_scanner | — | DISABLED | -$2,500 | Net loser |
| cex_pm_leadlag | cex_pm_leadlag.py | DISABLED | -$777 | Net loser |
| crypto_oracle | crypto_oracle.py | DISABLED | -$2,014 | Net loser |
| weather_emos | — | DISABLED | +$3,776 | Auto-killed by AGI |
| longshot_bias | longshot_bias.py | DISABLED | -$27 | 618 trades, net negative |
| agi_orchestrator | agi_orchestrator.py | DISABLED | — | Meta-strategy |
| general_scanner | general_market_scanner.py | DISABLED | — | — |
| universal_scanner | universal_scanner.py | DISABLED | — | — |
| hft_scalper | hft_scalper.py | DISABLED | — | — |
| hyperliquid | hyperliquid_strategy.py | DISABLED | — | — |
| whale_frontrun | — | DISABLED | — | — |
| whale_pnl_tracker | — | DISABLED | — | — |
| kalshi_arb | — | DISABLED | — | — |
| unified_arb | unified_pm_arb.py | DISABLED | — | — |
| news_frontrun | news_frontrun.py | DISABLED | -$5 | Too few trades |

### Live Mode — STOPPED

Live trading is DISABLED (bankroll=$3.48). Bond_scanner was moved from live to paper.
Re-enable only after 2+ weeks of profitable paper trading and re-funding.

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
├── unified_pm_arb.py       # Unified arb (PM + DEX detection)
├── line_movement_detector.py  # Order book kinetics
├── market_maker.py         # Market making
├── btc_oracle.py           # DISABLED: 43.9% WR, -$341 PnL
├── general_market_scanner.py  # ACTIVE: name=general_scanner
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
