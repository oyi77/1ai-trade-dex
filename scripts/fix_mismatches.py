#!/usr/bin/env python3
"""Fix remaining DB mismatches and verify 1:1 sync."""
import asyncio, os, sys, httpx
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text

engine = create_engine(os.getenv("DATABASE_URL"))
WALLET = os.getenv("POLYMARKET_WALLET_ADDRESS", "").lower()

async def main():
    async with httpx.AsyncClient(timeout=15) as h:
        r = await h.get(f"https://data-api.polymarket.com/positions?user={WALLET}")
        positions = r.json()
    pos_map = {p["asset"]: p for p in positions}
    pm_assets = set(pos_map.keys())
    print(f"Polymarket positions: {len(positions)}")

    with engine.connect() as conn:
        # Get ALL live trades grouped by status
        rows = conn.execute(text(
            "SELECT id, token_id, market_ticker, direction, size, entry_price, status "
            "FROM trades WHERE trading_mode='live' AND status IN ('filled','closed') "
            "ORDER BY id"
        )).fetchall()

        db_filled = [r for r in rows if r[6] == "filled"]
        db_closed = [r for r in rows if r[6] == "closed"]
        print(f"DB filled: {len(db_filled)}, DB closed: {len(db_closed)}")

        db_filled_tokens = set(str(r[1]) for r in db_filled if r[1])

        # Mismatches
        in_db_not_pm = db_filled_tokens - pm_assets
        in_pm_not_db = pm_assets - db_filled_tokens

        print(f"\nIn DB but NOT on PM: {len(in_db_not_pm)}")
        for tid in in_db_not_pm:
            # These were settled - mark closed
            result = conn.execute(text(
                "UPDATE trades SET status='closed', settlement_time=now() "
                "WHERE token_id=:t AND trading_mode='live' AND status='filled'"
            ), {"t": tid})
            print(f"  Fixed: {tid} -> marked closed")

        print(f"\nOn PM but NOT in DB: {len(in_pm_not_db)}")
        for tid in in_pm_not_db:
            p = pos_map[tid]
            # Check if these exist in DB with different status
            existing = conn.execute(text(
                "SELECT id, status FROM trades WHERE token_id=:t AND trading_mode='live'"
            ), {"t": tid}).fetchall()
            if existing:
                for ex in existing:
                    conn.execute(text(
                        "UPDATE trades SET status='filled' WHERE id=:id"
                    ), {"id": ex[0]})
                    print(f"  Fixed: id={ex[0]} -> status=filled (was {ex[1]})")
            else:
                print(f"  MISSING: {tid} {p['title'][:50]} - no DB entry at all")
        conn.commit()

        # Final verification
        print("\n=== FINAL STATE ===")
        rows = conn.execute(text(
            "SELECT status, COUNT(*), ROUND(COALESCE(SUM(size),0)::numeric,2), "
            "ROUND(COALESCE(SUM(pnl),0)::numeric,4) "
            "FROM trades WHERE trading_mode='live' "
            "GROUP BY status ORDER BY status"
        )).fetchall()
        for r in rows:
            print(f"  {str(r[0]):<16} cnt={r[1]:>5} sz={r[2]:>10} pnl={r[3]:>10}")

        # Check 1:1 match
        filled_count = conn.execute(text(
            "SELECT COUNT(*) FROM trades WHERE trading_mode='live' AND status='filled'"
        )).fetchone()[0]
        print(f"\n  Polymarket: {len(positions)} positions")
        print(f"  DB filled:  {filled_count} trades")
        print(f"  MATCH: {'YES' if filled_count == len(positions) else 'NO - MISMATCH!'}")

asyncio.run(main())
