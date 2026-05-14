# SIGNAL MODULES (INFRASTRUCTURE)
<!-- Parent: ../AGENTS.md -->

**Module**: `backend/modules/` — Signal infrastructure, external feed integration

## PURPOSE

Infrastructure modules: source external signals (leaderboard, on-chain, weather APIs) rather than generating independent alpha. Still governed as strategies (auto-kill at <30% WR).

## MODULE ROSTER

| Module | Purpose | File | External Feed |
|--------|---------|------|----------------|
| `copy_trader` | Mirror top traders | copy_trader.py | Leaderboard data |
| `weather_emos` | Weather-driven signals | weather_emos.py (905 LOC) | Weather APIs |
| `whale_frontrun` | Whale transaction tracking | whale_frontrun.py | Blockchain data |
| `whale_pnl_tracker` | Whale PnL analysis | whale_pnl_tracker.py | Leaderboard |

## KEY FILE

- `weather_emos.py` (905 LOC) — Largest module; sources weather APIs

## CRITICAL DISTINCTION

**NOT alpha strategies** — they don't generate independent market analysis.  
**Still governed as strategies** — auto-kill at <30% WR, registered in StrategyConfig.

Infrastructure role justifies placement in `backend/modules/` rather than `backend/strategies/`.

## GOVERNANCE

- Registered in `StrategyConfig` table (same as alpha strategies)
- Auto-kill triggers at <30% win rate
- Disabled state in DB (never override in code)
- Health checks every 15min (same cadence)

## ANTI-PATTERNS

- ❌ Treating modules as non-strategic (they ARE governed)
- ❌ Manual re-enable after auto-kill
- ❌ Hardcoding external feed credentials (use config)
- ❌ No fallback for failed external API calls

## TESTING

```bash
pytest backend/tests/ -k "weather|whale|copy" -v
```

## EXTERNAL INTEGRATIONS

- **Weather APIs**: Configure in backend/config.py
- **Blockchain RPC**: Direct node or Infura
- **Leaderboard**: Polymarket/Kalshi API keys (in .env)
