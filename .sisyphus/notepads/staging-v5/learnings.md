
## Staging v5 Startup (2026-05-15)

- Kalshi key must be at `secrets/kalshi_private_key.pem`; copied from `~/projects/polyedge/secrets/`
- Port 8101 was occupied by stale process; `kill -9` + `lsof` to verify
- API startup takes ~5-10s; health endpoint is `/api/v1/health` (not `/health`)
- Bot orchestrator starts via `python3 -m backend.core.orchestrator`
- 0 ERROR-level log lines, 0 Tracebacks in 2-min window = clean run
- `cross_market_arb` reports errors=500 (HTTP 500 from Kalshi upstream, not Python exceptions)
- `kalshi_arb` reports errors=1 per cycle (same Kalshi connectivity)
- Most strategies produce decisions but 0 trades due to rate-limit guards and duplicate-execution blocks
- `cex_pm_leadlag` is the first strategy to actually execute a trade in both paper and live PARALLEL modes
- `copy_trader` is scheduled at 300s intervals so won't appear in <2min window
