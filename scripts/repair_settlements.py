"""Repair incorrect settlement values in the database.

Fixes:
1. settlement_value=0.5 (wrong for binary markets) → fetch correct value from Polymarket
2. settlement_value=None on settled trades → fetch correct value
3. Recalculate PnL and result fields

Usage:
    python scripts/repair_settlements.py [--dry-run]
"""

import asyncio
import json
import sys
from datetime import datetime, timezone

from backend.models.database import SessionLocal, Trade
from backend.core.settlement.settlement_helpers import calculate_pnl
from backend.data.shared_client import get_shared_client
from backend.config import settings
from loguru import logger


async def _resolve_from_gamma(token_id: str, market_ticker: str) -> float | None:
    """Fetch settlement value from Gamma API by token_id."""
    if not token_id:
        return None
    try:
        client = get_shared_client()
        # Try by token_id first (more reliable)
        resp = await client.get(
            f"{settings.GAMMA_API_URL}/markets",
            params={"clob_token_ids": token_id},
        )
        if resp.status_code != 200:
            # Fallback: try by slug
            resp = await client.get(
                f"{settings.GAMMA_API_URL}/markets",
                params={"slug": market_ticker},
            )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, list) or not data:
            return None

        market = data[0]
        is_closed = market.get("closed", False)
        uma_status = market.get("umaResolutionStatus", "")
        resolved = is_closed or uma_status == "resolved"

        if not resolved:
            return None

        outcome_prices = market.get("outcomePrices", [])
        if isinstance(outcome_prices, str):
            outcome_prices = json.loads(outcome_prices)
        if not outcome_prices or len(outcome_prices) < 2:
            return None

        p0 = float(outcome_prices[0])
        p1 = float(outcome_prices[1])

        threshold = 0.005
        if p0 <= threshold and p1 >= (1.0 - threshold):
            return 0.0
        elif p1 <= threshold and p0 >= (1.0 - threshold):
            return 1.0
        else:
            return None
    except Exception as e:
        logger.debug(f"Gamma resolve failed for {market_ticker}: {e}")
        return None


async def repair_settlements(dry_run: bool = True):
    db = SessionLocal()

    broken_05 = db.query(Trade).filter(
        Trade.settlement_value == 0.5,
        Trade.settled == True,
    ).all()

    broken_none = db.query(Trade).filter(
        Trade.settlement_value == None,
        Trade.settled == True,
        Trade.result.in_(["pending", "stale_cleanup", "unknown_cancelled"]),
    ).all()

    all_broken = broken_05 + broken_none
    print(f"Found {len(broken_05)} trades with settlement_value=0.5")
    print(f"Found {len(broken_none)} trades with settlement_value=None (pending)")
    print(f"Total to repair: {len(all_broken)}")

    if not all_broken:
        print("Nothing to repair.")
        db.close()
        return

    fixed = 0
    failed = 0
    skipped = 0
    unresolved = 0

    for trade in all_broken:
        ticker = trade.market_ticker

        try:
            settlement_value = await _resolve_from_gamma(trade.token_id, ticker)

            if settlement_value is None:
                trade.settlement_value = None
                trade.settled = False
                trade.result = "pending"
                trade.settlement_source = "repair_unresolved"
                unresolved += 1
                continue

            if settlement_value not in (0.0, 1.0):
                skipped += 1
                continue

            direction = (trade.direction or "yes").lower()
            if direction in ("up", "buy"):
                direction = "yes"
            elif direction in ("down", "sell"):
                direction = "no"

            dir_yes = direction == "yes"
            is_win = (dir_yes and settlement_value == 1.0) or (
                not dir_yes and settlement_value == 0.0
            )

            old_pnl = trade.pnl or 0
            new_pnl = calculate_pnl(trade, settlement_value)

            trade.settlement_value = settlement_value
            trade.result = "win" if is_win else "loss"
            trade.pnl = new_pnl
            trade.settlement_source = "repair_script"
            trade.settlement_time = trade.settlement_time or datetime.now(timezone.utc)

            delta = new_pnl - old_pnl
            print(
                f"  FIXED {ticker[:50]} | sv={settlement_value} | "
                f"result={trade.result} | pnl=${old_pnl:.2f} -> ${new_pnl:.2f} | "
                f"delta=${delta:+.2f}"
            )
            fixed += 1

        except Exception as e:
            print(f"  ERROR {ticker[:50]} — {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"RESULTS: {fixed} fixed, {unresolved} unresolved, {failed} failed, {skipped} skipped")

    if dry_run:
        print("\nDRY RUN — rolling back all changes")
        db.rollback()
    else:
        print("\nCOMMITTING changes")
        db.commit()

    db.close()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv or "--dry" in sys.argv
    asyncio.run(repair_settlements(dry_run=dry_run))
