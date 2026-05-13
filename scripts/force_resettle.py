#!/usr/bin/env python3
"""
Manual settlement script for expired trades.

Run this after markets have been resolved on Polymarket to recalculate PnL.
"""

import asyncio
from backend.models.database import SessionLocal, Trade
from backend.core.settlement import (
    settle_pending_trades,
    update_bot_state_with_settlements,
)


async def force_resettle_expired():
    """Re-settle all expired trades by unmarking them and running settlement again."""
    db = SessionLocal()
    try:
        expired = (
            db.query(Trade)
            .filter(Trade.result == "expired", Trade.settled)
            .all()
        )

        print(f"Found {len(expired)} expired trades")
        print("=" * 80)

        if not expired:
            print("No expired trades to re-settle")
            return

        for trade in expired:
            print(f"Unmarking trade {trade.id}: {trade.market_ticker}")
            trade.settled = False
            trade.result = "pending"
            trade.pnl = None
            trade.settlement_time = None

        db.commit()
        print(f"\n✅ Unmarked {len(expired)} trades")
        print("\nRunning settlement job...")
        print("=" * 80)

        settled_trades = await settle_pending_trades(db)

        if settled_trades:
            print(f"\n✅ Settled {len(settled_trades)} trades")

            await update_bot_state_with_settlements(db, settled_trades)

            print("\nResults:")
            print("-" * 80)
            for t in settled_trades:
                status = "✅ RESOLVED" if t.result != "expired" else "⏳ STILL EXPIRED"
                pnl_str = f"${t.pnl:.2f}" if t.pnl else "$0.00"
                print(f"{status} | ID:{t.id} | {t.market_ticker[:50]}")
                print(f"         Result: {t.result} | PnL: {pnl_str}")
        else:
            print("\n⏳ No trades ready for settlement (markets still not resolved)")

    finally:
        db.close()


if __name__ == "__main__":
    print("MANUAL SETTLEMENT SCRIPT")
    print("=" * 80)
    print("This will re-attempt settlement for all expired trades.")
    print("Use this after markets have been resolved on Polymarket.")
    print()

    response = input("Continue? (y/n): ")
    if response.lower() == "y":
        asyncio.run(force_resettle_expired())
    else:
        print("Cancelled")
