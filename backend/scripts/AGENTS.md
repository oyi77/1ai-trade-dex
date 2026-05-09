<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-09 -->

# scripts

## Purpose

Operational and diagnostic scripts for the trading bot. Includes smoke tests, migrations, and debugging utilities. Not part of the main application; run manually for validation, one-time setup, or troubleshooting.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `scanner_smoke.py` | Smoke test: verifies market_scanner can fetch live markets from Polymarket/Kalshi APIs. Tests `fetch_all_active_markets()` and `fetch_markets_by_keywords()` for BTC and weather markets. Exit code 0 on success. |
| `backfill_data_quality.py` | Script for backfilling data quality. |
| `backfill_live_pnl.py` | Script for backfilling live PnL. |
| `recalculate_expired_pnl.py` | Script for recalculating expired PnL. |
| `reconcile_bot_state.py` | Script for reconciling bot state. |
| `recover_wallet_history.py` | Script for recovering wallet history. |
| `seed_settings.py` | Script for seeding settings. |
| `validate_schema_constraints.py` | Script for validating schema constraints. |

## For AI Agents

### Working In This Directory

1. **Running the scanner smoke test**:
   ```bash
   cd /home/openclaw/projects/polyedge
   python backend/scripts/scanner_smoke.py
   ```
   Expected output:
   ```
   Fetching active markets (up to 200)...
   Got XXX markets
   Fetching BTC markets...
   BTC markets: XXX
   Fetching weather markets...
   Weather markets: XXX
   SMOKE TEST PASSED
   ```

2. **What it tests**:
   - Network connectivity to Polymarket API
   - Market data schema (required fields present)
   - Keyword filtering works (BTC vs weather markets)
   - Pagination/limit handling

3. **When to run**: Before deploying to testnet/live, after API endpoint changes, or when debugging market data issues.

### Testing Requirements

1. **Integration test** (requires live API access):
   ```python
   # backend/tests/test_market_scanner_smoke.py
   import subprocess
   
   def test_scanner_smoke():
       result = subprocess.run(
           ["python", "backend/scripts/scanner_smoke.py"],
           cwd="/home/openclaw/projects/polyedge",
           capture_output=True,
           timeout=30
       )
       assert result.returncode == 0, f"Smoke test failed: {result.stderr}"
       assert "SMOKE TEST PASSED" in result.stdout
   ```

2. **Run as part of CI** (only if API keys available):
   ```bash
   if [ -n "$POLYMARKET_API_KEY" ]; then
       python backend/scripts/scanner_smoke.py
   fi
   ```

3. **Check for regressions**: Run before and after market_scanner refactors to ensure API contract didn't break.

### Common Patterns

1. **Quick connectivity check**:
   ```bash
   python backend/scripts/scanner_smoke.py
   # If it passes, APIs are reachable and responding correctly
   ```

2. **Debug market data issues**:
   ```python
   # Modify scanner_smoke.py to print raw responses
   markets = await fetch_all_active_markets(limit=10)
   for m in markets:
       print(json.dumps(m, indent=2))  # See full market schema
   ```

3. **Extended smoke test** (for new features):
   ```python
   # Add to scanner_smoke.py or create new script
   async def test_kalshi_markets():
       from backend.data.kalshi_api import fetch_kalshi_markets
       markets = await fetch_kalshi_markets()
       assert len(markets) > 0
       print("Kalshi markets OK")
   ```

4. **Batch smoke tests** (run all diagnostics):
   ```bash
   #!/bin/bash
   python backend/scripts/scanner_smoke.py
   python backend/scripts/test_clob_connection.py  # (if exists)
   python backend/scripts/test_telegram_bot.py     # (if exists)
   echo "All smoke tests passed"
   ```

## Dependencies

### Internal

- `backend.core.market_scanner` — `fetch_all_active_markets()`, `fetch_markets_by_keywords()`
- `backend.config` — Settings for API keys, base URLs

### External

- **asyncio** (stdlib) — Async main loop
- **sys** (stdlib) — Path manipulation, exit codes
- No external HTTP client needed (uses backend.data module which wraps httpx)

<!-- MANUAL: -->
