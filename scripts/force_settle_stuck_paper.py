#!/usr/bin/env python3
"""Force-settle 254 stuck paper trades (weather/event markets unable to resolve)."""
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text

engine = create_engine(os.getenv("DATABASE_URL"))

with engine.connect() as conn:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=5)

    # Count before
    before = conn.execute(text(
        "SELECT COUNT(*) FROM trades WHERE trading_mode='paper' "
        "AND settled=TRUE AND pnl IS NULL"
    )).fetchone()
    print(f"Before: {before[0]} stuck paper trades")

    if before[0] == 0:
        print("Nothing to do.")
        exit(0)

    # Force-settle as loss
    result = conn.execute(
        text(
            "UPDATE trades SET pnl=0.0, result='loss', settlement_value=0.0, "
            "settlement_time=:now, settlement_source='force_closed_unresolved' "
            "WHERE trading_mode='paper' AND settled=TRUE AND pnl IS NULL "
            "AND timestamp < :cutoff"
        ),
        {"now": now, "cutoff": cutoff},
    )
    conn.commit()
    print(f"Force-settled: {result.rowcount} trades")

    # Verify
    after = conn.execute(text(
        "SELECT COUNT(*) FROM trades WHERE trading_mode='paper' "
        "AND settled=TRUE AND pnl IS NULL"
    )).fetchone()
    total = conn.execute(text(
        "SELECT COUNT(*) FROM trades WHERE trading_mode='paper' AND pnl IS NOT NULL"
    )).fetchone()
    summary = conn.execute(text(
        "SELECT COUNT(*), ROUND(COALESCE(SUM(pnl),0)::numeric,2), "
        "ROUND(100.0*SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0),1) "
        "FROM trades WHERE trading_mode='paper' AND pnl IS NOT NULL"
    )).fetchone()

    print(f"After: {after[0]} stuck (should be 0)")
    print(f"Total paper settled: {total[0]} trades, PnL=${summary[1]}, WR={summary[2]}%")
    print("DONE.")
