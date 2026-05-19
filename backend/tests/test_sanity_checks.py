"""
Tests for backend.core.risk.sanity_checks — pre-trade market validation.
"""
import time
from backend.core.risk.sanity_checks import (
    MarketHealth,
    SourceWallet,
    quick_sanity_check,
    deep_sanity_check,
)


# ---------------------------------------------------------------------------
# quick_sanity_check tests
# ---------------------------------------------------------------------------

class TestQuickSanityCheck:
    """quick_sanity_check: market health validation."""

    def test_healthy_market_passes(self):
        """All checks pass for a well-formed active market."""
        now = time.time()
        market = MarketHealth(
            market_id="test-1",
            end_date=now + 86400,  # 24h from now
            book_depth_usd=5000,
            spread_cents=2,
            last_trade_ts=now - 60,  # 1 min ago
            yes_price=0.55,
            no_price=0.45,
        )
        ok, msg = quick_sanity_check(market)
        assert ok is True
        assert msg == "OK"

    def test_expired_market_rejected(self):
        """Market with end_date in the past is rejected."""
        now = time.time()
        market = MarketHealth(
            market_id="test-expired",
            end_date=now - 3600,  # 1 hour ago
            book_depth_usd=5000,
            spread_cents=2,
            last_trade_ts=now - 60,
            yes_price=0.99,
            no_price=0.01,
        )
        ok, msg = quick_sanity_check(market)
        assert ok is False
        assert "expired" in msg.lower() or "resolved" in msg.lower()

    def test_thin_book_rejected(self):
        """Order book depth below $100 is rejected."""
        now = time.time()
        market = MarketHealth(
            market_id="test-thin",
            end_date=now + 86400,
            book_depth_usd=50,  # below $100
            spread_cents=2,
            last_trade_ts=now - 60,
            yes_price=0.50,
            no_price=0.50,
        )
        ok, msg = quick_sanity_check(market)
        assert ok is False
        assert "thin" in msg.lower()

    def test_wide_spread_rejected(self):
        """Spread above 5 cents is rejected."""
        now = time.time()
        market = MarketHealth(
            market_id="test-spread",
            end_date=now + 86400,
            book_depth_usd=5000,
            spread_cents=8,  # > 5c
            last_trade_ts=now - 60,
            yes_price=0.55,
            no_price=0.45,
        )
        ok, msg = quick_sanity_check(market)
        assert ok is False
        assert "spread" in msg.lower() or "wide" in msg.lower()

    def test_no_recent_trades_rejected(self):
        """No trades in the last 24 hours is rejected."""
        now = time.time()
        market = MarketHealth(
            market_id="test-stale",
            end_date=now + 86400,
            book_depth_usd=5000,
            spread_cents=2,
            last_trade_ts=now - 172800,  # 48h ago
            yes_price=0.55,
            no_price=0.45,
        )
        ok, msg = quick_sanity_check(market)
        assert ok is False
        assert "trades" in msg.lower() or "24" in msg

    def test_expiring_soon_rejected(self):
        """Market expiring in less than 1 hour is rejected."""
        now = time.time()
        market = MarketHealth(
            market_id="test-expiring",
            end_date=now + 1800,  # 30 min from now
            book_depth_usd=5000,
            spread_cents=2,
            last_trade_ts=now - 60,
            yes_price=0.55,
            no_price=0.45,
        )
        ok, msg = quick_sanity_check(market)
        assert ok is False
        assert "expires" in msg.lower() or "hour" in msg.lower()

    def test_price_sum_off_rejected(self):
        """YES + NO not summing to ~1.0 is rejected."""
        now = time.time()
        market = MarketHealth(
            market_id="test-prices",
            end_date=now + 86400,
            book_depth_usd=5000,
            spread_cents=2,
            last_trade_ts=now - 60,
            yes_price=0.80,
            no_price=0.80,  # sum = 1.60, off by > 0.10
        )
        ok, msg = quick_sanity_check(market)
        assert ok is False
        assert "1.0" in msg or "sum" in msg.lower()

    def test_no_end_date_passes_expiry_check(self):
        """Market with no end_date skips expiry checks."""
        now = time.time()
        market = MarketHealth(
            market_id="test-no-end",
            end_date=None,
            book_depth_usd=5000,
            spread_cents=2,
            last_trade_ts=now - 60,
            yes_price=0.55,
            no_price=0.45,
        )
        ok, msg = quick_sanity_check(market)
        assert ok is True
        assert msg == "OK"

    def test_no_last_trade_skips_stale_check(self):
        """Market with no last_trade_ts skips stale check."""
        now = time.time()
        market = MarketHealth(
            market_id="test-no-trade",
            end_date=now + 86400,
            book_depth_usd=5000,
            spread_cents=2,
            last_trade_ts=None,
            yes_price=0.55,
            no_price=0.45,
        )
        ok, msg = quick_sanity_check(market)
        assert ok is True
        assert msg == "OK"


