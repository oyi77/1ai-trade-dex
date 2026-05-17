"""Tests for crypto oracle per-asset performance tracker."""
import pytest
from datetime import datetime, timezone

from backend.core.crypto_oracle_tracker import CryptoOracleTracker


@pytest.fixture
def tracker(tmp_path):
    """Create a tracker with a temp DB."""
    db_path = tmp_path / "test_perf.db"
    return CryptoOracleTracker(db_path=db_path)


def test_record_trade_stores_correctly(tracker):
    """record_trade stores data and get_asset_stats returns it."""
    now = datetime.now(timezone.utc)
    tracker.record_trade("bitcoin", "up", 0.52, 0.50, now, "win", 0.48)
    tracker.record_trade("bitcoin", "up", 0.51, 0.50, now, "loss", -0.51)
    tracker.record_trade("bitcoin", "down", 0.49, 0.50, now, "win", 0.51)

    stats = tracker.get_asset_stats("bitcoin", lookback_trades=10)
    assert stats.trade_count == 3
    assert abs(stats.win_rate - 2 / 3) < 0.01
    assert stats.avg_pnl == pytest.approx((0.48 - 0.51 + 0.51) / 3, abs=0.01)


def test_get_asset_stats_empty(tracker):
    """Empty DB returns zero stats."""
    stats = tracker.get_asset_stats("ethereum")
    assert stats.trade_count == 0
    assert stats.win_rate == 0.0
    assert stats.avg_pnl == 0.0


def test_get_asset_stats_respects_lookback(tracker):
    """get_asset_stats limits to lookback_trades."""
    now = datetime.now(timezone.utc)
    for i in range(30):
        tracker.record_trade("solana", "up", 0.52, 0.50, now, "win" if i < 25 else "loss", 0.1)

    stats_limited = tracker.get_asset_stats("solana", lookback_trades=10)
    assert stats_limited.trade_count == 10
    # Last 10 trades are all "loss" (i=25..29 are loss, but we limit to 10 from the end)
    # Actually the last 10 inserted are i=20..29, of which 20-24 are win, 25-29 are loss
    assert stats_limited.win_rate == pytest.approx(0.5, abs=0.01)


def test_get_time_stats(tracker):
    """get_time_stats groups WR by UTC hour."""
    now = datetime.now(timezone.utc)
    # 3 wins at hour 17
    for _ in range(3):
        tracker.record_trade("bitcoin", "up", 0.52, 0.50, now.replace(hour=17), "win", 0.5)
    # 1 loss at hour 17
    tracker.record_trade("bitcoin", "up", 0.52, 0.50, now.replace(hour=17), "loss", -0.5)
    # 2 wins at hour 3
    for _ in range(2):
        tracker.record_trade("bitcoin", "up", 0.52, 0.50, now.replace(hour=3), "win", 0.5)

    time_stats = tracker.get_time_stats(lookback_hours=48)
    assert 17 in time_stats
    assert time_stats[17] == pytest.approx(0.75, abs=0.01)  # 3/4
    assert 3 in time_stats
    assert time_stats[3] == pytest.approx(1.0, abs=0.01)  # 2/2


def test_get_bucket_stats(tracker):
    """get_bucket_stats groups WR by price bucket."""
    now = datetime.now(timezone.utc)
    # 50-55c bucket: 2 wins
    tracker.record_trade("bitcoin", "up", 0.52, 0.52, now, "win", 0.48)
    tracker.record_trade("bitcoin", "up", 0.53, 0.53, now, "win", 0.47)
    # 45-50c bucket: 1 win, 1 loss
    tracker.record_trade("bitcoin", "up", 0.47, 0.47, now, "win", 0.53)
    tracker.record_trade("bitcoin", "up", 0.48, 0.48, now, "loss", -0.48)
    # 55-60c bucket: 1 loss
    tracker.record_trade("bitcoin", "up", 0.57, 0.57, now, "loss", -0.57)

    bucket_stats = tracker.get_bucket_stats(lookback_trades=50)
    assert bucket_stats["50-55c"] == pytest.approx(1.0, abs=0.01)
    assert bucket_stats["45-50c"] == pytest.approx(0.5, abs=0.01)
    assert bucket_stats["55-60c"] == pytest.approx(0.0, abs=0.01)
    assert bucket_stats["40-45c"] == 0.0  # no trades


def test_detect_edge_decay_triggers(tracker):
    """detect_edge_decay returns True when WR < 55% after 20+ trades."""
    now = datetime.now(timezone.utc)
    # 10 wins, 15 losses = 40% WR, 25 trades
    for _ in range(10):
        tracker.record_trade("ethereum", "up", 0.52, 0.50, now, "win", 0.5)
    for _ in range(15):
        tracker.record_trade("ethereum", "up", 0.52, 0.50, now, "loss", -0.5)

    assert tracker.detect_edge_decay("ethereum") is True


def test_detect_edge_decay_no_trigger_high_wr(tracker):
    """detect_edge_decay returns False when WR >= 55%."""
    now = datetime.now(timezone.utc)
    # 15 wins, 5 losses = 75% WR
    for _ in range(15):
        tracker.record_trade("solana", "up", 0.52, 0.50, now, "win", 0.5)
    for _ in range(5):
        tracker.record_trade("solana", "up", 0.52, 0.50, now, "loss", -0.5)

    assert tracker.detect_edge_decay("solana") is False


def test_detect_edge_decay_no_trigger_insufficient(tracker):
    """detect_edge_decay returns False when < 20 trades regardless of WR."""
    now = datetime.now(timezone.utc)
    # 0 wins, 10 losses = 0% WR, but only 10 trades
    for _ in range(10):
        tracker.record_trade("bitcoin", "up", 0.52, 0.50, now, "loss", -0.5)

    assert tracker.detect_edge_decay("bitcoin") is False


def test_separate_assets(tracker):
    """Stats are isolated per asset."""
    now = datetime.now(timezone.utc)
    tracker.record_trade("bitcoin", "up", 0.52, 0.50, now, "win", 0.5)
    tracker.record_trade("ethereum", "up", 0.52, 0.50, now, "loss", -0.5)

    btc = tracker.get_asset_stats("bitcoin")
    eth = tracker.get_asset_stats("ethereum")
    assert btc.win_rate == 1.0
    assert eth.win_rate == 0.0
