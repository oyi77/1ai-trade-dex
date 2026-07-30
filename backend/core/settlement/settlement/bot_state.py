"""Bot state update and reconciliation after settlement."""

from typing import List

from sqlalchemy.orm import Session

from backend.models.database import Trade, BotState, botstate_mutex
from loguru import logger


async def update_bot_state_with_settlements(
    db: Session, settled_trades: List[Trade]
) -> None:
    """Update bot state with P&L from settled trades."""
    if not settled_trades:
        return

    try:
        async with botstate_mutex:
            from backend.core.wallet.botstate_ledger import BotStateLedger

            for trade in settled_trades:
                if trade.pnl is None and trade.result not in (
                    "expired",
                    "push",
                    "closed",
                    "expired_unresolved",
                    "btc_5min_unresolved",
                ):
                    continue

                trading_mode = getattr(trade, "trading_mode", "paper") or "paper"
                state = db.query(BotState).filter_by(mode=trading_mode).first()
                if not state:
                    logger.warning(f"Bot state not found for mode {trading_mode}")
                    continue

                try:
                    BotStateLedger.credit_on_settlement(
                        db=db, mode=trading_mode, trade=trade
                    )
                except LookupError as exc:
                    logger.warning(f"Settlement credit skipped: {exc}")

            db.commit()

        modes_with_settlements = {
            getattr(t, "trading_mode", "paper") or "paper"
            for t in settled_trades
            if t.pnl is not None
        }

        # Sync live bankroll from authoritative total equity source.
        if "live" in modes_with_settlements:
            try:
                from backend.core.wallet.bankroll_reconciliation import (
                    reconcile_bot_state as _reconcile,
                )

                reports = await _reconcile(
                    db,
                    modes=("live",),
                    apply=True,
                    commit=True,
                    source="settlement_live_sync",
                )
                if reports:
                    report = reports[0]
                    logger.info(
                        "Live bankroll reconciled after settlement: $%.2f (source=%s)",
                        report.new_bankroll,
                        report.source,
                    )
            except Exception as exc:
                logger.warning(
                    "Live bankroll reconciliation after settlement failed: %s — keeping additive PnL in bankroll", exc
                )

        # Log stats for ALL modes that had settlements
        for m in sorted(modes_with_settlements):
            state = db.query(BotState).filter_by(mode=m).first()
            if not state:
                logger.warning(f"Bot state not found while logging mode {m}")
                continue
            if m == "paper":
                logger.info(
                    f"Updated bot state (paper): Bankroll ${state.paper_bankroll:.2f}, "
                    f"P&L ${state.paper_pnl:+.2f}, {state.paper_trades} trades"
                )
            elif m == "testnet":
                logger.info(
                    f"Updated bot state (testnet): Bankroll ${state.testnet_bankroll:.2f}, "
                    f"P&L ${state.testnet_pnl:+.2f}, {state.testnet_trades} trades"
                )
            else:
                logger.info(
                    f"Updated bot state (live): Bankroll ${state.bankroll:.2f}, "
                    f"P&L ${state.total_pnl:+.2f}, {state.total_trades} trades"
                )
    except Exception as e:
        logger.error(f"Failed to update bot state: {e}")
        if db.in_transaction():
            db.rollback()


async def reconcile_bot_state(db: Session) -> None:
    """Recalculate bot_state from trade history to prevent drift.

    For live mode, cross-checks against Polymarket API portfolio value
    as the source of truth when on-chain wallet is available.
    """
    try:
        from backend.core.wallet.bankroll_reconciliation import (
            reconcile_bot_state as _reconcile,
        )

        await _reconcile(db, apply=True, commit=True, source="settlement_reconcile")
        logger.debug("Bot state reconciliation complete")

    except Exception as e:
        if db.in_transaction():
            db.rollback()
