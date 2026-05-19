#!/usr/bin/env python3
"""Analyze btc_oracle strategy performance."""
import sys
sys.path.insert(0, "/home/openclaw/projects/polyedge")

from sqlalchemy import create_engine, text
from backend.config import settings

engine = create_engine(settings.DATABASE_URL)

with engine.connect() as conn:
    # By direction
    rows = conn.execute(text("""
        SELECT direction, COUNT(*), COALESCE(SUM(pnl), 0),
               COALESCE(AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END), 0),
               COALESCE(AVG(pnl), 0),
               COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN pnl <= 0 THEN pnl ELSE 0 END), 0)
        FROM trades WHERE strategy = 'btc_oracle' AND settled = true
        GROUP BY direction
    """)).fetchall()
    print("=== BY DIRECTION ===")
    for r in rows:
        print(f"  {r[0]:5s} | {r[1]:4d}t | pnl={r[2]:+8.2f} | wr={r[3]:.1%} | avg={r[4]:+.3f} | gw={r[5]:+.2f} gl={r[6]:+.2f}")

    # By price bucket
    rows = conn.execute(text("""
        SELECT 
            CASE 
                WHEN entry_price < 0.35 THEN 'low (<0.35)'
                WHEN entry_price < 0.50 THEN 'mid-low (0.35-0.50)'
                WHEN entry_price < 0.65 THEN 'mid-high (0.50-0.65)'
                ELSE 'high (>0.65)'
            END as bucket,
            COUNT(*), COALESCE(SUM(pnl), 0),
            COALESCE(AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END), 0)
        FROM trades WHERE strategy = 'btc_oracle' AND settled = true
        GROUP BY bucket ORDER BY MIN(entry_price)
    """)).fetchall()
    print("\n=== BY PRICE BUCKET ===")
    for r in rows:
        print(f"  {r[0]:20s} | {r[1]:4d}t | pnl={r[2]:+8.2f} | wr={r[3]:.1%}")

    # Last 20 trades
    rows = conn.execute(text("""
        SELECT market_ticker, direction, entry_price, pnl, timestamp
        FROM trades WHERE strategy = 'btc_oracle'
        ORDER BY timestamp DESC LIMIT 20
    """)).fetchall()
    print("\n=== LAST 20 TRADES ===")
    for r in rows:
        pnl_str = f"{r[3]:+.2f}" if r[3] is not None else "pending"
        print(f"  {str(r[0])[:50]:50s} | {r[1]:5s} | entry={r[2]} | pnl={pnl_str} | {r[4]}")

    # By hour
    rows = conn.execute(text("""
        SELECT EXTRACT(HOUR FROM timestamp), COUNT(*),
               COALESCE(SUM(pnl), 0),
               COALESCE(AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END), 0)
        FROM trades WHERE strategy = 'btc_oracle' AND settled = true
        GROUP BY EXTRACT(HOUR FROM timestamp) ORDER BY EXTRACT(HOUR FROM timestamp)
    """)).fetchall()
    print("\n=== BY HOUR (UTC) ===")
    for r in rows:
        print(f"  {int(r[0]):02d}:00 | {r[1]:4d}t | pnl={r[2]:+8.2f} | wr={r[3]:.1%}")
