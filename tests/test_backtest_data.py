#!/usr/bin/env python3
"""
Script to create historical test data for backtesting verification.
Creates simulated settled trades with realistic outcomes.
"""
import sys
sys.path.insert(0, '.')

from datetime import datetime, timedelta
from backend.models.database import SessionLocal, Trade, Signal
import random

def create_historical_test_data():
    """Create historical signals and settled trades for testing."""
    session = SessionLocal()

    print("Creating historical test data for backtesting...")

    # Create 20 historical signals from past 7 days
    base_time = datetime.now() - timedelta(days=7)

    for i in range(20):
        signal_time = base_time + timedelta(hours=i*8)

        # Create signal
        signal = Signal(
            market_ticker=f"BTC-{i}",
            platform="polymarket",
            market_type="btc",
            direction="up" if i % 2 == 0 else "down",
            model_probability=0.6,
            market_price=0.50,
            edge=0.1,  # 10% edge - passes threshold
            confidence=0.7,
            suggested_size=10.0,
            reasoning="Test signal for backtesting",
            timestamp=signal_time,
            executed=True,
            actual_outcome="up" if i % 2 == 0 else "down",
            outcome_correct=True
        )
        session.add(signal)

        # Create corresponding settled trade
        win = random.choice([True, False])
        trade = Trade(
            market_ticker=f"BTC-{i}",
            platform="polymarket",
            direction="up" if i % 2 == 0 else "down",
            entry_price=0.50,
            size=10.0,
            timestamp=signal_time + timedelta(minutes=5),
            settled=True,
            result="win" if win else "loss",
            pnl=5.0 if win else -5.0,  # $5 win or $5 loss
            strategy="test_strategy",
            signal_source="backtest_test",
            confidence=0.7
        )
        session.add(trade)

    session.commit()
    print("Created 20 historical signals and 20 settled trades")

    # Verify
    signal_count = session.query(Signal).count()
    trade_count = session.query(Trade).filter(Trade.settled).count()
    print(f"Total signals in DB: {signal_count}")
    print(f"Settled trades in DB: {trade_count}")

    session.close()

if __name__ == "__main__":
    create_historical_test_data()
