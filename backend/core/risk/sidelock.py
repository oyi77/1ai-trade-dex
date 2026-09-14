"""
Side-lock and unsettled trade checks — prevent opposing positions on same market.
"""

from contextlib import nullcontext
from typing import Optional

from backend.config import settings
from backend.db.utils import get_db_session
from backend.models.database import Trade
from loguru import logger


def check_side_lock(
    market_ticker: str, direction: str, db=None, mode: Optional[str] = None
) -> Optional[str]:
    """Returns the conflicting side if an opposing-side, unsettled trade exists for the given market.
    Returns None if no side-lock is present.
    """
    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)
    try:
        with ctx as db:
            effective_mode = mode or settings.TRADING_MODE
            # Opposing side: if direction is 'YES', look for 'NO', and vice versa
            side_field = getattr(Trade, "side", None) or getattr(
                Trade, "direction", None
            )
            # Attempt both 'YES/NO' and 'BUY/SELL' as supported
            side_yes = [
                s for s in ["YES", "BUY"] if direction.upper().startswith(s[:1])
            ]
            if side_yes:
                opp_sides = ["NO", "SELL"]
            else:
                opp_sides = ["YES", "BUY"]
            conflict = (
                db.query(Trade)
                .filter(
                    Trade.market_ticker == market_ticker,
                    Trade.settled.is_(False),
                    Trade.trading_mode == effective_mode,
                    side_field.in_(opp_sides),
                )
                .first()
            )
            if conflict is not None:
                return getattr(
                    conflict, "side", getattr(conflict, "direction", None)
                )
            return None
    except Exception as e:
        logger.opt(exception=True).error(
            "[risk.sidelock.check_side_lock] {}: {}",
            type(e).__name__,
            e,
        )
        return "error"
    finally:
        if owns_db:
            db.close()


def _has_unsettled_trade(
    market_ticker: str,
    db=None,
    mode: Optional[str] = None,
    direction: Optional[str] = None,
    strategy_name: Optional[str] = None,
) -> bool:
    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)
    try:
        with ctx as db:
            effective_mode = mode or settings.TRADING_MODE
            query = db.query(func.count(Trade.id)).filter(
                Trade.market_ticker == market_ticker,
                Trade.settled.is_(False),
                Trade.trading_mode == effective_mode,
            )
            if strategy_name:
                query = query.filter(Trade.strategy == strategy_name)
            # Per-direction check: YES and NO positions can coexist on the same market
            if direction is not None:
                query = query.filter(Trade.direction == direction)
            count = query.scalar() or 0
            return count > 0
    except Exception as e:
        logger.opt(exception=True).error(
            "[risk.sidelock._has_unsettled_trade] {}: {}",
            type(e).__name__,
            e,
        )
        return True
    finally:
        if owns_db:
            db.close()


from sqlalchemy import func