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
            from backend.models.database import BotState

            # 1. Fetch wallet equity (already async)
            equity = await fetch_pm_total_equity()

            # 2. Update wallet_pnl BEFORE reconciliation, otherwise
            #    reconcile_bot_state overwrites bankroll with equity and
            #    wallet_pnl becomes equity - equity = 0.
            #    wallet_pnl = actual wallet equity - initial bankroll (real P&L)
            with get_db_session() as db:
                bot_state = db.query(BotState).filter(BotState.mode == mode).first()
                if bot_state and equity is not None:
                    bot_state.last_wallet_sync_at = datetime.now(timezone.utc)
                    initial = (
                        bot_state.live_initial_bankroll or bot_state.bankroll or 100.0
                    )
                    bot_state.wallet_pnl = round(equity - float(initial), 2)
                    db.commit()

            # 3. Reconcile bot state (overwrites bankroll with actual equity)
            with get_db_session() as db:
                result = await reconcile_bot_state(db, apply=True)

            # 3b. Compare wallet_pnl vs total_pnl for P&L drift detection
            with get_db_session() as db:
                bot_state = db.query(BotState).filter(BotState.mode == mode).first()
                if bot_state:
                    wpnl = float(bot_state.wallet_pnl or 0.0)
                    tpnl = float(bot_state.total_pnl or 0.0)
                    denominator = max(abs(wpnl), abs(tpnl), 1.0)
                    pnl_drift_pct = abs(wpnl - tpnl) / denominator * 100
                    if pnl_drift_pct > 5.0:
                        logger.warning(
                            "[WalletReconciler] PnL drift %.1f%%: wallet_pnl=$%.2f vs total_pnl=$%.2f",
                            pnl_drift_pct,
                            wpnl,
                            tpnl,
                        )

            # 4. Compare wallet_pnl vs stale total_pnl, alert if >5% drift
            if result and hasattr(result, "bankroll_drift_pct"):
                if abs(result.bankroll_drift_pct) > 5.0:
                    logger.warning(
                        "[WalletReconciler] Bankroll drift %.1f%% exceeds 5%%",
                        result.bankroll_drift_pct,
                    )

            logger.info("[WalletReconciler] Reconciliation complete for %s", mode)
        except Exception as e:
            logger.error(
                "[WalletReconciler] Reconciliation failed: %s", e, exc_info=True
            )


_wallet_reconciler = WalletReconciler()


async def wallet_reconciler_job():
    """Scheduler job entry point."""
    await _wallet_reconciler.reconcile()
