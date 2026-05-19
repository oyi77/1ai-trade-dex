# PolyEdge Critical Fix Plan
**Date:** 2026-05-20
**Priority:** P0 — Data integrity & live trading reliability

---

## Problem Summary

| # | Issue | Severity | Impact |
|---|---|---|---|
| 1 | `bot_state.total_pnl` stale — tidak sync dengan trades | 🔴 Critical | Reporting salah, keputusan berdasarkan data palsu |
| 2 | `trades.trading_mode` tidak konsisten — paper trades diatribusikan ke live | 🔴 Critical | PnL salah, strategy evaluation salah |
| 3 | Tidak ada wallet balance reconciliation | 🔴 Critical | Tidak tahu real PnL |
| 4 | Multiple zombie backend processes | 🟡 High | Resource waste, scheduler conflict |
| 5 | Scheduler jobs `last_run=None` di DB | 🟡 Monitoring blind | Tidak bisa audit job execution |
| 6 | WR monitoring manual, tidak automated | 🟡 High | Strategy bisa bleed tanpa terdeteksi |
| 7 | cex_pm_leadlag today 37.5% WR | 🟡 Medium | Below 50% threshold |

---

## Fix #1: Wallet Balance Reconciliation (P0)

**Goal:** Track real wallet balance, calculate actual PnL from balance delta.

### Implementation:
```python
# backend/core/wallet_reconciler.py

class WalletReconciler:
    """
    Periodically sync Polymarket wallet balance and calculate real PnL.
    
    Flow:
    1. Fetch wallet USDC balance from Polymarket API
    2. Calculate: real_pnl = current_balance - initial_deposit - deposits + withdrawals
    3. Update bot_state.bankroll with real balance
    4. Log discrepancy if bot_state.total_pnl != real_pnl
    """
    
    async def reconcile(self, mode: str = "live"):
        current_balance = await self.fetch_wallet_balance(mode)
        initial = self.get_initial_bankroll(mode)
        deposits = self.get_deposits(mode)
        withdrawals = self.get_withdrawals(mode)
        
        real_pnl = current_balance - initial - deposits + withdrawals
        
        # Update bot_state
        self.update_bot_state(mode, 
            bankroll=current_balance,
            total_pnl=real_pnl
        )
        
        # Alert if discrepancy > 5%
        if abs(real_pnl - self.get_stale_pnl(mode)) > abs(real_pnl * 0.05):
            self.alert_discrepancy(mode, stale=stale_pnl, real=real_pnl)
```

### Files to create/modify:
- `backend/core/wallet_reconciler.py` — NEW
- `backend/core/scheduling/scheduler.py` — Add reconciler job (every 5 min)
- `backend/models/database.py` — Add `deposits`/`withdrawals` tracking to bot_state

### Database changes:
```sql
ALTER TABLE bot_state ADD COLUMN total_deposits NUMERIC DEFAULT 0;
ALTER TABLE bot_state ADD COLUMN total_withdrawals NUMERIC DEFAULT 0;
ALTER TABLE bot_state ADD COLUMN last_wallet_sync_at TIMESTAMP;
ALTER TABLE bot_state ADD COLUMN wallet_pnl NUMERIC DEFAULT 0;
```

---

## Fix #2: Trade Mode Tracking (P0)

**Goal:** Setiap trade harus record `trading_mode` dengan benar.

### Root cause:
- `strategy_executor` tidak selalu set `trading_mode` saat insert trade
- Query "live trades" pakai `strategy_config.mode` (current config) bukan `trades.trading_mode` (actual execution mode)

### Implementation:
```python
# In backend/core/strategy_executor.py
# BEFORE inserting trade:
trade = Trade(
    ...,
    trading_mode=execution_mode,  # MUST be set: 'paper' | 'testnet' | 'live'
    strategy=strategy_name,
)
```

### Fix queries:
```python
# WRONG (current):
SELECT * FROM trades WHERE strategy IN (
    SELECT strategy_name FROM strategy_config WHERE mode = 'live'
)

# CORRECT:
SELECT * FROM trades WHERE trading_mode = 'live'
```

### Files to modify:
- `backend/core/strategy_executor.py` — Ensure trading_mode always set
- `backend/core/scheduling/scheduling_strategies.py` — Pass mode correctly
- All monitoring scripts — Use `trades.trading_mode` not `strategy_config.mode`

---

## Fix #3: Automated WR Monitoring (P0)

**Goal:** Auto-detect strategy degradation, auto-disable losing strategies.

### Rules:
| Condition | Action |
|---|---|
| WR < 50% + losing money | 🔴 Auto-disable, enter improvement stage |
| WR < 50% + profitable | 🟡 Warning, monitor closely |
| WR 50-60% | 🟢 OK but track trend |
| WR > 60% | ✅ Healthy |

