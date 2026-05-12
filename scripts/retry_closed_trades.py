#!/usr/bin/env python3
"""Retry settlement for closed trades with NULL settlement values."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.models.database import SessionLocal, Trade
from backend.core.settlement_helpers import (
    fetch_polymarket_resolution,
    calculate_pnl,
    process_settled_trade,
)
import logging

logging.basicConfig(level=logging.INFO)
from loguru import logger


async def retry_closed_trades():
    db = SessionLocal()
    try:
        closed_trades = (
            db.query(Trade)
            .filter(
                Trade.result == "closed",
                Trade.settlement_value == None
            )
            .all()
        )
        
        logger.info(f"Found {len(closed_trades)} closed trades to retry")
        
        fixed = 0
        for trade in closed_trades:
            logger.info(f"\nRetrying trade {trade.id}: {trade.market_ticker}")
            
            is_resolved, settlement_value = await fetch_polymarket_resolution(
                trade.market_ticker,
                event_slug=getattr(trade, "event_slug", None)
            )
            
            if is_resolved and settlement_value is not None:
                pnl = calculate_pnl(trade, settlement_value)
                
                trade.settlement_value = settlement_value
                trade.pnl = pnl
                
                if pnl > 0:
                    trade.result = "win"
                elif pnl < 0:
                    trade.result = "loss"
                else:
                    trade.result = "push"
                
                logger.info(f"  ✓ Resolved: settlement_value={settlement_value}, pnl=${pnl:.2f}, result={trade.result}")
                fixed += 1
            else:
                logger.info(f"  ✗ Market not resolved yet, keeping as 'closed'")
        
        if fixed > 0:
            db.commit()
            logger.info(f"\n✓ Fixed {fixed} trades")
        else:
            logger.info(f"\n✗ No trades could be resolved")
        
        return fixed
        
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(retry_closed_trades())
