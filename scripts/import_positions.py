"""
Import open positions from Polymarket Data API.

This script fetches current open positions from the Polymarket Data API
and imports them into the database as unsettled trades.
"""

import asyncio
import httpx
from datetime import datetime, timezone
from backend.models.database import SessionLocal, Trade, BotState
from backend.config import settings

# DATA_API_URL sourced from settings; fallback for standalone execution
try:
    DATA_API_URL = settings.DATA_API_URL
except (ImportError, AttributeError):
    DATA_API_URL = "https://data-api.polymarket.com"

async def import_positions_from_data_api(wallet_address: str, mode: str = "live"):
    """
    Import open positions from Polymarket Data API.
    
    Args:
        wallet_address: Wallet address to fetch positions for
        mode: Trading mode (paper, testnet, live)
    """
    db = SessionLocal()
    try:
        print(f"Fetching positions for wallet: {wallet_address}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{DATA_API_URL}/positions",
                params={"user": wallet_address}
            )
            response.raise_for_status()
            positions = response.json()
        
        print(f"Found {len(positions)} open positions")
        
        imported = 0
        updated = 0
        
        for pos in positions:
            # Skip redeemable positions (already settled)
            if pos.get("redeemable", False):
                continue
            
            asset_id = pos["asset"]
            size = pos["size"]
            avg_price = pos["avgPrice"]
            current_price = pos["curPrice"]
            initial_value = pos["initialValue"]
            current_value = pos["currentValue"]
            
            # Check if trade already exists
            existing = db.query(Trade).filter(
                Trade.market_ticker == asset_id,
                Trade.trading_mode == mode,
                not Trade.settled
            ).first()
            
            if existing:
                # Update existing trade
                existing.size = initial_value  # Use initial value as size (cost basis)
                existing.entry_price = avg_price
                existing.pnl = pos["cashPnl"]
                updated += 1
            else:
                # Create new trade
                trade = Trade(
                    market_ticker=asset_id,
                    direction="up" if pos["outcome"] == "Yes" else "down",
                    size=initial_value,  # Cost basis
                    entry_price=avg_price,
                    trading_mode=mode,
                    settled=False,
                    timestamp=datetime.now(timezone.utc),
                    pnl=pos["cashPnl"],
                    event_slug=pos.get("eventSlug"),
                    platform="polymarket"
                )
                db.add(trade)
                imported += 1
        
        db.commit()
        
        print("\nImport Summary:")
        print(f"  Imported: {imported}")
        print(f"  Updated: {updated}")
        print(f"  Total open positions: {imported + updated}")
        
        # Update BotState
        state = db.query(BotState).filter_by(mode=mode).first()
        if state:
            state.last_sync_at = datetime.now(timezone.utc)
            db.commit()
            print("  BotState updated")
        
        return imported, updated
        
    finally:
        db.close()


async def main():
    """Main entry point."""
    wallet = settings.POLYMARKET_BUILDER_ADDRESS or "0xad85c2f3942561afa448cbbd5811a5f7e2e3c6bd"
    
    print("=" * 80)
    print("Polymarket Position Import Tool")
    print("=" * 80)
    print()
    
    imported, updated = await import_positions_from_data_api(wallet, mode="live")
    
    print()
    print("=" * 80)
    print("Import Complete!")
    print("=" * 80)
    
    # Now calculate position value
    print()
    print("Calculating position market value...")
    
    from backend.core.position_valuation import calculate_position_market_value
    
    db = SessionLocal()
    try:
        async with httpx.AsyncClient() as client:
            result = await calculate_position_market_value("live", db, client)
        
        print("\nPosition Valuation:")
        print(f"  Position Cost: ${result['position_cost']:.2f}")
        print(f"  Position Market Value: ${result['position_market_value']:.2f}")
        print(f"  Unrealized PnL: ${result['unrealized_pnl']:.2f}")
        
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
