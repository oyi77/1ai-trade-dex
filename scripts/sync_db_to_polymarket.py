#!/usr/bin/env python3
"""
Sync local DB trades 1:1 with Polymarket reality.
- Match DB trades to Polymarket positions by token_id
- Settle resolved trades
- Update bot_state bankroll to match real portfolio
"""
import asyncio
import os
import httpx
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
WALLET = os.getenv("POLYMARKET_WALLET_ADDRESS", "").lower()
REPORTED_CASH = 6.88
LIVE_INITIAL = 13.12

async def run():
    # 1. Fetch Polymarket positions
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"https://data-api.polymarket.com/positions?user={WALLET}")
        r.raise_for_status()
        positions = r.json()

    pos_by_token = {}
    positions_value = 0.0
    for p in positions:
        asset = p.get("asset", "")
        pos_by_token[asset] = {
            "size": float(p.get("size", 0)),
            "avg_price": float(p.get("avgPrice", 0)),
            "cur_price": float(p.get("curPrice", 0)),
            "title": p.get("title", ""),
            "outcome": p.get("outcome", ""),
        }
        positions_value += float(p.get("currentValue", 0))

    portfolio = REPORTED_CASH + positions_value
    print(f"Polymarket: {len(positions)} positions = ${positions_value:.2f}")
    print(f"Cash: ${REPORTED_CASH:.2f}")
    print(f"Portfolio: ${portfolio:.2f}")

    # 2. Current DB state
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT status, COUNT(*) as cnt, "
            "ROUND(COALESCE(SUM(size),0)::numeric,2) as tsize, "
            "ROUND(COALESCE(SUM(pnl),0)::numeric,4) as tpnl "
            "FROM trades WHERE trading_mode='live' "
            "GROUP BY status ORDER BY status"
        )).fetchall()
        print("\nBefore sync:")
        for row in r:
            print(f"  {str(row[0]):<16} cnt={row[1]:>5} sz={row[2]:>10} pnl={row[3]:>10}")

    # 3. Update trades
    with Session(engine) as session:
        db_trades = session.execute(text(
            "SELECT id, token_id, direction, size, entry_price, status FROM trades "
            "WHERE trading_mode='live'"
        )).fetchall()

        updated_matched = 0
        updated_closed = 0
        for t in db_trades:
            tid = str(t[1]) if t[1] else ""
            direction = t[2]
            size = float(t[3]) if t[3] else 0
            entry = float(t[4]) if t[4] else 0
            current_status = t[5]

            if tid and tid in pos_by_token:
                # Has open position on Polymarket
                pos = pos_by_token[tid]
                cur = pos["cur_price"]
                if direction in ("yes", "up"):
                    pnl = round(size * (cur - entry), 4)
                else:
                    pnl = round(size * (entry - cur), 4)
                session.execute(text(
                    "UPDATE trades SET status='filled', pnl=:pnl, settlement_time=now() WHERE id=:id"
                ), {"pnl": pnl, "id": t[0]})
                updated_matched += 1
            elif current_status not in ("SETTLED",):
                # No position → market resolved
                session.execute(text(
                    "UPDATE trades SET status='closed', settlement_time=now() "
                    "WHERE id=:id AND (status IS NULL OR status IN ('closed_errored','None'))"
                ), {"id": t[0]})
                updated_closed += 1

        # Fix all closed_errored
        session.execute(text(
            "UPDATE trades SET status='closed' WHERE trading_mode='live' AND status='closed_errored'"
        ))

        # 4. Recalculate total settled PnL
        settled = session.execute(text(
            "SELECT COALESCE(SUM(pnl), 0) FROM trades "
            "WHERE trading_mode='live' AND status IN ('SETTLED','closed','filled') AND pnl IS NOT NULL"
        )).fetchone()[0]

        wins = session.execute(text(
            "SELECT COUNT(*) FROM trades "
            "WHERE trading_mode='live' AND status IN ('SETTLED','closed','filled') AND pnl > 0"
        )).fetchone()[0]

        total_cnt = session.execute(text(
            "SELECT COUNT(*) FROM trades WHERE trading_mode='live'"
        )).fetchone()[0]

        # Update bot_state
        session.execute(text(
            "UPDATE bot_state SET "
            "bankroll=:br, total_pnl=:pnl, winning_trades=:wins, total_trades=:tc, "
            "track_bankroll_realtime=:br, wallet_pnl=:wp, last_sync_at=now() "
            "WHERE mode='live'"
        ), {
            "br": portfolio,
            "pnl": settled,
            "wins": wins,
            "tc": total_cnt,
            "wp": portfolio - LIVE_INITIAL,
        })

        session.commit()

    # 5. Verify
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT status, COUNT(*) as cnt, "
            "ROUND(COALESCE(SUM(size),0)::numeric,2) as tsize, "
            "ROUND(COALESCE(SUM(pnl),0)::numeric,4) as tpnl "
            "FROM trades WHERE trading_mode='live' "
            "GROUP BY status ORDER BY status"
        )).fetchall()
        print("\nAfter sync:")
        for row in r:
            print(f"  {str(row[0]):<16} cnt={row[1]:>5} sz={row[2]:>10} pnl={row[3]:>10}")

        bs = conn.execute(text(
            "SELECT bankroll, total_pnl, wallet_pnl, total_trades, winning_trades FROM bot_state WHERE mode='live'"
        )).fetchone()
        print(f"\nbot_state: bankroll=${bs[0]:.2f} total_pnl=${bs[1]:.2f} wallet_pnl=${bs[2]:.2f}")
        print(f"          trades={bs[3]} wins={bs[4]}")

    print(f"\n=== SYNC DONE ===")
    print(f"Matched to positions: {updated_matched}")
    print(f"Marked closed: {updated_closed}")
    print(f"Portfolio: ${portfolio:.2f} = ${REPORTED_CASH:.2f} cash + ${positions_value:.2f} positions")

if __name__ == "__main__":
    asyncio.run(run())
