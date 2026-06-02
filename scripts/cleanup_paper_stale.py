#!/usr/bin/env python3
"""One-shot: clean stale paper trades via Gamma API."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta, timezone

ENGINE = create_engine(os.getenv("DATABASE_URL"))

async def main():
    # Step 1: Mark stale paper trades settled=True with pnl=None
    with ENGINE.connect() as conn:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        result = conn.execute(
            text(
                "UPDATE trades SET settled=TRUE, pnl=NULL, settlement_value=NULL, "
                "settlement_time=:now WHERE trading_mode='paper' AND settled=FALSE "
                "AND timestamp < :cutoff AND pnl IS NULL"
            ),
            {"now": datetime.now(timezone.utc), "cutoff": cutoff},
        )
        conn.commit()
        print(f"Marked {result.rowcount} paper trades for Gamma resolution")

        r = conn.execute(
            text(
                "SELECT COUNT(*) FROM trades WHERE trading_mode='paper' "
                "AND settled=TRUE AND pnl IS NULL"
            )
        ).fetchone()
        print(f"Ready for Gamma: {r[0]}")

    # Step 2: Run Gamma resolution (needs Session, not Connection)
    from backend.core.settlement.settlement_helpers import resolve_paper_trades
    from sqlalchemy.orm import Session

    with Session(ENGINE) as session:
        try:
            result = await resolve_paper_trades(session)
            session.commit()
            print(f"Gamma resolved: {len(result)} trades")
            if result:
                wins = sum(1 for t in result if getattr(t, "result", "") == "win")
                losses = len(result) - wins
                total_pnl = sum(getattr(t, "pnl", 0) or 0 for t in result)
                print(f"  {wins}W/{losses}L, PnL=${total_pnl:+.2f}")
            else:
                print("  Warning: 0 resolved — markets may not be settled yet")
        except Exception as ex:
            print(f"  Error: {type(ex).__name__}: {ex}")

    # Step 3: Force-settle remaining Gamma-unresolvable trades (weather/special markets)
    # These markets return invalid outcomePrices from Gamma (e.g. "[" instead of floats).
    # Rather than leaving them stuck forever, force-settle with PnL=0 (neutral).
    with Session(ENGINE) as session:
        remaining = session.execute(text(
            "SELECT COUNT(*) FROM trades WHERE trading_mode='paper' "
            "AND settled=TRUE AND pnl IS NULL"
        )).fetchone()[0]
        if remaining > 0:
            result = session.execute(text(
                "UPDATE trades SET pnl=0.0, settlement_value=0.5, result='loss', "
                "settlement_source='force_settled', settlement_time=:now "
                "WHERE trading_mode='paper' AND settled=TRUE AND pnl IS NULL "
                "AND timestamp < :cutoff"
            ), {"now": datetime.now(timezone.utc), "cutoff": datetime.now(timezone.utc) - timedelta(hours=1)})
            session.commit()
            print(f"Force-settled {result.rowcount} Gamma-unresolvable paper trades (PnL=$0)")

    # Step 4: Check remaining
    with ENGINE.connect() as conn:
        r = conn.execute(
            text(
                "SELECT COUNT(*) FROM trades WHERE trading_mode='paper' "
                "AND settled=FALSE"
            )
        ).fetchone()
        print(f"\nRemaining unsettled paper: {r[0]}")
        r = conn.execute(
            text(
                "SELECT COUNT(*) FROM trades WHERE trading_mode='paper' "
                "AND settled=TRUE AND pnl IS NULL"
            )
        ).fetchone()
        print(f"Still pending Gamma: {r[0]}")
        r = conn.execute(
            text(
                "SELECT COUNT(*) FROM trades WHERE trading_mode='paper' "
                "AND settled=TRUE AND pnl IS NOT NULL"
            )
        ).fetchone()
        print(f"Settled with PnL: {r[0]}")

asyncio.run(main())
