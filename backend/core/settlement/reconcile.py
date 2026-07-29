"""
Reconcile open trades with Polymarket positions and resolve pending paper trades.

Extracted from settlement_helpers.py to reduce that module's size.
"""
from datetime import datetime, timedelta, timezone
from typing import List

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from backend.config import settings
from backend.data.shared_client import get_shared_client
from backend.core.settlement.calculate_pnl import calculate_pnl
from backend.models.database import Trade


async def reconcile_positions(db: Session) -> List[int]:
    """
    Reconcile open trades with actual Polymarket positions.

    Fetches current positions from Polymarket and compares with open trades in DB.
    Returns list of trade IDs that should be marked as "closed" (position no longer exists).

    This catches:
    - Orders that were filled then sold manually
    - Orders that expired unfilled
    - Positions closed outside the bot
    """
    from backend.data.polymarket_clob import clob_from_settings

    effective_mode = settings.TRADING_MODE
    wallet_address = settings.POLYMARKET_BUILDER_ADDRESS

    if not wallet_address:
        logger.debug("No wallet address available for position reconciliation")
        return []

    try:
        async with clob_from_settings(mode=effective_mode) as clob:
            positions = await clob.get_trader_positions(wallet_address)

        active_positions = set()
        for pos in positions:
            market_ticker = pos.get("slug")

            if market_ticker and float(pos.get("size", 0)) > 0:
                active_positions.add(market_ticker)

        logger.info(
            f"Position reconciliation: found {len(active_positions)} active positions on Polymarket"
        )

        open_trades = (
            db.query(Trade)
            .filter(
                Trade.settled.is_(False),
                Trade.trading_mode == effective_mode,
                Trade.platform == "polymarket",
            )
            .all()
        )

        logger.info(
            f"Position reconciliation: found {len(open_trades)} open trades in DB"
        )

        trades_to_close = []
        for trade in open_trades:
            if trade.market_ticker not in active_positions:
                trades_to_close.append(trade.id)
                logger.info(
                    f"Trade {trade.id} marked for closure: {trade.market_ticker} "
                    f"{trade.direction.upper()} (position not found on Polymarket)"
                )

        logger.info(
            f"Position reconciliation: {len(trades_to_close)} trades to mark as closed"
        )
        return trades_to_close

    except Exception as e:
        logger.error("[Settlement] reconciliation error: {}", e)
        logger.error(
            f"[settlement_helpers.reconcile_positions] {type(e).__name__}: "
            f"Position reconciliation failed: {e}",
            exc_info=True,
        )
        return []


async def resolve_paper_trades(db) -> List[Trade]:
    """
    Resolve pending paper trades via Gamma API outcome prices.
    Paper trades are marked settled=True but result='pending' — this
    queries Gamma for actual market outcomes and updates PnL accordingly.
    """
    # Find paper trades still pending resolution
    pending = (
        db.query(Trade)
        .filter(
            Trade.trading_mode == "paper",
            Trade.settled,
            Trade.pnl.is_(None),
        )
        .all()
    )

    if not pending:
        return []

    settled = []
    now = datetime.now(timezone.utc)

    # Filter out trades that are too young to settle (prevents premature settlement
    # on markets that haven't had time to resolve — Gamma prices can spike to extremes
    # on illiquid markets before actual resolution)
    MIN_SETTLE_AGE = timedelta(hours=1)
    pending = [
        t
        for t in pending
        if t.timestamp
        and (
            now
            - (
                t.timestamp.replace(tzinfo=timezone.utc)
                if t.timestamp.tzinfo is None
                else t.timestamp
            )
        )
        > MIN_SETTLE_AGE
    ]

    if not pending:
        return []

    # Deduplicate by market_ticker
    tickers = list(set(t.market_ticker for t in pending))

    client = get_shared_client()
    for ticker in tickers:
        try:
            r = await client.get(
                f"{settings.GAMMA_API_URL}/markets",
                params={"slug": ticker},
            )
            if r.status_code != 200:
                continue
            data = r.json()
            if not isinstance(data, list) or not data:
                continue

            market = data[0]
            prices = market.get("outcomePrices", [])
            if not prices:
                continue

            try:
                p0 = float(prices[0]) if prices[0] is not None else None
            except (ValueError, TypeError):
                p0 = None
            try:
                p1 = (
                    float(prices[1])
                    if len(prices) > 1 and prices[1] is not None
                    else None
                )
            except (ValueError, TypeError):
                p1 = None

            # If prices are non-numeric (e.g. "[" from unresolved markets),
            # skip — will be force-settled by stale cleanup job after max age
            if p0 is None or p1 is None:
                continue

            # Determine settlement value from extreme prices
            threshold = 0.005
            if p0 <= threshold and p1 >= (1.0 - threshold):
                settlement_value = 0.0  # outcome index 0 won (NO)
            elif p1 <= threshold and p0 >= (1.0 - threshold):
                settlement_value = 1.0  # outcome index 1 won (YES)
            else:
                continue  # market still open

            condition_id = market.get("conditionId", "")

            # Update all trades for this ticker
            for trade in pending:
                if trade.market_ticker == ticker:
                    dir_yes = trade.direction in ("yes", "up")
                    is_win = (dir_yes and settlement_value == 1.0) or (
                        not dir_yes and settlement_value == 0.0
                    )

                    trade.result = "win" if is_win else "loss"
                    trade.settlement_value = settlement_value
                    trade.settlement_time = now
                    trade.settlement_source = "gamma_outcome"

                    trade.pnl = calculate_pnl(trade, settlement_value)

                    if condition_id:
                        trade.condition_id = condition_id

                    settled.append(trade)
        except Exception as e:
            logger.warning(f"Paper settlement failed for {ticker}: {e}")
            continue

    if settled:
        try:
            db.commit()
        except Exception as e:
            logger.error(f"Failed to commit paper settlements: {e}")
            db.rollback()
            return []

        # Record outcomes to strategy_outcomes table
        try:
            from backend.core.outcome_repository import record_outcome

            for trade in settled:
                if trade.result in ("win", "loss"):
                    record_outcome(trade, db)
        except Exception as e:
            logger.error(f"Failed to record paper outcomes: {e}")

        # Update bot_state counters for settled paper trades
        try:
            from backend.models.database import BotState

            state = db.query(BotState).filter_by(mode="paper").first()
            if state:
                for trade in settled:
                    if trade.pnl is None:
                        continue
                    state.paper_pnl = (state.paper_pnl or 0) + trade.pnl
                    state.paper_trades = (state.paper_trades or 0) + 1
                    if trade.result == "win":
                        state.paper_wins = (state.paper_wins or 0) + 1
            db.commit()
        except Exception as e:
            logger.error(f"Failed to update paper bot_state: {e}")

    return settled
