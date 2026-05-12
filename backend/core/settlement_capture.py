"""
Capture positions before they close/disappear from Polymarket API
This ensures we don't lose historical trade data
"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from backend.models.database import Trade

from loguru import logger
async def capture_closing_position(trade: Trade, cashPnl: float, db: Session) -> bool:
    """
    Capture position data BEFORE it closes and disappears from API

    Args:
        trade: Trade object to capture
        cashPnl: Final PNL from Polymarket
        db: Database session

    Returns:
        True if captured successfully
    """
    try:
        # Update trade with final data BEFORE claiming
        trade.settled = True
        trade.pnl = cashPnl
        trade.settlement_time = datetime.now(timezone.utc)

        if cashPnl > 0:
            trade.result = 'win'
        elif cashPnl < 0:
            trade.result = 'loss'
        else:
            trade.result = 'push'

        # Commit to database FIRST
        db.commit()

        logger.info(f"✅ Captured closing position: {trade.market_ticker} PNL=${cashPnl:.2f}")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to capture closing position: {e}")
        db.rollback()
        return False


async def ensure_position_captured(market_ticker: str, db: Session) -> Optional[Trade]:
    """
    Ensure a position is captured in database before it disappears

    Args:
        market_ticker: Market ticker to check
        db: Database session

    Returns:
        Trade object if found, None otherwise
    """
    trade = db.query(Trade).filter(
        Trade.market_ticker == market_ticker,
        Trade.settled == False
    ).first()

    if not trade:
        logger.warning(f"⚠️  Position {market_ticker} not found in database")
        return None

    return trade
