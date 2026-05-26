import os
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
import duckdb
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base, Trade, BotState
from backend.core.risk.risk_manager import RiskManager, RiskDecision
from backend.core.learning.calibration_tracker import compute_price_bucket_calibration
from backend.core.longshot_bias import LongshotBiasDetector
from backend.core.db_archiver import archive_trades_to_parquet, query_parquet_analytics


def test_price_bucket_calibration_tracking(db_session):
    """Test calibration tracking in 5c increments from settled trades."""
    # Insert settled trades in various buckets
    # Bucket 1: 10-15c (predicted: 12.5c / 0.125)
    # 10 trades, 2 wins (actual win rate: 20%) -> error: 20% - 12.5% = 7.5%
    now = datetime.now(timezone.utc)
    for i in range(10):
        t = Trade(
            market_ticker="m1",
            platform="polymarket",
            entry_price=0.12,  # in 10-15c bucket
            settled=True,
            result="win" if i < 2 else "loss",
            timestamp=now,
        )
        db_session.add(t)

    # Bucket 2: 80-85c (predicted: 82.5c / 0.825)
    # 10 trades, 9 wins (actual win rate: 90%) -> error: 90% - 82.5% = 7.5%
    for i in range(10):
        t = Trade(
            market_ticker="m2",
            platform="polymarket",
            entry_price=0.82,  # in 80-85c bucket
            settled=True,
            result="win" if i < 9 else "loss",
            timestamp=now,
        )
        db_session.add(t)

    db_session.commit()

    # Compute calibration tracking with bucket width 5
    calib = compute_price_bucket_calibration(db_session, bucket_width=5, window_days=1)

    # Verify Bucket 1 (10c)
    assert 10 in calib
    assert calib[10]["trades"] == 10
    assert calib[10]["predicted"] == 0.125
    assert calib[10]["actual"] == 0.20
    assert abs(calib[10]["error"] - 0.075) < 1e-5
    assert calib[10]["confidence"] == 10 / 50

    # Verify Bucket 2 (80c)
    assert 80 in calib
    assert calib[80]["trades"] == 10
    assert calib[80]["predicted"] == 0.825
    assert calib[80]["actual"] == 0.90
    assert abs(calib[80]["error"] - 0.075) < 1e-5


def test_risk_manager_calibration_adjustment(db_session):
    """Test RiskManager probability adjustment based on price bucket calibration."""
    # Setup calibration data
    now = datetime.now(timezone.utc)
    # 10 trades, 8 wins in 20-25c bucket -> error = 0.80 - 0.225 = 0.575
    for i in range(10):
        t = Trade(
            market_ticker="m3",
            platform="polymarket",
            entry_price=0.21,
            settled=True,
            result="win" if i < 8 else "loss",
            timestamp=now,
        )
        db_session.add(t)
    db_session.commit()

    rm = RiskManager()
    
    # Pre-warm calibration cache to trigger adjustment
    rm._get_or_update_calibration_and_bias(db_session)
    
    # Verify that cache is not empty
    assert rm._calibration_cache is not None
    assert 20 in rm._calibration_cache
    
    # We call validate_trade for a trade in 20-25c bucket
    # Original signal_win_rate = 0.30
    # Expected error = 0.8 - 0.225 = 0.575
    # confidence = 10 / 50 = 0.20. Since confidence 0.2 < 0.3, it should not adjust.
    # Let's add 10 more trades to raise confidence to 20 / 50 = 0.4 (> 0.3)
    for i in range(10):
        t = Trade(
            market_ticker="m3",
            platform="polymarket",
            entry_price=0.21,
            settled=True,
            result="win" if i < 8 else "loss",
            timestamp=now,
        )
        db_session.add(t)
    db_session.commit()
    
    # Force re-update (clear cache timestamp to trigger recalculation)
    rm._calibration_cache_time = 0
    rm._get_or_update_calibration_and_bias(db_session)
    assert rm._calibration_cache[20]["confidence"] == 20 / 50 # 0.40
    
    # The expected adjustment:
    # error = 0.8 - 0.225 = 0.575
    # adjustment = error * confidence = 0.575 * 0.40 = 0.23 -> capped at 0.05
    # Adjusted probability should be: signal_win_rate + 0.05
    # Let's patch check_edge to verify the adjusted_win_rate passed down is indeed signal_win_rate + 0.05
    with patch.object(rm, "check_edge", return_value=10.0) as mock_check_edge:
        rm.validate_trade(
            size=10.0,
            current_exposure=0.0,
            bankroll=100.0,
            confidence=0.90,
            market_ticker="m3",
            db=db_session,
            strategy_name="hft_scalper",
            direction="yes",
            market_price=0.21,
            signal_win_rate=0.30,
        )
        
        # Verify check_edge received the adjusted win rate: 0.30 + 0.05 = 0.35
        mock_check_edge.assert_called_once()
        assert abs(mock_check_edge.call_args[1]["signal_win_rate"] - 0.35) < 1e-5