# ---------------------------------------------------------------------------
# deep_sanity_check tests
# ---------------------------------------------------------------------------

class TestDeepSanityCheck:
    """deep_sanity_check: source wallet validation."""

    def test_healthy_wallet_passes(self):
        """All checks pass for a well-performing wallet."""
        now = time.time()
        wallet = SourceWallet(
            wallet_address="0xabc",
            last_trade_ts=now - 86400,  # 1 day ago
            total_trades=100,
            recent_win_rate=0.60,
            historical_win_rate=0.55,
            wallet_age_days=120,
            total_pnl=500.0,
        )
        ok, issues = deep_sanity_check(wallet)
        assert ok is True
        assert issues == []

    def test_new_wallet_rejected(self):
        """Wallet younger than 30 days is flagged."""
        now = time.time()
        wallet = SourceWallet(
            wallet_address="0xnew",
            last_trade_ts=now - 86400,
            total_trades=50,
            recent_win_rate=0.60,
            historical_win_rate=0.55,
            wallet_age_days=10,  # < 30
            total_pnl=100.0,
        )
        ok, issues = deep_sanity_check(wallet)
        assert ok is False
        assert any("new" in i.lower() for i in issues)

    def test_low_win_rate_rejected(self):
        """Historical win rate below 30% is flagged."""
        now = time.time()
        wallet = SourceWallet(
            wallet_address="0xlow",
            last_trade_ts=now - 86400,
            total_trades=100,
            recent_win_rate=0.25,
            historical_win_rate=0.20,  # < 30%
            wallet_age_days=90,
            total_pnl=-50.0,
        )
        ok, issues = deep_sanity_check(wallet)
        assert ok is False
        assert any("wr" in i.lower() or "win" in i.lower() for i in issues)

    def test_inactive_wallet_rejected(self):
        """Wallet inactive for more than 7 days is flagged."""
        now = time.time()
        wallet = SourceWallet(
            wallet_address="0xinactive",
            last_trade_ts=now - 1209600,  # 14 days ago
            total_trades=100,
            recent_win_rate=0.60,
            historical_win_rate=0.55,
            wallet_age_days=90,
            total_pnl=200.0,
        )
        ok, issues = deep_sanity_check(wallet)
        assert ok is False
        assert any("inactive" in i.lower() for i in issues)

    def test_few_trades_rejected(self):
        """Wallet with fewer than 20 trades is flagged."""
        now = time.time()
        wallet = SourceWallet(
            wallet_address="0xfew",
            last_trade_ts=now - 86400,
            total_trades=5,  # < 20
            recent_win_rate=0.80,
            historical_win_rate=0.75,
            wallet_age_days=60,
            total_pnl=50.0,
        )
        ok, issues = deep_sanity_check(wallet)
        assert ok is False
        assert any("few" in i.lower() or "trades" in i.lower() for i in issues)

    def test_negative_pnl_rejected(self):
        """Wallet with PnL below -$100 is flagged."""
        now = time.time()
        wallet = SourceWallet(
            wallet_address="0xbad",
            last_trade_ts=now - 86400,
            total_trades=100,
            recent_win_rate=0.45,
            historical_win_rate=0.40,
            wallet_age_days=90,
            total_pnl=-500.0,  # < -100
        )
        ok, issues = deep_sanity_check(wallet)
        assert ok is False
        assert any("pnl" in i.lower() for i in issues)

    def test_performance_degradation_flagged(self):
        """Recent WR significantly below historical is flagged."""
        now = time.time()
        wallet = SourceWallet(
            wallet_address="0xdegrade",
            last_trade_ts=now - 86400,
            total_trades=100,  # > 50
            recent_win_rate=0.30,  # < 0.55 * 0.7 = 0.385
            historical_win_rate=0.55,
            wallet_age_days=120,
            total_pnl=100.0,
        )
        ok, issues = deep_sanity_check(wallet)
        assert ok is False
        assert any("degraded" in i.lower() for i in issues)

    def test_no_last_trade_skips_inactive_check(self):
        """Wallet with no last_trade_ts skips the inactivity check."""
        now = time.time()
        wallet = SourceWallet(
            wallet_address="0xnots",
            last_trade_ts=None,
            total_trades=100,
            recent_win_rate=0.60,
            historical_win_rate=0.55,
            wallet_age_days=120,
            total_pnl=200.0,
        )
        ok, issues = deep_sanity_check(wallet)
        assert ok is True
        assert issues == []
