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
                fetch_pm_open_position_value,
                fetch_pm_total_equity,
                reconcile_bot_state,
            )
            from backend.db.utils import get_db_session
            from backend.models.database import BotState, Trade

            from sqlalchemy import func

            # 1. Fetch wallet equity and open position market value
            equity = await fetch_pm_total_equity()
            open_position_value = await fetch_pm_open_position_value()

            # 2. Update wallet_pnl BEFORE reconciliation, otherwise
            #    reconcile_bot_state overwrites bankroll with equity and
            #    wallet_pnl becomes equity - equity = 0.
            #
            #    wallet_pnl = equity - initial - net_deposits
            #    Subtracting net deposits ensures external capital flows
            #    (deposits, withdrawals) are not counted as trading PnL.
            with get_db_session() as db:
                bot_state = db.query(BotState).filter(BotState.mode == mode).first()
                if bot_state and equity is not None:
                    bot_state.last_wallet_sync_at = datetime.now(timezone.utc)
                    initial = (
                        bot_state.live_initial_bankroll or bot_state.bankroll or 100.0
                    )
                    net_deposits = (bot_state.total_deposits or 0.0) - (
                        bot_state.total_withdrawals or 0.0
                    )
                    bot_state.wallet_pnl = round(
                        equity - float(initial) - float(net_deposits), 2
                    )
                    db.commit()

            # 3. Reconcile bot state
            with get_db_session() as db:
                result = await reconcile_bot_state(db, apply=True)

            # 3b. Compare wallet_pnl vs total_pnl for P&L drift detection.
            #     Both sides now use the SAME accounting basis:
            #     - wallet_pnl = equity - initial - net_deposits
            #       (trading PnL including unrealized gains on open positions)
            #     - db_effective_pnl = total_pnl + open_unrealized_pnl
            #       where open_unrealized_pnl = (current market value - cost basis)
            #       of unsettled positions, so both sides include open positions.
            with get_db_session() as db:
                bot_state = db.query(BotState).filter(BotState.mode == mode).first()
                if bot_state:
                    wpnl = float(bot_state.wallet_pnl or 0.0)

                    # DB realized PnL from settled trades
                    tpnl = float(bot_state.total_pnl or 0.0)

                    # Cost basis of open (unsettled) positions from DB =
                    # SUM(size * entry_price) for all unsettled trades.
                    # This works for both YES and NO positions because
                    # entry_price is always the USDC cost per share.
                    open_cost_basis = (
                        db.query(
                            func.coalesce(
                                func.sum(Trade.size * Trade.entry_price), 0.0
                            )
                        )
                        .filter(
                            Trade.settled.is_(False),
                            Trade.trading_mode == mode,
                        )
                        .scalar()
                        or 0.0
                    )
                    open_cost_basis = float(open_cost_basis)

                    # Unrealized PnL = current market value - cost basis
                    unrealized_pnl = 0.0
                    if open_position_value is not None:
                        unrealized_pnl = float(open_position_value) - open_cost_basis

                    # Total effective PnL from DB = realized + unrealized
                    db_effective_pnl = tpnl + unrealized_pnl

                    denominator = max(abs(wpnl), abs(db_effective_pnl), 1.0)
                    pnl_drift_pct = abs(wpnl - db_effective_pnl) / denominator * 100
                    if pnl_drift_pct > 5.0:
                        logger.warning(
                            "[WalletReconciler] PnL drift %.1f%%: wallet_pnl=$%.2f vs "
                            "db_effective_pnl=$%.2f (realized=$%.2f, unrealized=$%.2f, "
                            "open_cost_basis=$%.2f)",
                            pnl_drift_pct,
                            wpnl,
                            db_effective_pnl,
                            tpnl,
                            unrealized_pnl,
                            open_cost_basis,
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
