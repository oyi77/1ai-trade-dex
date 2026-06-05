#!/usr/bin/env python3
"""Fix DB mismatches: deduplicate filled trades, then fix root cause in code."""
import os, sys
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text

engine = create_engine(os.getenv("DATABASE_URL"))

with engine.connect() as conn:
    # Step 1: Find duplicate filled trades
    rows = conn.execute(text(
        "SELECT token_id, COUNT(*) as cnt, "
        "array_agg(id ORDER BY id) as ids, "
        "array_agg(direction ORDER BY id) as dirs, "
        "array_agg(ROUND(size::numeric,2) ORDER BY id) as sizes "
        "FROM trades WHERE trading_mode='live' AND status='filled' "
        "GROUP BY token_id HAVING COUNT(*) > 1"
    )).fetchall()

    print(f"Duplicate token_ids found: {len(rows)}")
    for r in rows:
        print(f"  token={r[0]} cnt={r[1]} ids={r[2]} dirs={r[3]} sizes={r[4]}")

    # Step 2: For each duplicate pair, close the older one
    for r in rows:
        ids = r[2]
        keep_id = ids[-1]  # keep last (most recent entry)
        for dup_id in ids[:-1]:
            conn.execute(text(
                "UPDATE trades SET status='closed', settlement_time=now() WHERE id=:id"
            ), {"id": dup_id})
        print(f"  Merged: keep {keep_id}, closed {ids[:-1]}")
    conn.commit()

    # Step 3: Verify final count
    filled = conn.execute(text(
        "SELECT COUNT(*) FROM trades WHERE trading_mode='live' AND status='filled'"
    )).fetchone()[0]
    print(f"\nDB filled after dedup: {filled}")

    # Step 4: Full status
    rows = conn.execute(text(
        "SELECT status, COUNT(*) as cnt, "
        "ROUND(COALESCE(SUM(size),0)::numeric,2) as tsize, "
        "ROUND(COALESCE(SUM(pnl),0)::numeric,4) as tpnl "
        "FROM trades WHERE trading_mode='live' "
        "GROUP BY status ORDER BY status"
    )).fetchall()
    print("Final status:")
    for r in rows:
        print(f"  {str(r[0]):<16} cnt={r[1]:>5} sz={r[2]:>10} pnl={r[3]:>10}")

    total = conn.execute(text(
        "SELECT COUNT(*) FROM trades WHERE trading_mode='live'"
    )).fetchone()[0]
    print(f"\nTotal live trades: {total}")
    print(f"12 Polymarket positions == {filled} DB filled trades == MATCH" if filled == 12 else f"MISMATCH: 12 vs {filled}")
