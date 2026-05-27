# SIGNAL MODULES (INFRASTRUCTURE)
<!-- Parent: ../AGENTS.md -->
<!-- Updated: 2026-05-27 -->

**Module**: `backend/modules/` — Signal infrastructure, external feed integration

## PURPOSE

Infrastructure modules: source external signals (leaderboard, on-chain, weather APIs) rather than generating independent alpha. Still governed as strategies (auto-kill at <30% WR).

## MODULE ROSTER

| Module | Purpose | Directory | External Feed |
|--------|---------|-----------|---------------|
| `copy_trader` | Mirror top traders | `copy_trader/` | Leaderboard data |
| `whale_frontrun` | Whale transaction tracking | `scanners/` | Blockchain data |
| `whale_pnl_tracker` | Whale PnL analysis | `scanners/` | Leaderboard |
| `data_feeds` | Data feed infrastructure | `data_feeds/` | Various APIs |
| `execution` | Execution helpers | `execution/` | — |
| `arbitrage` | Cross-exchange arbitrage | `arbitrage/` | — |

## SUBDIRECTORIES

| Directory | Purpose |
|-----------|---------|
| `copy_trader/` | Copy trading signal source |
| `scanners/` | Whale and market scanners |
| `data_feeds/` | Data feed infrastructure |
| `execution/` | Execution helpers |
| `arbitrage/` | Cross-exchange arbitrage logic |

## CRITICAL DISTINCTION

**NOT alpha strategies** — they don't generate independent market analysis.
**Still governed as strategies** — auto-kill at <30% WR, registered in StrategyConfig.

Infrastructure role justifies placement in `backend/modules/` rather than `backend/strategies/`.

## GOVERNANCE

- Registered in `StrategyConfig` table (same as alpha strategies)
- Auto-kill triggers at <30% win rate
- Disabled state in DB (never override in code)
- Health checks every 15min (same cadence)

## TESTING

```bash
pytest backend/tests/ -k "weather|whale|copy" -v
```