### Implementation:
```python
# backend/core/wr_monitor.py

class WinRateMonitor:
    MIN_TRADES = 10  # Minimum trades before evaluation
    WR_THRESHOLD = 0.50
    CHECK_INTERVAL_HOURS = 6
    
    async def check_all_strategies(self):
        for strategy in self.get_active_strategies():
            stats = self.get_strategy_stats(strategy, days=3)
            
            if stats.trades < self.MIN_TRADES:
                continue
                
            if stats.win_rate < self.WR_THRESHOLD:
                if stats.pnl < 0:
                    await self.auto_disable(strategy, stats)
                    await self.alert("critical", 
                        f"{strategy} DISABLED: WR={stats.win_rate:.1%}, PnL=${stats.pnl:.2f}")
                else:
                    await self.alert("warning",
                        f"{strategy} low WR but profitable: WR={stats.win_rate:.1%}, PnL=${stats.pnl:.2f}")
    
    async def auto_disable(self, strategy, stats):
        # Update strategy_config
        await self.db.execute("""
            UPDATE strategy_config 
            SET enabled = false, disabled_at = NOW()
            WHERE strategy_name = :name
        """, {"name": strategy})
        
        # Log action
        await self.log_action("auto_disable", strategy, stats)
```

### Files to create:
- `backend/core/wr_monitor.py` — NEW
- Add to scheduler: every 6 hours

---

## Fix #4: Process Management (P1)

**Goal:** Single backend process, no zombies.

### Implementation:
```bash
# Add systemd service for polyedge
# /etc/systemd/system/polyedge.service

[Unit]
Description=PolyEdge Trading Bot
After=network.target postgresql.service

[Service]
Type=simple
User=openclaw
WorkingDirectory=/home/openclaw/projects/polyedge
ExecStart=/home/openclaw/projects/polyedge/venv/bin/python -m backend
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

### Process lock:
```python
# In backend/__main__.py
import fcntl
LOCK_FILE = "/tmp/polyedge.lock"

def acquire_lock():
    fp = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fp
    except IOError:
        print("Another instance is running. Exiting.")
        sys.exit(1)
```

### Files to create:
- `/etc/systemd/system/polyedge.service` — NEW
- `backend/__main__.py` — Add process lock

---

## Fix #5: Scheduler Health (P1)

**Goal:** Scheduler jobs execute properly, DB reflects real status.

### Implementation:
```python
# After each job execution, update scheduled_jobs table
async def update_job_status(job_name: str):
    await db.execute("""
        UPDATE scheduled_jobs 
        SET last_run = NOW(), 
            next_run = :next_run
        WHERE job_name = :name
    """, {"name": job_name, "next_run": calculate_next_run(job_name)})
```

### Files to modify:
- `backend/core/scheduling/scheduler.py` — Add DB update after job execution

---

## Fix #6: Reporting Accuracy (P0)

**Goal:** Vilona reports use real data, not stale bot_state.

### New report data source:
```python
def generate_report():
    # 1. Wallet balance (real)
    balance = reconciler.get_current_balance("live")
    
    # 2. PnL from trades table WHERE trading_mode='live'
    pnl = db.execute("""
        SELECT SUM(pnl) FROM trades 
        WHERE trading_mode = 'live' AND settled = true
    """).scalar()
    
    # 3. Strategy stats from trades (not bot_state)
    strategies = db.execute("""
        SELECT strategy, COUNT(*), SUM(pnl), 
               AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END)
        FROM trades WHERE trading_mode = 'live' AND settled = true
        GROUP BY strategy
    """).fetchall()
    
    # 4. Open positions
    open_pos = db.execute("""
        SELECT COUNT(*), SUM(size) FROM trades 
        WHERE trading_mode = 'live' AND settled = false
    """).fetchone()
```

### Files to modify:
- `scripts/vilona_monitor_report.py` — Rewrite to use trades table
- `agents/vilona-monitor/monitor_loop.py` — Use new data source

---

## Execution Order

| Phase | Fix | Time | Dependencies |
|---|---|---|---|
| 1 | #2 Trade Mode Tracking | 30 min | None |
| 2 | #6 Reporting Accuracy | 30 min | Fix #2 |
| 3 | #3 WR Monitoring | 1 hour | Fix #2 |
| 4 | #1 Wallet Reconciliation | 2 hours | None |
| 5 | #4 Process Management | 30 min | None |
| 6 | #5 Scheduler Health | 30 min | Fix #4 |

**Total estimated time: 5 hours**

---

## Success Criteria

- [ ] `bot_state.bankroll` == Polymarket wallet balance (±1%)
- [ ] `bot_state.total_pnl` == SUM(trades.pnl WHERE trading_mode='live')
- [ ] All trades have `trading_mode` set correctly
- [ ] WR monitor runs every 6 hours, auto-disables < 50% WR strategies
- [ ] Single backend process (no zombies)
- [ ] Scheduler jobs have `last_run` updated in DB
- [ ] Vilona reports show real wallet balance and PnL

---

*Plan created: 2026-05-20 00:27 WIB*
*Author: Vilona*
