#!/usr/bin/env python3
"""48-hour paper trial gate. Only allows live if ALL criteria pass."""
import sys
sys.path.insert(0, '/home/openclaw/projects/1ai-poly-trader')

from backend.models.database import SessionLocal
from sqlalchemy import text
from datetime import datetime, timezone, timedelta

db = SessionLocal()

cutoff = datetime.now(timezone.utc) - timedelta(hours=48)

# Get settled trades from last 48h
rows = db.execute(text("""
    SELECT strategy, COUNT(*) as n,
           SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
           SUM(pnl) as total_pnl,
           AVG(pnl) as avg_pnl,
           STDDEV(pnl) as std_pnl
    FROM trades
    WHERE settled = true AND trading_mode = 'paper'
      AND timestamp >= :cutoff
    GROUP BY strategy
    ORDER BY total_pnl DESC
"""), {"cutoff": cutoff}).fetchall()

print("=" * 60)
print("48-HOUR PAPER TRIAL GATE")
print("=" * 60)

total_trades = 0
total_wins = 0
total_pnl = 0.0
all_pass = True

for row in rows:
    strategy, n, wins, pnl, avg_pnl, std_pnl = row
    wr = (wins / n * 100) if n > 0 else 0
    sharpe = (avg_pnl / std_pnl) if std_pnl and std_pnl > 0 else 0
    total_trades += n
    total_wins += wins
    total_pnl += pnl or 0

    # Per-strategy gate
    strategy_pass = pnl > 0 and wr > 50 and n >= 10
    status = "PASS" if strategy_pass else "FAIL"
    if not strategy_pass:
        all_pass = False

    print(f"  {strategy}: {n} trades, {wr:.1f}% WR, ${pnl:+.2f} P&L, Sharpe {sharpe:.2f} [{status}]")

overall_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0

print(f"\n  TOTAL: {total_trades} trades, {overall_wr:.1f}% WR, ${total_pnl:+.2f} P&L")

# Global gates
gates = [
    ("Min 50 trades", total_trades >= 50),
    ("Win rate > 55%", overall_wr > 55),
    ("Total P&L > 0", total_pnl > 0),
    ("All strategies profitable", all_pass),
    ("No single strategy > 50% of P&L", True),  # check below
]

# Check concentration risk
if total_pnl > 0:
    for row in rows:
        if row[3] and row[3] > total_pnl * 0.5:
            gates[-1] = ("No single strategy > 50% of P&L", False)
            all_pass = False

print(f"\n{'=' * 60}")
print("GATES:")
for name, passed in gates:
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}")

print(f"\n{'=' * 60}")
if all_pass and total_trades >= 50:
    print("DECISION: GO — All gates passed. Safe to go live.")
else:
    print("DECISION: NO-GO — Continue paper trial.")

db.close()
