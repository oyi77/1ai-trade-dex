# PolyEdge Critical Fix Plan — Comprehensive Implementation

**Date:** 2026-05-20
**Priority:** P0 — Data integrity & live trading reliability
**Source:** [PROMPT.md](file:///Users/paijo/1ai-poly-trader/PROMPT.md)

---

## Codebase Assessment Summary

After deep exploration of the codebase, here's what **already exists** vs what's **actually broken**:

| Fix | PROMPT.md Assumption | Codebase Reality | Actual Work Needed |
|-----|---------------------|-------------------|-------------------|
| #1 Wallet Reconciliation | "Tidak ada wallet balance reconciliation" | **Exists** — 800-line [bankroll_reconciliation.py](file:///Users/paijo/1ai-poly-trader/backend/core/wallet/bankroll_reconciliation.py) with RPC + CLOB fallback | Wire the **disabled** `wallet_sync_live` scheduler job; add deposit/withdrawal tracking columns |
| #2 Trade Mode Tracking | "trading_mode tidak konsisten" | `strategy_executor.py` **already sets** `trading_mode=mode` correctly ([L635](file:///Users/paijo/1ai-poly-trader/backend/core/strategy_executor.py#L635)) | Fix monitoring scripts that **don't filter** by `trading_mode` |
| #3 WR Monitoring | "WR monitoring manual" | [strategy_health.py](file:///Users/paijo/1ai-poly-trader/backend/core/strategy_health.py) exists but uses **5% kill threshold** (not 50%) | New WR monitor with proper thresholds + scheduler job |
| #4 Process Management | "Multiple zombie backend processes" | [polyedge.service](file:///Users/paijo/1ai-poly-trader/scripts/polyedge.service) exists, **no process lock** in [\_\_main\_\_.py](file:///Users/paijo/1ai-poly-trader/backend/__main__.py) | Add `fcntl` process lock |
| #5 Scheduler Health | "last_run=None di DB" | `ScheduledJob` model exists ([L830](file:///Users/paijo/1ai-poly-trader/backend/models/database.py#L830)), `save_scheduler_state()` **never updates** `last_run` | Add job execution listener |
| #6 Reporting Accuracy | "Vilona reports use stale bot_state" | [vilona_monitor_report.py](file:///Users/paijo/1ai-poly-trader/scripts/vilona_monitor_report.py) **doesn't filter** `trading_mode` in queries | Rewrite report queries with proper mode filtering + wallet data |

> [!IMPORTANT]
> The original PROMPT.md plan underestimates what already exists. Several fixes reduce to **wiring existing code** rather than building from scratch. The actual risk is in Fix #1 (re-enabling disabled wallet sync) and Fix #3 (correct WR thresholds).

---

## Proposed Changes

### Fix #1: Wallet Balance Reconciliation (P0)

**What exists:** `bankroll_reconciliation.py` already has:
- `fetch_pm_total_equity()` — fetches USDC cash via RPC + PM open-position value
- `fetch_pm_profile_pnl()` — fetches cumulative PnL from Polymarket profile API
- `reconcile_bot_state()` — recomputes BotState caches from trade ledger
- Live bankroll is protected by ORM flush guard ([L539-567](file:///Users/paijo/1ai-poly-trader/backend/models/database.py#L539-L567))

**What's broken:** The `wallet_sync_live` job is **explicitly disabled** in the scheduler ([L617-621](file:///Users/paijo/1ai-poly-trader/backend/core/scheduling/scheduler.py#L617-L621)) with the comment: *"disabled — contains blocking synchronous DB calls that freeze the event loop"*.

#### [MODIFY] [database.py](file:///Users/paijo/1ai-poly-trader/backend/models/database.py)

Add deposit/withdrawal tracking columns to `BotState`:
```python
# After line 531 (settlement_last_check_at)
total_deposits = Column(Float, default=0.0)
total_withdrawals = Column(Float, default=0.0)
last_wallet_sync_at = Column(DateTime, nullable=True)
wallet_pnl = Column(Float, default=0.0)  # PnL derived from wallet balance delta
```

#### [NEW] [wallet_reconciler.py](file:///Users/paijo/1ai-poly-trader/backend/core/wallet_reconciler.py)

Thin orchestration layer wrapping existing `bankroll_reconciliation` functions:

```python
class WalletReconciler:
    """
    Periodic wallet balance sync using existing bankroll_reconciliation infra.
    
    Runs as an async scheduler job. Uses thread pool for DB calls to avoid
    freezing the event loop (the original reason wallet_sync_live was disabled).
    """
    
    async def reconcile(self, mode: str = "live"):
        # 1. Fetch wallet equity via existing fetch_pm_total_equity()
        # 2. Run reconcile_bot_state() with apply=True in thread pool
        # 3. Compare wallet_pnl vs stale total_pnl, alert if >5% discrepancy
        # 4. Update last_wallet_sync_at timestamp
```

Key design decision: wraps existing functions in `asyncio.to_thread()` to solve the original blocking-DB problem that caused the job to be disabled.

#### [MODIFY] [scheduler.py](file:///Users/paijo/1ai-poly-trader/backend/core/scheduling/scheduler.py)

- Remove the disabled `wallet_sync_live` removal block (L617-621)
- Add new async-safe reconciler job every 5 minutes
- Register in `_persist_and_add_job()` for crash recovery

#### Database Migration

```sql
ALTER TABLE bot_state ADD COLUMN total_deposits FLOAT DEFAULT 0;
ALTER TABLE bot_state ADD COLUMN total_withdrawals FLOAT DEFAULT 0;
ALTER TABLE bot_state ADD COLUMN last_wallet_sync_at TIMESTAMP;
ALTER TABLE bot_state ADD COLUMN wallet_pnl FLOAT DEFAULT 0;
```

---

### Fix #2: Trade Mode Tracking (P0)

**What exists:** `strategy_executor.py` already sets `trading_mode=mode` correctly at [Trade creation (L635)](file:///Users/paijo/1ai-poly-trader/backend/core/strategy_executor.py#L635). The `scheduling_strategies.py` also passes `mode` correctly.

**What's broken:** Monitoring/reporting scripts query trades **without filtering** by `trading_mode`.

#### [MODIFY] [vilona_monitor_report.py](file:///Users/paijo/1ai-poly-trader/scripts/vilona_monitor_report.py)

The strategy PnL query at L46-55 has **no `trading_mode` filter**:
```sql
-- CURRENT (broken): counts ALL trades regardless of mode
SELECT strategy, COUNT(*), ... FROM trades 
WHERE settled = true AND timestamp >= NOW() - INTERVAL '7 days'
GROUP BY strategy

-- FIXED: filter to live trades only
SELECT strategy, COUNT(*), ... FROM trades 
WHERE settled = true AND trading_mode = 'live' 
  AND timestamp >= NOW() - INTERVAL '7 days'
GROUP BY strategy
```

#### [MODIFY] [scheduling_strategies.py](file:///Users/paijo/1ai-poly-trader/backend/core/scheduling/scheduling_strategies.py)

Audit the `strategy_cycle_job` function to verify mode is always passed through. Current code at scan_and_trade_job L399 already sets `copied["trading_mode"] = mode` — this is correct.

> [!NOTE]
> The core trade execution path is already correct. The fix is **purely in the reporting/monitoring layer**. No changes needed to `strategy_executor.py` or `scheduling_strategies.py` core logic.

---

### Fix #3: Automated WR Monitoring (P0)

**What exists:** [strategy_health.py](file:///Users/paijo/1ai-poly-trader/backend/core/strategy_health.py) has `StrategyHealthMonitor` with:
- Kill switch at **5% WR** (far too low for practical use)
- Warning at **15% WR**
- Sharpe-based kill at < -2.0 + drawdown > 50%
- PSI drift detection

The scheduler's `start_scheduler()` at [L730-743](file:///Users/paijo/1ai-poly-trader/backend/core/scheduling/scheduler.py#L730-L743) also has startup-time strategy disabling at **30% WR + $-50 PnL**.

**What's missing:** A periodic (every 6 hours) WR monitor with the **correct thresholds** from the PROMPT:
- WR < 50% + losing money → 🔴 Auto-disable
- WR < 50% + profitable → 🟡 Warning
- WR 50-60% → 🟢 OK but track trend
- WR > 60% → ✅ Healthy

#### [NEW] [wr_monitor.py](file:///Users/paijo/1ai-poly-trader/backend/core/wr_monitor.py)

```python
class WinRateMonitor:
    MIN_TRADES = 10
    WR_THRESHOLD = 0.50
    CHECK_INTERVAL_HOURS = 6
    LOOKBACK_DAYS = 3
    
    async def check_all_strategies(self):
        """Iterate active strategies, compute rolling WR, auto-disable losers."""
        # Uses trades table with trading_mode='live' AND settled=true
        # Computes per-strategy WR over last 3 days
        # Auto-disables via StrategyConfig.enabled = False
        # Publishes event_bus "strategy_wr_disabled" for alerting
    
    async def auto_disable(self, strategy, stats):
        # Update strategy_config.enabled = False, disabled_at = NOW()
        # Log action to audit_logger
        # Send Telegram alert via notifier
```

> [!WARNING]
> The existing `StrategyHealthMonitor.KILL_WIN_RATE = 0.05` is dangerously low — a strategy can lose 95% of trades before being killed. The new WR monitor with 50% threshold will catch degradation **much earlier**. These two systems should coexist: WR monitor for operational health, HealthMonitor for catastrophic kill-switch.

#### [MODIFY] [scheduler.py](file:///Users/paijo/1ai-poly-trader/backend/core/scheduling/scheduler.py)

Add WR monitor job:
```python
from backend.core.wr_monitor import wr_monitor_job

scheduler.add_job(
    wr_monitor_job,
    IntervalTrigger(hours=6, jitter=600),
    id="wr_monitor",
    replace_existing=True,
    max_instances=1,
    misfire_grace_time=3600,
)
```

---

### Fix #4: Process Management (P1)

**What exists:** 
- `scripts/polyedge.service` systemd unit with `Restart=always`
- `polyedge-api.service` for the API server
- `deploy/polyedge-monitor.service` for the monitor daemon

**What's missing:** Runtime process lock to prevent multiple backend instances from running concurrently.

#### [MODIFY] [\_\_main\_\_.py](file:///Users/paijo/1ai-poly-trader/backend/__main__.py)

Add `fcntl`-based exclusive file lock:

```python
import fcntl
import sys

LOCK_FILE = "/tmp/polyedge.lock"

def acquire_lock():
    """Acquire exclusive process lock. Exit if another instance is running."""
    fp = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fp.write(str(os.getpid()))
        fp.flush()
        return fp  # Must keep reference to prevent GC closing the file
    except IOError:
        print("ERROR: Another PolyEdge instance is already running. Exiting.")
        sys.exit(1)

if __name__ == "__main__":
    _lock_fp = acquire_lock()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
```

> [!TIP]
> The systemd service already handles restart-on-crash. The `fcntl` lock specifically prevents the scenario where a user manually runs `python -m backend` while systemd is already running the service, creating zombie schedulers with conflicting APScheduler jobs.

---

### Fix #5: Scheduler Health (P1)

**What exists:** 
- `ScheduledJob` model with `last_run` column ([L844](file:///Users/paijo/1ai-poly-trader/backend/models/database.py#L844))
- `save_scheduler_state()` persists job registration metadata
- `load_scheduler_state()` restores jobs on restart

**What's broken:** No code **ever updates** `ScheduledJob.last_run` after job execution. The `save_scheduler_state()` function only writes registration metadata (trigger, kwargs, etc.), not execution timestamps.

#### [MODIFY] [scheduler.py](file:///Users/paijo/1ai-poly-trader/backend/core/scheduling/scheduler.py)

Add an APScheduler event listener that updates `last_run` after each job completes:

```python
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

def _job_executed_listener(event):
    """Update ScheduledJob.last_run and next_run after each job execution."""
    job_id = event.job_id
    try:
        from backend.db.utils import get_db_session
        with get_db_session() as db:
            row = db.query(ScheduledJob).filter(
                ScheduledJob.job_name == job_id
            ).first()
            if row:
                row.last_run = datetime.now(timezone.utc)
                # Calculate next_run from the scheduler
                sched = _get_scheduler()
                if sched:
                    job = sched.get_job(job_id)
                    if job and job.next_run_time:
                        row.next_run = job.next_run_time
                db.commit()
    except Exception as exc:
        logger.debug(f"Failed to update last_run for job '{job_id}': {exc}")

# In start_scheduler(), before scheduler.start():
scheduler.add_listener(
    _job_executed_listener, 
    EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
)
```

---

### Fix #6: Reporting Accuracy (P0)

**What exists:** [vilona_monitor_report.py](file:///Users/paijo/1ai-poly-trader/scripts/vilona_monitor_report.py) reads:
- `bot_state` table directly for account data (L64-82) — gets **stale** `bankroll` and `total_pnl`
- Strategy PnL from `trades` without `trading_mode` filter (L46-55)
- 24h trade count without `trading_mode` filter (L85-90)

#### [MODIFY] [vilona_monitor_report.py](file:///Users/paijo/1ai-poly-trader/scripts/vilona_monitor_report.py)

Complete rewrite of data sourcing:

1. **Wallet balance**: Use `fetch_pm_total_equity()` from bankroll_reconciliation (real balance)
2. **PnL**: Compute from `SUM(pnl) FROM trades WHERE trading_mode='live' AND settled=true`
3. **Strategy stats**: Filter all queries by `trading_mode = 'live'`
4. **Open positions**: `FROM trades WHERE trading_mode='live' AND settled=false`
5. **WR computation**: Use `trades.trading_mode` not `strategy_config.mode`

Key query fixes:
```sql
-- Strategy PnL (fix L46-55): add trading_mode filter
SELECT strategy, COUNT(*), ...
FROM trades 
WHERE settled = true AND trading_mode = 'live'
  AND timestamp >= NOW() - INTERVAL '7 days'
GROUP BY strategy ORDER BY SUM(pnl) DESC

-- 24h trades (fix L85-90): add trading_mode filter
SELECT COUNT(*), COALESCE(SUM(pnl), 0)
FROM trades 
WHERE trading_mode = 'live'
  AND timestamp >= NOW() - INTERVAL '24 hours'

-- Open positions (new): real exposure
SELECT COUNT(*), SUM(size) FROM trades 
WHERE trading_mode = 'live' AND settled = false
```

Also add a new section for **wallet balance comparison**:
```python
# Compare bot_state.bankroll vs real wallet equity
report["wallet_health"] = {
    "bot_state_bankroll": float(bot_state_bankroll),
    "real_wallet_equity": float(real_equity),
    "discrepancy_pct": abs(bot_state_bankroll - real_equity) / max(real_equity, 1) * 100,
    "last_sync_at": str(last_wallet_sync_at),
}
```

---

## Execution Order

| Phase | Fix | Est. Time | Dependencies | Risk |
|-------|-----|-----------|-------------|------|
| 1 | **#2** Trade Mode Tracking | 20 min | None | 🟢 Low — query-only changes |
| 2 | **#6** Reporting Accuracy | 40 min | Fix #2 | 🟢 Low — script rewrite |
| 3 | **#3** WR Monitoring | 45 min | Fix #2 | 🟡 Medium — new module + scheduler integration |
| 4 | **#5** Scheduler Health | 20 min | None | 🟢 Low — event listener |
| 5 | **#4** Process Management | 15 min | None | 🟢 Low — lock file |
| 6 | **#1** Wallet Reconciliation | 1.5 hours | None | 🟡 Medium — re-enabling disabled job + migration |

**Total estimated time: ~3.5 hours** (reduced from original 5 hours because much infrastructure already exists)

---

## Verification Plan

### Automated Tests

```bash
# Run existing test suite to ensure no regressions
pytest tests/ -x --tb=short

# Specific new tests to write:
# - test_wr_monitor.py: threshold logic, auto-disable behavior
# - test_wallet_reconciler.py: async reconciliation, discrepancy alerting
# - test_process_lock.py: fcntl lock acquisition/rejection
# - test_scheduler_listener.py: last_run updates after job execution
```

### Manual Verification

- [ ] `bot_state.bankroll` == Polymarket wallet balance (±1%)
- [ ] `bot_state.total_pnl` == `SUM(trades.pnl WHERE trading_mode='live')`
- [ ] All trades have `trading_mode` set correctly
- [ ] WR monitor runs every 6 hours, auto-disables < 50% WR strategies
- [ ] Single backend process (no zombies)
- [ ] Scheduler jobs have `last_run` updated in DB
- [ ] Vilona reports show real wallet balance and PnL
- [ ] Running `python -m backend` twice fails with lock error

### Production Deployment Checklist

1. Run Alembic migration for new BotState columns
2. Deploy updated `__main__.py` with process lock
3. Restart systemd service (will acquire lock)
4. Verify scheduler registers WR monitor and wallet reconciler jobs
5. Wait 6 hours, check `scheduled_jobs.last_run` values
6. Run `scripts/vilona_monitor_report.py` and verify live mode data

---

## Open Questions

> [!IMPORTANT]
> **Q1: Deposit/Withdrawal Tracking Source**
> The PROMPT.md proposes tracking `total_deposits` and `total_withdrawals`, but there's no on-chain deposit detection implemented. Should we:
> - (a) Parse blockchain transaction history to detect deposits/withdrawals automatically?
> - (b) Add a manual CLI command (`python -m backend deposit --amount 100`)?
> - (c) Defer deposit tracking and rely solely on `fetch_pm_total_equity()` for live balance?
>
> Recommendation: Option (c) for now. The existing `fetch_pm_total_equity()` already gives real-time balance. Deposit tracking is a nice-to-have but not blocking for the P0 data integrity fix.

> [!WARNING]
> **Q2: WR Monitor vs Strategy Health Monitor Coexistence**
> The existing `StrategyHealthMonitor` has a 5% kill threshold (emergency kill-switch). The new WR monitor has a 50% threshold (operational health). Should we:
> - (a) Keep both systems running independently?
> - (b) Raise `StrategyHealthMonitor.KILL_WIN_RATE` from 5% to a more reasonable 30%?
> - (c) Deprecate `StrategyHealthMonitor` in favor of the new WR monitor?
>
> Recommendation: Option (a) — keep both. They serve different purposes.

> [!IMPORTANT]
> **Q3: Wallet Sync Frequency**
> The disabled `wallet_sync_live` job was removed because of blocking DB calls. The new implementation wraps calls in `asyncio.to_thread()`. Should the sync frequency be:
> - (a) Every 60 seconds (original)
> - (b) Every 5 minutes (PROMPT.md proposal)
> - (c) Every 2 minutes (compromise)
>
> Recommendation: Option (b) — every 5 minutes. Reduces API call volume and is sufficient for reconciliation alerting.
