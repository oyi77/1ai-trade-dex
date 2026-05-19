"""Tests for strategy fingerprint module -- 14-dimension profiling."""

import time


from backend.strategies.fingerprint import strategy_fingerprint


def _make_positions(n, *, title="BTC up or down 5m", outcome="YES",
                    avg_price=0.55, size=10.0, pnl=5.0,
                    start_ts=None, gap_seconds=300, slug="", event_slug=""):
    """Generate n position dicts with controllable parameters."""
    base_ts = start_ts or time.time() - n * gap_seconds
    return [
        {
            "title": title,
            "outcome": outcome,
            "avgPrice": avg_price,
            "totalBought": size,
            "realizedPnl": pnl,
            "timestamp": base_ts + i * gap_seconds,
            "slug": slug,
            "eventSlug": event_slug,
        }
        for i in range(n)
    ]


# ------------------------------------------------------------------
# 1. Scalper profile: many small trades, short hold -> SCALPER
# ------------------------------------------------------------------
class TestScalperProfile:
    def test_scalper_strategy_type(self):
        positions = _make_positions(60, size=8.0, gap_seconds=120)
        fp = strategy_fingerprint(positions)
        assert fp.strategy_type == "SCALPER"

    def test_scalper_hold_style(self):
        positions = _make_positions(60, gap_seconds=120)
        fp = strategy_fingerprint(positions)
        assert fp.hold_style == "SCALPER"


# ------------------------------------------------------------------
# 2. Whale profile: few large trades -> WHALE
# ------------------------------------------------------------------
class TestWhaleProfile:
    def test_whale_strategy_type(self):
        positions = _make_positions(10, size=800.0, pnl=200.0, gap_seconds=86400)
        fp = strategy_fingerprint(positions)
        assert fp.strategy_type == "WHALE"


# ------------------------------------------------------------------
# 3. BTC specialist: 80%+ BTC trades -> primary_category="BTC_5m"
# ------------------------------------------------------------------
class TestBTCSpecialist:
    def test_primary_category_btc(self):
        # 8 BTC trades + 2 other
        btc = _make_positions(8, title="BTC up or down 5m")
        other = _make_positions(2, title="Will it rain tomorrow weather")
        fp = strategy_fingerprint(btc + other)
        assert fp.primary_category == "BTC_5m"
        assert fp.primary_category_share >= 0.8


# ------------------------------------------------------------------
# 4. Low confidence: <20 trades -> confidence < 0.5, red_flag
# ------------------------------------------------------------------
class TestLowConfidence:
    def test_low_confidence_and_red_flag(self):
        positions = _make_positions(10)
        fp = strategy_fingerprint(positions)
        assert fp.confidence < 0.5
        assert "small sample" in fp.red_flags


# ------------------------------------------------------------------
# 5. High confidence: 200+ consistent trades -> confidence > 0.8
# ------------------------------------------------------------------
class TestHighConfidence:
    def test_high_confidence(self):
        pnls = [5.0] * 120 + [-3.0] * 80
        positions = []
        base = time.time() - 200 * 600
        for i, p in enumerate(pnls):
            positions.append({
                "title": "BTC up or down 5m",
                "outcome": "YES",
                "avgPrice": 0.55,
                "totalBought": 10.0,
                "realizedPnl": p,
                "timestamp": base + i * 600,
                "slug": "btc-5m",
                "eventSlug": "btc-event",
            })
        fp = strategy_fingerprint(positions)
        assert fp.confidence > 0.8


# ------------------------------------------------------------------
# 6. All 14 dimensions produce non-null output
# ------------------------------------------------------------------
class TestNonNullOutput:
    def test_all_dimensions_populated(self):
        positions = _make_positions(50, pnl=3.0)
        fp = strategy_fingerprint(positions)

        assert fp.strategy_type is not None
        assert fp.confidence is not None
        assert fp.primary_category is not None
        assert fp.primary_category_share is not None
        assert fp.avg_position_size is not None
        assert fp.size_strategy is not None
        assert fp.win_rate is not None
        assert fp.profit_factor is not None
        assert fp.sharpe_ratio is not None
        assert fp.avg_hold_time_hours is not None
        assert fp.hold_style is not None
        assert fp.preferred_outcome is not None
        assert fp.preferred_side is not None
        assert fp.avg_price_entry is not None
        assert fp.limit_order_pct is not None
        assert fp.max_consecutive_losses is not None
        assert fp.recovery_ability is not None
        assert fp.is_replicable is not None
        assert fp.replication_difficulty is not None
        assert fp.copy_trade_suitability is not None
        assert fp.red_flags is not None
        assert fp.green_flags is not None
        assert fp.categories is not None
        assert fp.sizing_analysis is not None
        assert fp.timing_analysis is not None


# ------------------------------------------------------------------
# 7. Red flags: single +$500 trade dominates -> "lucky trade"
# ------------------------------------------------------------------
class TestLuckyTradeFlag:
    def test_lucky_trade_red_flag(self):
        positions = _make_positions(30, pnl=2.0)
        # Add one dominant winning trade
        positions.append({
            "title": "BTC up or down 5m",
            "outcome": "YES",
            "avgPrice": 0.55,
            "totalBought": 500.0,
            "realizedPnl": 600.0,
            "timestamp": time.time(),
            "slug": "btc-5m",
            "eventSlug": "btc-event",
        })
        fp = strategy_fingerprint(positions)
        assert "lucky trade" in fp.red_flags


# ------------------------------------------------------------------
# 8. Green flags: 500+ trades, 53% WR -> green_flags populated
# ------------------------------------------------------------------
class TestGreenFlags:
    def test_green_flags_large_sample_consistent_wr(self):
        pnls = [5.0] * 270 + [-4.0] * 230
        positions = []
        base = time.time() - 500 * 600
        for i, p in enumerate(pnls):
            positions.append({
                "title": "BTC up or down 5m",
                "outcome": "YES",
                "avgPrice": 0.55,
                "totalBought": 10.0,
                "realizedPnl": p,
                "timestamp": base + i * 600,
                "slug": "btc-5m",
                "eventSlug": "btc-event",
            })
        fp = strategy_fingerprint(positions)
        assert "large sample" in fp.green_flags
        assert "consistent win rate" in fp.green_flags


# ------------------------------------------------------------------
# 9. Empty positions: returns default fingerprint
# ------------------------------------------------------------------
class TestEmptyPositions:
    def test_empty_returns_default(self):
        fp = strategy_fingerprint([])
        assert fp.strategy_type == "MIXED"
        assert fp.confidence == 0.0
        assert fp.win_rate == 0.0
        assert fp.primary_category == "Other"
        assert fp.red_flags == []
        assert fp.green_flags == []
