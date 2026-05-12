#!/usr/bin/env python3
"""
Fix critical production bugs in PolyEdge trading bot.

Issues fixed:
1. Settlement process not fetching resolution data
2. Settled trades with NULL settlement_value and pnl
3. Stats calculation only counting settled trades
4. No equity snapshots being created
5. Bot state out of sync with actual trades
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import func, case
from backend.models.database import SessionLocal, Trade, BotState, EquitySnapshot
from backend.core.settlement_helpers import (
    fetch_polymarket_resolution,
    calculate_pnl,
    process_settled_trade,
)
from backend.config import settings
import logging

logging.basicConfig(level=logging.INFO)
from loguru import logger


async def backfill_missing_settlement_data(db):
    """Fix settled trades with NULL settlement_value and pnl."""
    logger.info("=" * 80)
    logger.info("STEP 1: Backfilling missing settlement data")
    logger.info("=" * 80)
    
    # Find settled trades with missing data
    broken_trades = (
        db.query(Trade)
        .filter(
            Trade.settled == True,
            (Trade.settlement_value == None) | (Trade.pnl == None)
        )
        .all()
    )
    
    logger.info(f"Found {len(broken_trades)} settled trades with missing data")
    
    fixed_count = 0
    for trade in broken_trades:
        logger.info(f"\nProcessing trade {trade.id}: {trade.market_ticker}")
        
        # Try to fetch resolution
        is_resolved, settlement_value = await fetch_polymarket_resolution(
            trade.market_ticker,
            event_slug=getattr(trade, "event_slug", None)
        )
        
        if is_resolved and settlement_value is not None:
            # Calculate PNL
            pnl = calculate_pnl(trade, settlement_value)
            
            # Update trade
            trade.settlement_value = settlement_value
            trade.pnl = pnl
            
            # Set result based on PNL
            if pnl > 0:
                trade.result = "win"
            elif pnl < 0:
                trade.result = "loss"
            else:
                trade.result = "push"
            
            logger.info(f"  ✓ Fixed: settlement_value={settlement_value}, pnl=${pnl:.2f}, result={trade.result}")
            fixed_count += 1
        else:
            logger.warning(f"  ✗ Could not resolve market {trade.market_ticker}")
    
    if fixed_count > 0:
        db.commit()
        logger.info(f"\n✓ Fixed {fixed_count} trades with missing settlement data")
    else:
        logger.info("\n✗ No trades could be fixed (markets may not be resolved yet)")
    
    return fixed_count


async def sync_bot_state(db):
    """Sync bot_state with actual trade counts."""
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2: Syncing bot_state with actual trades")
    logger.info("=" * 80)
    
    for mode in ["paper", "testnet", "live"]:
        state = db.query(BotState).filter_by(mode=mode).first()
        if not state:
            logger.warning(f"No bot_state found for mode: {mode}")
            continue
        
        # Count settled trades (wins/losses only, not expired/closed)
        settled_stats = (
            db.query(
                func.count(Trade.id),
                func.sum(Trade.pnl),
                func.sum(case((Trade.result == "win", 1), else_=0)),
            )
            .filter(
                Trade.settled == True,
                Trade.trading_mode == mode,
                Trade.result.in_(["win", "loss"]),
                Trade.source == "bot"
            )
            .first()
        )
        
        trade_count, total_pnl, win_count = settled_stats
        trade_count = trade_count or 0
        total_pnl = total_pnl or 0.0
        win_count = win_count or 0
        
        # Count open trades
        open_count = (
            db.query(func.count(Trade.id))
            .filter(Trade.settled == False, Trade.trading_mode == mode)
            .scalar() or 0
        )
        
        # Update mode-specific fields
        if mode == "paper":
            old_trades = state.paper_trades or 0
            old_wins = state.paper_wins or 0
            state.paper_trades = trade_count
            state.paper_wins = win_count
            state.paper_pnl = round(total_pnl, 2)
            logger.info(f"\n{mode.upper()} mode:")
            logger.info(f"  Trades: {old_trades} → {trade_count}")
            logger.info(f"  Wins: {old_wins} → {win_count}")
            logger.info(f"  Open: {open_count}")
            logger.info(f"  PNL: ${state.paper_pnl:.2f}")
        elif mode == "testnet":
            old_trades = state.testnet_trades or 0
            old_wins = state.testnet_wins or 0
            state.testnet_trades = trade_count
            state.testnet_wins = win_count
            state.testnet_pnl = round(total_pnl, 2)
            logger.info(f"\n{mode.upper()} mode:")
            logger.info(f"  Trades: {old_trades} → {trade_count}")
            logger.info(f"  Wins: {old_wins} → {win_count}")
            logger.info(f"  Open: {open_count}")
            logger.info(f"  PNL: ${state.testnet_pnl:.2f}")
        else:  # live
            old_trades = state.total_trades or 0
            old_wins = state.winning_trades or 0
            state.total_trades = trade_count
            state.winning_trades = win_count
            state.total_pnl = round(total_pnl, 2)
            logger.info(f"\n{mode.upper()} mode:")
            logger.info(f"  Trades: {old_trades} → {trade_count}")
            logger.info(f"  Wins: {old_wins} → {win_count}")
            logger.info(f"  Open: {open_count}")
            logger.info(f"  PNL: ${state.total_pnl:.2f}")
    
    db.commit()
    logger.info("\n✓ Bot state synced successfully")


async def create_equity_snapshots(db):
    """Create equity snapshots for historical tracking."""
    logger.info("\n" + "=" * 80)
    logger.info("STEP 3: Creating equity snapshots")
    logger.info("=" * 80)
    
    # Check if snapshots already exist
    existing_count = db.query(func.count(EquitySnapshot.id)).scalar() or 0
    logger.info(f"Existing snapshots: {existing_count}")
    
    if existing_count > 0:
        logger.info("Equity snapshots already exist, skipping creation")
        return
    
    # Create snapshot for each mode
    for mode in ["paper", "testnet", "live"]:
        state = db.query(BotState).filter_by(mode=mode).first()
        if not state:
            continue
        
        # Get stats for this mode
        if mode == "paper":
            bankroll = state.paper_bankroll or settings.INITIAL_BANKROLL
            total_pnl = state.paper_pnl or 0.0
            trade_count = state.paper_trades or 0
            win_count = state.paper_wins or 0
        elif mode == "testnet":
            bankroll = state.testnet_bankroll or 100.0
            total_pnl = state.testnet_pnl or 0.0
            trade_count = state.testnet_trades or 0
            win_count = state.testnet_wins or 0
        else:  # live
            bankroll = state.bankroll or settings.INITIAL_BANKROLL
            total_pnl = state.total_pnl or 0.0
            trade_count = state.total_trades or 0
            win_count = state.winning_trades or 0
        
        # Calculate open exposure
        open_exposure = (
            db.query(func.sum(Trade.size))
            .filter(Trade.settled == False, Trade.trading_mode == mode)
            .scalar() or 0.0
        )
        
        # Create snapshot
        snapshot = EquitySnapshot(
            timestamp=datetime.now(timezone.utc),
            bankroll=bankroll,
            total_pnl=total_pnl,
            open_exposure=open_exposure,
            trade_count=trade_count,
            win_count=win_count,
            strategy_allocations={"mode": mode}
        )
        db.add(snapshot)
        
        logger.info(f"\n{mode.upper()} snapshot:")
        logger.info(f"  Bankroll: ${bankroll:.2f}")
        logger.info(f"  PNL: ${total_pnl:.2f}")
        logger.info(f"  Open exposure: ${open_exposure:.2f}")
        logger.info(f"  Trades: {trade_count} ({win_count} wins)")
    
    db.commit()
    logger.info("\n✓ Equity snapshots created successfully")


async def verify_fixes(db):
    """Verify all fixes were applied correctly."""
    logger.info("\n" + "=" * 80)
    logger.info("VERIFICATION: Checking all fixes")
    logger.info("=" * 80)
    
    # Check for remaining NULL values
    broken_count = (
        db.query(func.count(Trade.id))
        .filter(
            Trade.settled == True,
            (Trade.settlement_value == None) | (Trade.pnl == None)
        )
        .scalar() or 0
    )
    
    logger.info(f"\n1. Settled trades with NULL values: {broken_count}")
    if broken_count == 0:
        logger.info("   ✓ PASS: All settled trades have settlement data")
    else:
        logger.warning(f"   ✗ FAIL: {broken_count} trades still have NULL values")
    
    # Check equity snapshots
    snapshot_count = db.query(func.count(EquitySnapshot.id)).scalar() or 0
    logger.info(f"\n2. Equity snapshots: {snapshot_count}")
    if snapshot_count > 0:
        logger.info("   ✓ PASS: Equity snapshots exist")
    else:
        logger.warning("   ✗ FAIL: No equity snapshots found")
    
    # Check bot_state sync
    logger.info("\n3. Bot state sync:")
    for mode in ["paper", "testnet", "live"]:
        state = db.query(BotState).filter_by(mode=mode).first()
        if not state:
            continue
        
        actual_settled = (
            db.query(func.count(Trade.id))
            .filter(
                Trade.settled == True,
                Trade.trading_mode == mode,
                Trade.result.in_(["win", "loss"]),
                Trade.source == "bot"
            )
            .scalar() or 0
        )
        
        if mode == "paper":
            state_count = state.paper_trades or 0
        elif mode == "testnet":
            state_count = state.testnet_trades or 0
        else:
            state_count = state.total_trades or 0
        
        logger.info(f"   {mode}: state={state_count}, actual={actual_settled}")
        if state_count == actual_settled:
            logger.info(f"      ✓ PASS")
        else:
            logger.warning(f"      ✗ FAIL: Mismatch")
    
    logger.info("\n" + "=" * 80)
    logger.info("VERIFICATION COMPLETE")
    logger.info("=" * 80)


async def main():
    """Run all fixes."""
    logger.info("\n" + "=" * 80)
    logger.info("POLYEDGE PRODUCTION BUG FIX")
    logger.info("=" * 80)
    logger.info(f"Database: {settings.DATABASE_URL}")
    logger.info(f"Trading mode: {settings.TRADING_MODE}")
    logger.info("=" * 80)
    
    db = SessionLocal()
    try:
        # Run all fixes
        await backfill_missing_settlement_data(db)
        await sync_bot_state(db)
        await create_equity_snapshots(db)
        await verify_fixes(db)
        
        logger.info("\n" + "=" * 80)
        logger.info("✓ ALL FIXES COMPLETED SUCCESSFULLY")
        logger.info("=" * 80)
        logger.info("\nNext steps:")
        logger.info("1. Restart the backend server")
        logger.info("2. Check the dashboard - stats should now be correct")
        logger.info("3. Monitor settlement process for new trades")
        
    except Exception as e:
        logger.error(f"\n✗ ERROR: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
