#!/usr/bin/env python3
"""One-time backfill script to correct paper_initial_bankroll.

Problem: Auto-topups added funds to paper_bankroll but never updated
paper_initial_bankroll, causing paper_pnl to be overstated by the
total amount of auto-topups deposited over time.

This script:
1. Reads the current paper bankroll state from bot_state
2. Calculates total auto-topup amount from the formula:
   total_topups = current_bankroll - initial_bankroll - (total_returned - total_staked)
3. Updates paper_initial_bankroll = initial + total_topups
4. Updates paper_pnl = paper_bankroll - paper_initial_bankroll
5. Updates misc_data to include paper_topup_count for audit
6. Creates TransactionEvent deposit records for past auto-topups

Usage:
    # Dry run (default) - shows what would change without writing
    python scripts/backfill_paper_initial_bankroll.py

    # Apply changes
    python scripts/backfill_paper_initial_bankroll.py --apply

    # Apply to specific DB path
    python scripts/backfill_paper_initial_bankroll.py --apply --db /path/to/tradingbot.db
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError


def calculate_paper_topups(db_session):
    """Calculate total auto-topup amount from bankroll math.

    In paper mode, bankroll changes from:
    1. Opening a trade:  bankroll -= size
    2. Settling a trade: bankroll += (size + pnl) for wins, += size for expired/push, += 0 for losses
    3. Auto-topup:       bankroll += topup_amount

    Therefore:  current_bankroll = initial + total_topups + total_returned - total_staked
    And:        total_topups = current_bankroll - initial - total_returned + total_staked
    """
    row = db_session.execute(text(
        "SELECT paper_bankroll, paper_initial_bankroll, paper_pnl, misc_data "
        "FROM bot_state WHERE mode = 'paper'"
    )).fetchone()

    if not row:
        print("ERROR: No paper bot_state row found.")
        return None

    current_bankroll = float(row[0] or 0)
    initial_bankroll = float(row[1] or row[1]) if row[1] is not None else None
    current_pnl = float(row[2] or 0)
    misc_data_raw = row[3]

    try:
        misc_data = json.loads(misc_data_raw) if misc_data_raw else {}
    except (ValueError, TypeError):
        misc_data = {}

    # Get total staked (sum of all trade sizes for settled trades)
    total_staked = db_session.execute(text(
        "SELECT COALESCE(SUM(size), 0) FROM trades "
        "WHERE trading_mode = 'paper' AND result IN ('win', 'loss', 'expired', 'push', 'closed')"
    )).scalar() or 0
    total_staked = float(total_staked)

    # Get total returned: wins return size+pnl, expired/push return size, losses return 0
    total_returned = db_session.execute(text(
        "SELECT COALESCE(SUM(CASE "
        "  WHEN result = 'win' AND pnl IS NOT NULL THEN size + pnl "
        "  WHEN result IN ('expired', 'push', 'closed') THEN size "
        "  WHEN result = 'loss' THEN 0 "
        "  ELSE 0 "
        "END), 0) FROM trades "
        "WHERE trading_mode = 'paper' AND pnl IS NOT NULL"
    )).scalar() or 0
    total_returned = float(total_returned)

    settings_initial = db_session.execute(text(
        "SELECT value FROM settings WHERE key = 'INITIAL_BANKROLL'"
    )).scalar()
    if settings_initial:
        settings_initial = float(settings_initial)
    else:
        settings_initial = 1000.0

    effective_initial = initial_bankroll if initial_bankroll is not None else settings_initial

    total_topups = current_bankroll - effective_initial - total_returned + total_staked
    total_topups = round(total_topups, 2)
    estimated_topup_count = int(total_topups / 500) if total_topups > 0 else 0

    corrected_initial = round(effective_initial + total_topups, 2)
    corrected_pnl = round(current_bankroll - corrected_initial, 2)

    return {
        "current_bankroll": current_bankroll,
        "current_initial_bankroll": effective_initial,
        "current_pnl": current_pnl,
        "settings_initial_bankroll": settings_initial,
        "total_staked": total_staked,
        "total_returned": total_returned,
        "total_topups": total_topups,
        "estimated_topup_count": estimated_topup_count,
        "corrected_initial_bankroll": corrected_initial,
        "corrected_pnl": corrected_pnl,
        "pnl_overstatement": round(current_pnl - corrected_pnl, 2),
        "misc_data": misc_data,
    }


def apply_corrections(db_session, calc_result, topup_amount=500.0, max_topups=10):
    """Apply the calculated corrections to the database."""
    corrected_initial = calc_result["corrected_initial_bankroll"]
    corrected_pnl = calc_result["corrected_pnl"]
    topup_count = calc_result["estimated_topup_count"]

    max_retries = 5
    base_delay_ms = 500

    for attempt in range(max_retries):
        try:
            # 1. Update paper_initial_bankroll
            db_session.execute(text(
                "UPDATE bot_state SET paper_initial_bankroll = :initial "
                "WHERE mode = 'paper'"
            ), {"initial": corrected_initial})

            # 2. Update paper_pnl
            db_session.execute(text(
                "UPDATE bot_state SET paper_pnl = :pnl "
                "WHERE mode = 'paper'"
            ), {"pnl": corrected_pnl})

            # 3. Update misc_data with paper_topup_count
            misc_data = calc_result["misc_data"].copy()
            misc_data["paper_topup_count"] = topup_count
            db_session.execute(text(
                "UPDATE bot_state SET misc_data = :misc "
                "WHERE mode = 'paper'"
            ), {"misc": json.dumps(misc_data)})

            # 4. Create TransactionEvent records for past auto-topups
            # We can't know the exact timestamps of past auto-topups, so we create
            # summary records with approximate info
            for i in range(1, topup_count + 1):
                db_session.execute(text(
                    "INSERT INTO transaction_events "
                    "(timestamp, type, amount, balance_after, context, note) "
                    "VALUES ("
                    "  (SELECT MIN(timestamp) FROM trades WHERE trading_mode = 'paper'), "
                    "  'deposit', :amount, NULL, :context, :note"
                    ")"
                ), {
                    "amount": topup_amount,
                    "context": json.dumps({
                        "source": "backfill",
                        "topup_number": i,
                        "max_topups": max_topups,
                        "trigger": "retroactive correction for auto-topup that did not update paper_initial_bankroll",
                    }),
                    "note": f"Backfilled paper auto-topup #{i}: +${topup_amount:,.2f}",
                })

            # 5. If there's a remaining fractional topup (< 500), record it too
            remainder = calc_result["total_topups"] - (topup_count * topup_amount)
            if remainder > 0.01:
                db_session.execute(text(
                    "INSERT INTO transaction_events "
                    "(timestamp, type, amount, balance_after, context, note) "
                    "VALUES ("
                    "  (SELECT MIN(timestamp) FROM trades WHERE trading_mode = 'paper'), "
                    "  'deposit', :amount, NULL, :context, :note"
                    ")"
                ), {
                    "amount": round(remainder, 2),
                    "context": json.dumps({
                        "source": "backfill",
                        "topup_number": topup_count + 1,
                        "max_topups": max_topups,
                        "trigger": "fractional remainder from correction",
                    }),
                    "note": f"Backfilled paper auto-topup #{topup_count + 1} (partial): +${remainder:,.2f}",
                })

            db_session.commit()
            return
        except OperationalError as e:
            db_session.rollback()
            if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                delay_ms = base_delay_ms * (2 ** attempt)
                print(f"  Database locked, retrying in {delay_ms}ms (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay_ms / 1000)
                continue
            raise


def main():
    parser = argparse.ArgumentParser(
        description="Backfill paper_initial_bankroll with correct value from auto-topup history"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply changes (default is dry-run)"
    )
    parser.add_argument(
        "--db", default=None,
        help="Path to SQLite database file (auto-detects if not specified)"
    )
    parser.add_argument(
        "--topup-amount", type=float, default=500.0,
        help="Paper topup amount per deposit (default: 500)"
    )
    parser.add_argument(
        "--max-topups", type=int, default=10,
        help="Maximum topups allowed (default: 10)"
    )
    args = parser.parse_args()

    # Determine DB path
    if args.db:
        db_path = args.db
    else:
        # Try common locations
        for candidate in [
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tradingbot.db"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trading_bot.db"),
        ]:
            if os.path.exists(candidate):
                db_path = candidate
                break
        else:
            # Check DATABASE_URL env var
            db_url = os.environ.get("DATABASE_URL", "")
            if db_url.startswith("sqlite:///"):
                db_path = db_url[len("sqlite:///"):]
            else:
                print("ERROR: Could not auto-detect database path. Use --db flag.")
                sys.exit(1)

    if not os.path.exists(db_path):
        print(f"ERROR: Database file not found: {db_path}")
        sys.exit(1)

    print(f"Database: {db_path}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN (no changes will be made)'}")
    print("=" * 60)

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 30})
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        result = calculate_paper_topups(db)
        if result is None:
            sys.exit(1)

        # Print findings
        print("CURRENT STATE:")
        print(f"  paper_bankroll:           ${result['current_bankroll']:>12,.2f}")
        print(f"  paper_initial_bankroll:   ${result['current_initial_bankroll']:>12,.2f}")
        print(f"  paper_pnl:                ${result['current_pnl']:>12,.2f}")
        print()
        print("CALCULATION:")
        print(f"  settings.INITIAL_BANKROLL: ${result['settings_initial_bankroll']:>11,.2f}")
        print(f"  total staked (trade sizes): ${result['total_staked']:>10,.2f}")
        print(f"  total returned:           ${result['total_returned']:>12,.2f}")
        print(f"  total auto-topups:         ${result['total_topups']:>10,.2f}  (~{result['estimated_topup_count']} x ${args.topup_amount:,.0f})")
        print()
        print("CORRECTED STATE:")
        print(f"  paper_initial_bankroll:   ${result['corrected_initial_bankroll']:>12,.2f}")
        print(f"  paper_pnl:                ${result['corrected_pnl']:>12,.2f}")
        print(f"  PnL overstatement:        ${result['pnl_overstatement']:>12,.2f}  (currently counting deposits as profit)")
        print()

        if not args.apply:
            print("DRY RUN — no changes made. Use --apply to write corrections.")
        else:
            apply_corrections(db, result, args.topup_amount, args.max_topups)
            print("✓ Corrections applied successfully!")
            print()

            # Verify
            verify = calculate_paper_topups(db)
            print("VERIFICATION (post-apply):")
            print(f"  paper_initial_bankroll:   ${verify['current_initial_bankroll']:>12,.2f}")
            print(f"  paper_pnl:                ${verify['current_pnl']:>12,.2f}")
            print(f"  topup_count in misc_data: {verify['misc_data'].get('paper_topup_count', 'NOT SET')}")

    finally:
        db.close()


if __name__ == "__main__":
    main()