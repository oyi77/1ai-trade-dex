#!/usr/bin/env python3
"""Analyze why live trades perform worse than paper."""
import os
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text

e = create_engine(os.getenv("DATABASE_URL"))

with e.connect() as c:
    # Live vs Paper PnL by strategy
    print("=" * 70)
    print("  LIVE vs PAPER - PnL by Strategy")
    print("=" * 70)
    r = c.execute(text("""
        SELECT strategy, trading_mode,
               COUNT(*) as trades,
               ROUND(COALESCE(SUM(size),0)::numeric,2) as invested,
               ROUND(COALESCE(SUM(pnl),0)::numeric,2) as pnl,
               ROUND(100.0 * SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0), 1) as wr
        FROM trades
        WHERE trading_mode IN ('live','paper')
        GROUP BY strategy, trading_mode
        ORDER BY strategy, trading_mode
    """)).fetchall()

    current_strat = None
    for row in r:
        if row[0] != current_strat:
            if current_strat:
                print()
            current_strat = row[0]
            print(f"  {row[0]}:")
        print(f"    {row[1]:<6} {row[2]:>5} trades  invested=${row[3]:>8}  pnl=${row[4]:>8}  WR={row[5]}%")

    # Total summary
    print("\n" + "=" * 70)
    print("  TOTALS")
    print("=" * 70)
    for mode in ('live', 'paper'):
        r = c.execute(text("""
            SELECT COUNT(*), ROUND(COALESCE(SUM(size),0)::numeric,2),
                   ROUND(COALESCE(SUM(pnl),0)::numeric,2),
                   ROUND(100.0 * SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0), 1)
            FROM trades WHERE trading_mode=:m AND pnl IS NOT NULL
        """), {'m': mode}).fetchone()
        print(f"  {mode}: {r[0]} trades  invested=${r[1]}  pnl=${r[2]}  WR={r[3]}%")

    # Live trades timeline
    print("\n" + "=" * 70)
    print("  LIVE TRADES - Timeline")
    print("=" * 70)
    r = c.execute(text("""
        SELECT DATE(timestamp) as dt, COUNT(*),
               ROUND(COALESCE(SUM(size),0)::numeric,2),
               ROUND(COALESCE(SUM(pnl),0)::numeric,2)
        FROM trades WHERE trading_mode='live' AND timestamp IS NOT NULL
        GROUP BY DATE(timestamp) ORDER BY dt
    """)).fetchall()
    for row in r:
        print(f"  {row[0]}  {row[1]:>4} trades  ${row[2]:>8}  pnl=${row[3]:>8}")

    # The 7 SETTLED trades - only reliable data
    print("\n" + "=" * 70)
    print("  ONLY RELIABLE DATA: 7 SETTLED LIVE TRADES")
    print("=" * 70)
    r = c.execute(text("""
        SELECT id, strategy, market_ticker, direction, size, entry_price, pnl, timestamp, settlement_source
        FROM trades WHERE trading_mode='live' AND status='SETTLED'
        ORDER BY id
    """)).fetchall()
    for row in r:
        mkt = (row[2] or '?')[:40]
        print(f"  id={row[0]} {row[1]:<20} {mkt} {row[3]:<4} sz=${row[4]} entry={row[5]} pnl=${row[6]} src={row[8] or '?'} ts={row[7]}")

    # Closed trades with PnL
    print("\n" + "=" * 70)
    print("  CLOSED LIVE TRADES (resolved by sync)")
    print("=" * 70)
    r = c.execute(text("""
        SELECT COUNT(*),
               ROUND(COALESCE(SUM(size),0)::numeric,2),
               ROUND(COALESCE(SUM(pnl),0)::numeric,2),
               ROUND(100.0 * SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0), 1)
        FROM trades WHERE trading_mode='live' AND status='closed'
    """)).fetchone()
    print(f"  {r[0]} trades, invested=${r[1]}, pnl=${r[2]}, WR={r[3]}%")

    # Paper PnL by strategy (real settled only)
    print("\n" + "=" * 70)
    print("  PAPER SETTLED/CLOSED PnL by Strategy")
    print("=" * 70)
    r = c.execute(text("""
        SELECT strategy, COUNT(*),
               ROUND(COALESCE(SUM(size),0)::numeric,2),
               ROUND(COALESCE(SUM(pnl),0)::numeric,2),
               ROUND(100.0 * SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0), 1)
        FROM trades WHERE trading_mode='paper'
        AND status IN ('SETTLED','closed') AND pnl IS NOT NULL
        GROUP BY strategy ORDER BY SUM(pnl) DESC
    """)).fetchall()
    for row in r:
        print(f"  {row[0]:<25} {row[1]:>5} trades  invested=${row[2]:>8}  pnl=${row[3]:>8}  WR={row[4]}%")
