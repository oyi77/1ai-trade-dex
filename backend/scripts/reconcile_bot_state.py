"""Safely reconcile BotState bankroll caches from source-of-truth data.

This script preserves the Trade ledger. It only updates derived BotState cache
fields used by risk sizing and dashboards.

Usage:
  python -m backend.scripts.reconcile_bot_state          # dry run
  python -m backend.scripts.reconcile_bot_state --apply  # mutate BotState only
"""

from __future__ import annotations

import argparse
import asyncio
import json

from backend.core.wallet.bankroll_reconciliation import reconcile_bot_state
from backend.models.database import SessionLocal


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Apply BotState cache changes"
    )
    parser.add_argument(
        "--mode",
        choices=("paper", "testnet", "live", "all"),
        default="all",
        help="Mode to reconcile",
    )
    args = parser.parse_args()

    modes = ("paper", "testnet", "live") if args.mode == "all" else (args.mode,)
    db = SessionLocal()
    try:
        reports = await reconcile_bot_state(
            db,
            modes=modes,
            apply=args.apply,
            commit=args.apply,
            source="manual_reconcile_script",
        )
        print(
            json.dumps(
                [report.to_dict() for report in reports], indent=2, sort_keys=True
            )
        )
        if not args.apply:
            print(
                "DRY RUN — no BotState changes committed. Re-run with --apply to update caches."
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
