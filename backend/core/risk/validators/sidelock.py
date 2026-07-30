"""
Side-lock validation — prevent opposing positions on the same market.
"""
from typing import Optional

from contextlib import nullcontext
from loguru import logger
from sqlalchemy import func

from backend.db.utils import get_db_session
from backend.models.database import Trade


def check_side_lock(
    market_ticker: str, direction: str, db=None, mode: Optional[str] = None
) -> Optional[str]:
    """Returns the conflicting side if an opposing-side, unsettled trade exists.

    Returns None if no side-lock is present.
    """
    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)
    try:
        with ctx as db:
            effective_mode = mode or "paper"
            side_field = getattr(Trade, "side", None) or getattr(
                Trade, "direction", None
            )
            side_yes = [s for s in ["YES", "BUY"] if direction.upper().startswith(s[:1])]
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
                return getattr(conflict, "side", getattr(conflict, "direction", None))
            return None
    except Exception as e:
        logger.opt(exception=True).error(
            "[risk_manager.check_side_lock] {}: {}", type(e).__name__, e,
        )
        return "error"
    finally:
        if owns_db:
            db.close()


def has_unsettled_trade(
    market_ticker: str,
    db=None,
    mode: Optional[str] = None,
    direction: Optional[str] = None,
) -> bool:
    """Check if there's an unsettled trade for a market (optionally per-direction)."""
    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)
    try:
        with ctx as db:
            effective_mode = mode or "paper"
            query = db.query(func.count(Trade.id)).filter(
                Trade.market_ticker == market_ticker,
                Trade.settled.is_(False),
                Trade.trading_mode == effective_mode,
            )
            if direction is not None:
                query = query.filter(Trade.direction == direction)
            count = query.scalar() or 0
            return count > 0
    except Exception as e:
        logger.opt(exception=True).error(
            "[risk_manager._has_unsettled_trade] {}: {}", type(e).__name__, e,
        )
        return True
    finally:
        if owns_db:
            db.close()
