"""Wallet synchronization jobs."""

import asyncio

from loguru import logger

from backend.models.database import BotState


async def sync_testnet_wallet():
    """Testnet wallet sync — not yet implemented."""
    logger.warning("[sync_testnet_wallet] Not implemented — skipping")


async def sync_live_wallet():
    """Reconcile live wallet every 30 seconds."""
    from backend.db.utils import get_db_session

    try:
        from backend.core.wallet.bankroll_reconciliation import reconcile_bot_state
        from backend.core.wallet.wallet_reconciliation import WalletReconciler
        from backend.data.polymarket_clob import clob_from_settings

        logger.info("[sync_live_wallet] Starting reconciliation...")
        clob = clob_from_settings(mode="live")
        async with clob:
            await clob.create_or_derive_api_key()
            with get_db_session() as db:
                reconciler = WalletReconciler(clob, db, "live")
                result = await reconciler.full_reconciliation()

        logger.info(
            "[sync_live_wallet] Reconciliation done, updating BotState timestamp..."
        )

        def _update_bot_state_sync():
            from backend.db.utils import get_db_session

            with get_db_session() as db:
                state = db.query(BotState).filter_by(mode="live").first()
                if state and result.last_sync_at:
                    state.last_sync_at = result.last_sync_at
                    try:
                        db.flush()
                    except Exception as flush_err:
                        logger.warning(f"[sync_live_wallet] flush failed: {flush_err}")
                        db.rollback()

        await asyncio.to_thread(_update_bot_state_sync)

        logger.info("[sync_live_wallet] Calling reconcile_bot_state...")
        try:
            with get_db_session() as db:
                await reconcile_bot_state(
                    db,
                    modes=("live",),
                    apply=True,
                    commit=True,
                    source="live_wallet_sync_reconcile",
                )
            logger.info("[sync_live_wallet] reconcile_bot_state done")
        except Exception as recon_err:
            logger.exception(
                f"[sync_live_wallet] reconcile_bot_state failed: {recon_err}"
            )

        logger.info(
            f"Live wallet sync: imported={result.imported_count}, "
            f"updated={result.updated_count}, closed={result.closed_count}"
        )
    except Exception as e:
        logger.exception(f"Live wallet sync failed: {e}")
