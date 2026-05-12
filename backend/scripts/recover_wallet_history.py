#!/usr/bin/env python3
"""Recover wallet history from blockchain.

Standalone script for manual wallet history recovery. Fetches ALL historical trades
from Polymarket Data API and imports them into the database with source='imported'.

Idempotent: running twice produces the same result (no duplicates due to clob_order_id check).

Usage:
    python backend/scripts/recover_wallet_history.py --wallet 0xabc... [--mode live|testnet]
    python backend/scripts/recover_wallet_history.py --help

Examples:
    # Recover mainnet wallet
    python backend/scripts/recover_wallet_history.py --wallet 0x1234567890abcdef

    # Recover testnet wallet
    python backend/scripts/recover_wallet_history.py --wallet 0x1234567890abcdef --mode testnet
"""

import argparse
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.wallet_reconciliation import WalletReconciler
from backend.data.polymarket_clob import clob_from_settings
from backend.models.database import SessionLocal

from backend.core.log import configure_logging
configure_logging()
from loguru import logger  # noqa: E402
async def main(wallet: str, mode: str):
    """
    Recover wallet history from blockchain.

    Args:
        wallet: Wallet address (0x-prefixed hex string)
        mode: Trading mode ("live" or "testnet")

    Returns:
        Exit code (0 on success, 1 on failure)
    """
    if not wallet:
        logger.error("Wallet address is required. Use --wallet 0xabc...")
        return 1

    if not wallet.startswith("0x"):
        logger.error(f"Invalid wallet address: {wallet}. Must start with 0x")
        return 1

    logger.info(f"Starting wallet history recovery for {wallet} ({mode} mode)")

    try:
        # Create CLOB client
        logger.info("Initializing CLOB client...")
        clob = clob_from_settings(mode=mode)

        # Create DB session
        db = SessionLocal()

        try:
            # Initialize reconciler
            logger.info("Initializing wallet reconciler...")
            reconciler = WalletReconciler(clob, db, mode)

            # Run full reconciliation
            logger.info("Starting full reconciliation cycle...")
            result = await reconciler.full_reconciliation()

            # Report results
            logger.info("=" * 60)
            logger.info("RECOVERY COMPLETE")
            logger.info("=" * 60)
            logger.info(f"Imported trades:  {result.imported_count}")
            logger.info(f"Updated trades:  {result.updated_count}")
            logger.info(f"Closed trades:   {result.closed_count}")

            if result.errors:
                logger.warning(f"Errors encountered: {len(result.errors)}")
                for error in result.errors:
                    logger.warning(f"  - {error}")

            logger.info(f"Last sync: {result.last_sync_at}")
            logger.info("=" * 60)

            return 0

        finally:
            db.close()

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Recovery failed: {e}", exc_info=True)
        return 1


def main_sync():
    """Synchronous entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Recover wallet history from blockchain",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--wallet",
        required=True,
        help="Wallet address (0x-prefixed hex string)",
    )

    parser.add_argument(
        "--mode",
        default="live",
        choices=["live", "testnet"],
        help="Trading mode (default: live)",
    )

    args = parser.parse_args()

    # Run async main
    exit_code = asyncio.run(main(args.wallet, args.mode))
    sys.exit(exit_code)


if __name__ == "__main__":
    main_sync()
