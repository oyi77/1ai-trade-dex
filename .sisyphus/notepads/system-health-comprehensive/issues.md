
## 2026-05-08 T7: Auto-Disable Rehabilitation Path — DEFERRED

**Status**: DEFERRED (3 subagent failures — deep, unspecified-high, unspecified-high all aborted/timed out)

**Root cause of failures**: Subagents appear to struggle with the scheduler.py codebase complexity. The task requires:
1. Adding `disabled_at` field to StrategyConfig model (DB schema change)
2. Modifying `auto_disable_losing_strategies()` to add trade count exemption
3. Creating new `_auto_rehabilitate_strategies()` function
4. Registering the new job in the scheduler

**Mitigation**: Strategies were manually re-enabled via SQL (T8). The existing `strategy_rehabilitator.py` still works for manual rehabilitation (50% WR + 7-day cooldown). The lightweight path can be implemented as a standalone task later.

**Impact**: LOW — strategies are now re-enabled and will trade in paper mode. The lack of auto-rehabilitation means if they get auto-disabled again, they'll stay disabled until manual intervention. This is acceptable for now.

## 2026-05-08 Wave 1 Learnings

- `apply_profile()` was already called at startup from comprehensive-fix phase — T1 only needed import cleanup
- Confidence normalization used `abs(edge + min_edge) / min_edge` pattern with zero-division guard
- T4 subagent crashed with 200+ file diff — changes never applied, so no scope creep
- `_cfg()` helper pattern used throughout strategies for settings access

## 2026-05-08 Wave 2 Learnings

- Loss floor fields (`daily_loss_floor_pct`, `weekly_loss_floor_pct`) already existed in RiskProfile from comprehensive-fix
- `DAILY_LOSS_LIMIT_PCT` was a new field needed in config.py and risk_profiles.py
- `_get_bankroll()` helper added to risk_manager for dynamic limit computation
- Config had duplicate declarations that needed cleanup

## 2026-05-08 Wave 4-7 Learnings

- `.env` file overrides config defaults — must update BOTH config.py defaults AND .env values
- Per-asset lock pattern: `_trade_locks: dict[str, asyncio.Lock]` with mutex for lock creation + semaphore for global concurrency cap
- Re-indenting large blocks done via Python script (541 lines) — manual edits would be error-prone
- `role` column already existed on Trade model from comprehensive-fix phase
- WAL mode + busy_timeout already configured for SQLite race conditions
- T19-T21 were never formalized as checkboxes in the plan — they're in the Wave 7 execution strategy text
- task() subagent calls kept aborting — direct implementation was necessary for all Wave 4+ tasks
