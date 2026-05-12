#!/usr/bin/env python
"""Test script to verify database validation constraints reject invalid data."""

import sys
from sqlalchemy.exc import IntegrityError
from backend.models.database import SessionLocal, Trade
from backend.core.validation import TradeValidator, SignalValidator, ValidationError

def test_invalid_trade_insertion():
    print("Testing database constraints for invalid trade data...")
    db = SessionLocal()
    
    try:
        print("\n1. Testing negative trade size (should fail)...")
        try:
            trade = Trade(
                market_ticker="TEST",
                platform="polymarket",
                direction="up",
                entry_price=0.65,
                size=-5.0,
                model_probability=0.7,
                market_price_at_entry=0.6,
                edge_at_entry=0.05,
                trading_mode="paper",
            )
            db.add(trade)
            db.commit()
            print("   ❌ FAILED: Negative size was accepted!")
            return False
        except IntegrityError:
            db.rollback()
            print("   ✅ PASSED: Database rejected negative size")
        
        print("\n2. Testing invalid price range (should fail)...")
        try:
            trade = Trade(
                market_ticker="TEST",
                platform="polymarket",
                direction="up",
                entry_price=1.5,
                size=5.0,
                model_probability=0.7,
                market_price_at_entry=0.6,
                edge_at_entry=0.05,
                trading_mode="paper",
            )
            db.add(trade)
            db.commit()
            print("   ❌ FAILED: Invalid price was accepted!")
            return False
        except IntegrityError:
            db.rollback()
            print("   ✅ PASSED: Database rejected invalid price")
        
        print("\n3. Testing invalid confidence (should fail)...")
        try:
            trade = Trade(
                market_ticker="TEST",
                platform="polymarket",
                direction="up",
                entry_price=0.65,
                size=5.0,
                model_probability=0.7,
                market_price_at_entry=0.6,
                edge_at_entry=0.05,
                trading_mode="paper",
                confidence=2.0,
            )
            db.add(trade)
            db.commit()
            print("   ❌ FAILED: Invalid confidence was accepted!")
            return False
        except IntegrityError:
            db.rollback()
            print("   ✅ PASSED: Database rejected invalid confidence")
        
        print("\n4. Testing valid trade (should succeed)...")
        try:
            trade = Trade(
                market_ticker="TEST",
                platform="polymarket",
                direction="up",
                entry_price=0.65,
                size=5.0,
                model_probability=0.7,
                market_price_at_entry=0.6,
                edge_at_entry=0.05,
                trading_mode="paper",
                confidence=0.75,
            )
            db.add(trade)
            db.commit()
            print(f"   ✅ PASSED: Valid trade accepted (ID: {trade.id})")
            db.delete(trade)
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"   ❌ FAILED: Valid trade rejected: {e}")
            return False
        
        print("\n5. Testing application-level validation...")
        try:
            invalid_data = {"size": -10.0, "entry_price": 1.5}
            TradeValidator.validate_trade_data(invalid_data)
            print("   ❌ FAILED: Application validator accepted invalid data!")
            return False
        except ValidationError as e:
            print(f"   ✅ PASSED: Application validator rejected: {e.message}")
        
        print("\n6. Testing signal validation...")
        try:
            invalid_signal = {"confidence": 2.0, "suggested_size": -5.0}
            SignalValidator.validate_signal_data(invalid_signal)
            print("   ❌ FAILED: Signal validator accepted invalid data!")
            return False
        except ValidationError as e:
            print(f"   ✅ PASSED: Signal validator rejected: {e.message}")
        
        print("\n" + "="*60)
        print("✅ ALL VALIDATION TESTS PASSED")
        print("="*60)
        return True
        
    finally:
        db.close()

if __name__ == "__main__":
    success = test_invalid_trade_insertion()
    sys.exit(0 if success else 1)