def test_longshot_bias_sizing_and_blocking(db_session):
    """Test RiskManager blocking and sizing scaling using longshot bias ratio.

    Uses mocked _get_or_update_calibration_and_bias to inject exact bias values,
    ensuring the test is fully isolated from other tests' DB state.
    """
    rm = RiskManager()

    # Case A: bias=0.5 (< 0.8) -> trade must be blocked by dynamic filter.
    # Pre-warm the cache so the static fallback rejection is bypassed.
    bias_a = {"bias": 0.5, "sample_size": 10, "expected_win_rate": 0.20, "actual_win_rate": 0.10}
    rm._longshot_bias_cache = bias_a
    with patch.object(rm, "_get_or_update_calibration_and_bias", return_value=({}, bias_a)):
        dec = rm.validate_trade(
            size=10.0,
            current_exposure=0.0,
            bankroll=100.0,
            confidence=0.90,
            market_ticker="m_longshot",
            db=db_session,
            strategy_name="longshot_bias",
            direction="yes",
            market_price=0.20,
            signal_win_rate=0.35,
        )
    assert not dec.allowed
    assert "blocked" in dec.reason

    # Case B: bias=1.0 (market priced correctly) -> allowed, size unchanged
    bias_b = {"bias": 1.0, "sample_size": 10, "expected_win_rate": 0.20, "actual_win_rate": 0.20}
    rm._longshot_bias_cache = bias_b  # pre-warm so static fallback rejection is bypassed
    with patch.object(rm, "_get_or_update_calibration_and_bias", return_value=({}, bias_b)):
        with patch.object(rm, "check_edge", return_value=10.0):
            dec = rm.validate_trade(
                size=10.0,
                current_exposure=0.0,
                bankroll=100.0,
                confidence=0.90,
                market_ticker="m_longshot",
                db=db_session,
                strategy_name="longshot_bias",
                direction="yes",
                market_price=0.20,
                signal_win_rate=0.35,
            )
    assert dec.allowed
    assert dec.adjusted_size == 10.0

    # Case C: bias=0.85 -> allowed, size scaled down by factor 0.85
    # actual_win_rate=0.17, expected=0.20 -> bias=0.17/0.20=0.85
    bias_c = {"bias": 0.85, "sample_size": 100, "expected_win_rate": 0.20, "actual_win_rate": 0.17}
    rm._longshot_bias_cache = bias_c  # pre-warm so static fallback rejection is bypassed
    with patch.object(rm, "_get_or_update_calibration_and_bias", return_value=({}, bias_c)):
        with patch.object(rm, "check_edge", return_value=10.0):
            dec = rm.validate_trade(
                size=10.0,
                current_exposure=0.0,
                bankroll=100.0,
                confidence=0.90,
                market_ticker="m_longshot",
                db=db_session,
                strategy_name="longshot_bias",
                direction="yes",
                market_price=0.20,
                signal_win_rate=0.35,
            )
    assert dec.allowed
    # size should be scaled by bias: 10.0 * 0.85 = 8.5
    assert abs(dec.adjusted_size - 8.5) < 0.1


def test_hive_partitioned_parquet_archiving(tmp_path):
    """Test file-based SQLite database archiving to hive partitioned Parquet folders and querying with DuckDB."""
    db_file = str(tmp_path / "test_app.db")
    parquet_dir = str(tmp_path / "parquet")

    # Create temporary SQLite file and schema
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY,
            market_ticker TEXT,
            direction TEXT,
            size REAL,
            entry_price REAL,
            settlement_value REAL,
            pnl REAL,
            result TEXT,
            timestamp TEXT,
            signal_id INTEGER,
            strategy TEXT
        )
    """)

    # Insert mock trades for two strategies across multiple months
    now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    prev_month = now - timedelta(days=35)

    cursor.executemany("""
        INSERT INTO trades (
            market_ticker, direction, size, entry_price, settlement_value, pnl, result, timestamp, strategy
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        ("m1", "BUY", 10.0, 0.20, 1.0, 8.0, "win", now.isoformat(), "hft_scalper"),
        ("m2", "SELL", 15.0, 0.80, 0.0, -15.0, "loss", now.isoformat(), "market_maker"),
        ("m3", "BUY", 20.0, 0.15, 1.0, 17.0, "win", prev_month.isoformat(), "hft_scalper"),
    ])
    conn.commit()
    conn.close()

    # Run partitioned archiving
    count = archive_trades_to_parquet(db_file, parquet_dir, days_back=60)
    assert count == 3

    # Verify hive partition directories exist
    # strategy=hft_scalper/year=2026/month=05/
    # strategy=hft_scalper/year=2026/month=04/
    # strategy=market_maker/year=2026/month=05/
    scalper_may = os.path.join(parquet_dir, "strategy=hft_scalper", "year=2026", "month=05")
    scalper_apr = os.path.join(parquet_dir, "strategy=hft_scalper", "year=2026", "month=04")
    mm_may = os.path.join(parquet_dir, "strategy=market_maker", "year=2026", "month=05")

    assert os.path.exists(scalper_may)
    assert os.path.exists(scalper_apr)
    assert os.path.exists(mm_may)

    # Query partitioned dataset using DuckDB
    sql = """
        SELECT strategy, year, month, COUNT(*) as trade_count, SUM(pnl) as total_pnl
        FROM {table}
        GROUP BY strategy, year, month
        ORDER BY strategy, month
    """
    results = query_parquet_analytics(parquet_dir, sql)

    assert len(results) == 3
    # Check partition columns were correctly populated and read
    assert results[0]["strategy"] == "hft_scalper"
    assert results[0]["month"] == "04"
    assert results[0]["trade_count"] == 1
    assert results[0]["total_pnl"] == 17.0

    assert results[1]["strategy"] == "hft_scalper"
    assert results[1]["month"] == "05"
    assert results[1]["trade_count"] == 1
    assert results[1]["total_pnl"] == 8.0

    assert results[2]["strategy"] == "market_maker"
    assert results[2]["month"] == "05"
    assert results[2]["trade_count"] == 1
    assert results[2]["total_pnl"] == -15.0
