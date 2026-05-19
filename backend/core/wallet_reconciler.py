import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class WalletReconciler:
    """Periodic wallet balance sync using existing bankroll_reconciliation infra.

    Runs as async scheduler job. Uses thread pool for DB calls to avoid
    freezing the event loop.
    """

    async def reconcile(self, mode: str = "live"):
        try:
            from backend.core.wallet.bankroll_reconciliation import (
                fetch_pm_total_equity,
                reconcile_bot_state,
            )
            from backend.db.utils import get_db_session

            # 1. Fetch wallet equity (already async)
            equity = await fetch_pm_total_equity()

            # 2. Reconcile bot state (already async, no thread pool needed)
            with get_db_session() as db:
                result = await reconcile_bot_state(db, apply=True)

            # 3. Compare wallet_pnl vs stale total_pnl, alert if >5% drift
            if result and hasattr(result, "bankroll_drift_pct"):
                if abs(result.bankroll_drift_pct) > 5.0:
                    logger.warning(
                        "[WalletReconciler] Bankroll drift %.1f%% exceeds 5%%",
                        result.bankroll_drift_pct,
                    )

            # 4. Update last_wallet_sync_at
            with get_db_session() as db:
                from backend.models.database import BotState

                bot_state = (
                    db.query(BotState)
                    .filter(BotState.trading_mode == mode)
                    .first()
                )
                if bot_state:
                    bot_state.last_wallet_sync_at = datetime.now(timezone.utc)
                    if equity is not None:
                        bot_state.wallet_pnl = equity - (
                            bot_state.bankroll or 0
                        )
                    db.commit()

            logger.info(
                "[WalletReconciler] Reconciliation complete for %s", mode
            )
        except Exception as e:
            logger.error(
                "[WalletReconciler] Reconciliation failed: %s", e, exc_info=True
            )


_wallet_reconciler = WalletReconciler()


async def wallet_reconciler_job():
    """Scheduler job entry point."""
    await _wallet_reconciler.reconcile()
