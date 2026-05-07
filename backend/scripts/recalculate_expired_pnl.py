"""Recover expired trades by re-fetching market resolutions from the Polymarket API.

Two modes:
  1. recalculate: Trades with settlement_value but pnl=0 (already had data, just bad math)
  2. recover: Trades with NO settlement_value (expired before API returned resolution)

Usage:
  python -m backend.scripts.recalculate_expired_pnl [--dry-run]          # recalculate only
  python -m backend.scripts.recalculate_expired_pnl --recover [--dry-run] # re-fetch from API
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.models.database import get_db, Trade, BotState, for_update
from backend.core.settlement_helpers import calculate_pnl, fetch_polymarket_resolution
from backend.config import settings


def recalculate_expired_trades(dry_run: bool = False):
    db = next(get_db())

    affected = (
        db.query(Trade)
        .filter(
            Trade.result == "expired",
            Trade.settlement_value.isnot(None),
            Trade.pnl == 0,
        )
        .all()
    )

    print(f"Found {len(affected)} expired trades with settlement_value but pnl=0")

    wins = 0
    losses = 0
    pushes = 0
    total_pnl_delta = 0.0

    for trade in affected:
        old_pnl = trade.pnl
        new_pnl = calculate_pnl(trade, trade.settlement_value)

        if new_pnl > 0:
            new_result = "win"
            wins += 1
        elif new_pnl < 0:
            new_result = "loss"
            losses += 1
        else:
            new_result = "push"
            pushes += 1

        total_pnl_delta += new_pnl - old_pnl

        print(
            f"  Trade {trade.id}: {trade.direction} @ {trade.entry_price} "
            f"size={trade.size:.2f} settle={trade.settlement_value} "
            f"pnl: {old_pnl} -> {new_pnl:+.2f} ({new_result})"
        )

        if not dry_run:
            trade.pnl = new_pnl
            trade.result = new_result

    print(f"\nSummary: {wins} wins, {losses} losses, {pushes} pushes")
    print(f"Total PnL change: ${total_pnl_delta:+.2f}")

    if not dry_run:
        db.commit()
        print("Changes committed.")

        _reconcile_bot_state(db)
    else:
        print("DRY RUN — no changes made.")


def _reconcile_bot_state(db):
    from sqlalchemy import func, case

    state = for_update(db, db.query(BotState)).first()
    if not state:
        print("No BotState found!")
        return

    real_trades = (
        db.query(
            func.count(Trade.id),
            func.sum(Trade.pnl),
            func.sum(case((Trade.result == "win", 1), else_=0)),
        )
        .filter(Trade.settled.is_(True), Trade.result.in_(("win", "loss")))
        .first()
    )

    trade_count, realized_pnl, win_count = real_trades
    trade_count = trade_count or 0
    realized_pnl = round(realized_pnl or 0.0, 2)
    win_count = win_count or 0

    open_exposure = (
        db.query(func.sum(Trade.size)).filter(Trade.settled.is_(False)).scalar()
    ) or 0.0

    correct_bankroll = round(
        settings.INITIAL_BANKROLL + realized_pnl - open_exposure, 2
    )

    print("\nBotState reconciliation:")
    print(f"  paper_bankroll: {state.paper_bankroll} -> {correct_bankroll}")
    print(f"  paper_pnl: {state.paper_pnl} -> {realized_pnl}")
    print(f"  paper_trades: {state.paper_trades} -> {trade_count}")
    print(f"  paper_wins: {state.paper_wins} -> {win_count}")

    state.paper_bankroll = correct_bankroll
    state.paper_pnl = realized_pnl
    state.paper_trades = trade_count
    state.paper_wins = win_count
    db.commit()
    print("BotState reconciled.")


async def recover_expired_trades(dry_run: bool = False):
    """Re-fetch market resolutions from Polymarket API for expired trades with no settlement_value.

    These trades expired before the API returned a resolution (e.g., the old
    STALE_TRADE_HOURS=18 window was too short). We now query each market
    individually to see if it has since resolved, and if so, compute proper PnL.
    """
    db = next(get_db())

    expired_no_sv = (
        db.query(Trade)
        .filter(
            Trade.result == "expired",
            Trade.settlement_value.is_(None),
        )
        .all()
    )

    print(f"Found {len(expired_no_sv)} expired trades with settlement_value=None")
    if not expired_no_sv:
        print("Nothing to recover.")
        return

    recovered = 0
    still_unresolved = 0
    api_errors = 0
    total_pnl_recovered = 0.0

    for trade in expired_no_sv:
        ticker = trade.market_ticker
        slug = getattr(trade, "event_slug", None)

        try:
            is_resolved, settlement_value = await fetch_polymarket_resolution(
                ticker, event_slug=slug
            )
        except Exception as e:
            print(f"  Trade {trade.id} [{ticker}]: API error — {e}")
            api_errors += 1
            continue

        if not is_resolved or settlement_value is None:
            print(f"  Trade {trade.id} [{ticker}]: still unresolved")
            still_unresolved += 1
            continue

        pnl = calculate_pnl(trade, settlement_value)

        if pnl > 0:
            new_result = "win"
        elif pnl < 0:
            new_result = "loss"
        else:
            new_result = "push"

        total_pnl_recovered += pnl

        print(
            f"  Trade {trade.id} [{ticker}]: {trade.direction} @ {trade.entry_price} "
            f"size=${trade.size:.2f} -> settle={settlement_value} "
            f"pnl=${pnl:+.2f} ({new_result})"
        )

        if not dry_run:
            trade.settlement_value = settlement_value
            trade.pnl = pnl
            trade.result = new_result

        recovered += 1

    print("\nRecovery summary:")
    print(f"  Recovered:    {recovered}")
    print(f"  Unresolved:   {still_unresolved}")
    print(f"  API errors:   {api_errors}")
    print(f"  Total PnL:    ${total_pnl_recovered:+.2f}")

    if not dry_run and recovered > 0:
        db.commit()
        print("Trade changes committed.")
        _reconcile_bot_state(db)
    else:
        if dry_run:
            print("DRY RUN — no changes made.")
        else:
            print("No trades recovered — nothing to commit.")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    recover = "--recover" in sys.argv

    if recover:
        asyncio.run(recover_expired_trades(dry_run=dry))
    else:
        recalculate_expired_trades(dry_run=dry)
