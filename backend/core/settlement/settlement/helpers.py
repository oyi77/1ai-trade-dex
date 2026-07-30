"""Module-level shared state and helper functions for settlement."""

import asyncio
from sqlalchemy.orm import Session
from sqlalchemy import text as sa_text
from loguru import logger


_settlement_lock = asyncio.Lock()


def _ensure_session(db: Session) -> None:
    """Ping the DB connection and reconnect if it dropped during async awaits."""
    try:
        db.execute(sa_text("SELECT 1"))
    except Exception:
        logger.warning("[settlement] DB session stale, rolling back and reconnecting")
        try:
            db.rollback()
        except Exception:
            pass
        db.bind.dispose()
        # Re-establish the connection by forcing a new checkout
        db.connection().close()
        db.connection()


# Track trades whose position is gone but API couldn't confirm resolution.
# Maps trade_id -> datetime of first detection. Used to implement a grace
# period before force-settling as loss, preventing false loss markings from
# temporary API failures.
_closed_unresolved_grace: dict = {}


async def _fetch_pm_portfolio_value() -> float | None:
    """Fetch live total equity (USDC cash + open position value)."""
    from backend.core.wallet.bankroll_reconciliation import fetch_pm_total_equity

    return await fetch_pm_total_equity()
