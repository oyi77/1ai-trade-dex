#!/usr/bin/env python3
"""Backfill trade role column for existing trades.

Usage:
    python -m backend.core.trade_forensics_backfill --dry-run   # preview changes
    python -m backend.core.trade_forensics_backfill             # apply changes
"""

import argparse
import sys
from backend.models.database import SessionLocal, Trade
from backend.core.trade_forensics import classify_trade_role


def backfill_trade_roles(dry_run: bool = True) -> int:
    """Backfill role column for trades with NULL/empty role.

    Args:
        dry_run: If True, only count and display. If False, write to DB.

    Returns:
        Number of trades that would be/were updated.
    """
    db = SessionLocal()
    updated = 0
    try:
        trades = (
            db.query(Trade)
            .filter((Trade.role == None) | (Trade.role == "unknown"))  # noqa: E711
            .all()
        )

        if not trades:
            print("No trades require role backfill.")
            return 0

        for trade in trades:
            role = classify_trade_role(
                order_type=None,
                fill_price=trade.fill_price or trade.entry_price,
                mid_price=None,
                maker_rebate=None,
                taker_fee=None,
            )
            if dry_run:
                print(f"  [DRY RUN] Trade #{trade.id}: would set role={role}")
            else:
                trade.role = role
                print(f"  Trade #{trade.id}: set role={role}")
            updated += 1

        if not dry_run:
            db.commit()
            print(f"\nCommitted {updated} role updates.")
        else:
            print(f"\n[Dry run] Would update {updated} trades.")

    finally:
        db.close()

    return updated


def main():
    parser = argparse.ArgumentParser(description="Backfill trade role column")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without applying"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Apply changes to the database"
    )
    args = parser.parse_args()

    # Default to dry-run unless --apply is explicitly passed.
    dry_run = True
    if args.apply and not args.dry_run:
        dry_run = False

    print(f"Starting trade role backfill (mode={'dry-run' if dry_run else 'apply'})...")
    count = backfill_trade_roles(dry_run=dry_run)
    print(f"Done. {'Would update' if dry_run else 'Updated'} {count} trades.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
