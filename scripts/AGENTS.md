<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# scripts

## Purpose
Operational scripts, one-off fixes, seed data tools, and production service configuration for PolyEdge. **Not all scripts here are safe to re-run** — read the category column before executing anything.

## Script Inventory

| File | Category | Description |
|------|----------|-------------|
| `health-check.sh` | operational | HTTP health check against running instance |
| `backup-cron.sh` | operational | Cron-triggered DB backup |
| `backup_with_validation.sh` | operational | DB backup with integrity validation |
| `hourly_backup_job.sh` | operational | Hourly backup job (called by cron/systemd) |
| `verify_latest_backup.sh` | operational | Verify most recent backup is valid |
| `test_backup_verification.sh` | operational | Test backup verification logic |
| `migration_safety.sh` | operational | Pre-migration safety checks |
| `polyedge.service` | service-config | systemd unit for the main PolyEdge process |
| `polyedge-backup.service` | service-config | systemd unit for backup service |
| `polyedge-backup.timer` | service-config | systemd timer for scheduled backups |
| `seed_backtest_data.py` | seed | Seed historical backtest data into DB |
| `seed_honest_backtest.py` | seed | Seed realistic (non-inflated) backtest data |
| `seed_whale_wallets.py` | seed | Seed known whale wallet addresses |
| `configure_strategies.py` | operational | Set strategy enabled/disabled state in DB |
| `set_trading_mode_gating.py` | operational | Configure trading mode gating rules |
| `import_positions.py` | operational | Import positions from exchange into DB |
| `optimize_kelly.py` | operational | Compute and apply Kelly criterion sizing |
| `benchmark_forecastbench.py` | operational | Run ForecastBench evaluation |
| `dry-run-mainnet.py` | operational | Dry-run mainnet connection check (read-only) |
| `test-testnet-connection.py` | operational | Verify testnet API connectivity |
| `test-mirofish-ui.sh` | operational | Smoke test MiroFish UI endpoints |
| `verify_agi_system.py` | operational | Verify AGI system components are healthy |
| `verify_agi_final.py` | operational | Final AGI verification checklist |
| `verify_online_learner_cycle.py` | operational | Verify online learner training cycle |
| `verify_fixes.sh` | operational | Verify a set of bug fixes are applied |
| `integrate_becker_data.py` | operational | Integrate Becker research dataset |
| `backfill_blockchain_txns.py` | one-off | Backfill blockchain transaction history — **do not re-run** |
| `backfill_paper_initial_bankroll.py` | one-off | Backfill paper trading initial bankroll — **do not re-run** |
| `retry_closed_trades.py` | one-off | Retry settlement for closed trades — **do not re-run without review** |
| `force_resettle.py` | destructive | Force re-settlement of specific trades — **mutates settled trade records, do not re-run** |
| `fix_production_bugs.py` | destructive | Applied production bug fixes — **historical record only, do not re-run** |
| `FIXES_APPLIED.py` | destructive | Log of applied fixes — **historical record only, do not re-run** |
| `test-dashboard.spec.ts` | test | Dashboard E2E test (belongs in `frontend/e2e/`) |
| `test_agi_e2e.py` | test | AGI end-to-end test (run manually against live instance) |
| `test_alerts_manual.py` | test | Manual alert system test |
| `test_circuit_breakers.py` | test | Circuit breaker manual test |
| `test_mode_switch.py` | test | Trading mode switch test |
| `test_online_learner.py` | test | Online learner manual test |
| `test_risk_verification.py` | test | Risk system verification test |

## For AI Agents

### Working In This Directory
- **`one-off` and `destructive` scripts must not be re-run** — they document historical fixes applied to production data. `destructive` scripts mutate or delete existing records; re-running either category will corrupt data or produce duplicates.
- **`service-config` files are systemd units** — do not modify without ops review. Changes require reloading systemd on the production host (`systemctl daemon-reload`).
- **`test` scripts in this directory are manual** — they are not part of the `pytest` suite and require a running server instance. Automated tests belong in `tests/` or `frontend/e2e/`.
- Seed scripts (`seed_*.py`) are idempotent for initial setup but may produce duplicates if re-run against a populated DB — check before running.
- All scripts that touch the DB should be run with `SHADOW_MODE=true` unless explicitly intended for production.

### Common Patterns
- Run health check: `bash scripts/health-check.sh`
- Run backup: `bash scripts/backup_with_validation.sh`
- Configure strategies: `python scripts/configure_strategies.py --strategy btc_oracle --enable`


## Scripts (May 2026)

### Backfill Scripts
- `backfill_unresolved_v2.py` — Resolve unresolved live trades via Gamma API
- `backfill_unresolved_trades.py` — v1 (deprecated)

### Risk & Gate
Strategy gating is enforced in `backend/core/strategy_gate.py`. All strategies in PAPER mode.
