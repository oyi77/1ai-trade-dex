"""Backfill PnL for live trades that were closed without resolution.

These are trades where wallet_reconciliation or other close paths marked the
trade as settled (or simply NULL pnl) without ever computing a real win/loss.

Strategy:
  1. Find all settled live trades with pnl IS NULL.
  2. Re-fetch resolution via fetch_resolution_for_trade (platform-aware).
  3. If resolved -> compute pnl via calculate_pnl, set result, mark
     settlement_source='data_api' if not already set.
  4. If not resolvable (closed too long ago, off-chain, etc) -> tag
     settlement_source='unresolvable' so we never re-try and our reports
     stop counting them as "stuck".

Idempotent: only touches rows with pnl IS NULL.
Default dry-run; pass --apply to write.
Does NOT mutate BotState (live mode bankroll stays user-owned).

Usage:
  python -m backend.scripts.backfill_live_pnl                  # dry-run
  python -m backend.scripts.backfill_live_pnl --apply          # commit
  python -m backend.scripts.backfill_live_pnl --limit 10       # cap rows
  python -m backend.scripts.backfill_live_pnl --platform kalshi
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.models.database import get_db, Trade
from backend.core.settlement_helpers import (
    calculate_pnl,
    fetch_resolution_for_trade,
)


def _classify_platform(trade: Trade) -> str:
    """Read trade.platform directly; fall back to ticker heuristic for legacy rows."""
    if getattr(trade, "platform", None):
        return str(trade.platform).lower()
    ticker = (trade.market_ticker or "").lower()
    if ticker.startswith("kx"):
        return "kalshi"
    return "polymarket"


async def backfill(apply_changes: bool, limit: int | None, platform_filter: str | None):
    db = next(get_db())

    q = db.query(Trade).filter(
        Trade.trading_mode == "live",
        Trade.pnl.is_(None),
    )
    if platform_filter:
        q = q.filter(Trade.platform == platform_filter.lower())
    if limit:
        q = q.limit(limit)

    candidates = q.all()

    print(
        f"Found {len(candidates)} live trades with pnl IS NULL"
        + (f" (filter: platform={platform_filter})" if platform_filter else "")
    )

    if not candidates:
        print("Nothing to backfill.")
        return

    resolved_count = 0
    unresolvable_count = 0
    api_errors = 0
    wins = losses = pushes = 0
    total_pnl = 0.0

    for trade in candidates:
        platform = _classify_platform(trade)
        try:
            is_resolved, settlement_value = await fetch_resolution_for_trade(trade)
        except Exception as exc:  # noqa: BLE001
            print(
                f"  Trade {trade.id} [{platform}/{trade.market_ticker}]: API error — {exc}"
            )
            api_errors += 1
            continue

        if not is_resolved or settlement_value is None:
            print(
                f"  Trade {trade.id} [{platform}/{trade.market_ticker}]: unresolvable"
            )
            unresolvable_count += 1
            if apply_changes:
                trade.settlement_source = "unresolvable"
            continue

        pnl = calculate_pnl(trade, settlement_value)
        if pnl > 0:
            new_result = "win"
            wins += 1
        elif pnl < 0:
            new_result = "loss"
            losses += 1
        else:
            new_result = "push"
            pushes += 1

        total_pnl += pnl
        print(
            f"  Trade {trade.id} [{platform}/{trade.market_ticker}]: "
            f"{trade.direction} @ {trade.entry_price} size=${trade.size:.2f} "
            f"-> settle={settlement_value} pnl=${pnl:+.2f} ({new_result})"
        )

        if apply_changes:
            now = datetime.now(timezone.utc)
            trade.settlement_value = settlement_value
            trade.pnl = pnl
            trade.result = new_result
            trade.settled = True
            if not trade.settlement_time:
                trade.settlement_time = now
            if not trade.settlement_source or trade.settlement_source == "unresolvable":
                trade.settlement_source = "data_api"

        resolved_count += 1

    print("\nBackfill summary:")
    print(f"  Resolved:      {resolved_count} ({wins}W / {losses}L / {pushes}P)")
    print(f"  Unresolvable:  {unresolvable_count}")
    print(f"  API errors:    {api_errors}")
    print(f"  Total PnL:     ${total_pnl:+.2f}")

    if apply_changes:
        db.commit()
        print("Committed. (BotState NOT mutated — live mode.)")
    else:
        print("DRY RUN — no changes written. Re-run with --apply to commit.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill PnL for live trades closed without resolution."
    )
    parser.add_argument(
        "--apply", action="store_true", help="Commit changes (default: dry-run)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Cap number of trades processed"
    )
    parser.add_argument(
        "--platform",
        type=str,
        default=None,
        choices=["polymarket", "kalshi"],
        help="Restrict to a single platform",
    )
    args = parser.parse_args()

    asyncio.run(
        backfill(
            apply_changes=args.apply, limit=args.limit, platform_filter=args.platform
        )
    )
