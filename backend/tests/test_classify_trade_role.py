"""Unit tests for classify_trade_role in backend.core.trade_forensics.

This pure function determines whether a trade was executed as a maker or taker,
which feeds into role-based allocation adjustments in BankrollAllocator.
"""

from backend.core.trade_forensics import classify_trade_role


class TestClassifyTradeRole:
    def test_market_order_is_always_taker(self):
        """Market orders consume liquidity — always classified as taker."""
        assert classify_trade_role("market", 0.50, 0.50, None, None) == "taker"

    def test_market_order_ignores_rebate(self):
        """Market order type takes priority even when a maker rebate is present."""
        assert classify_trade_role("market", 0.50, 0.50, 0.01, None) == "taker"

    def test_positive_maker_rebate_returns_maker(self):
        """A positive maker_rebate is definitive evidence of maker execution."""
        assert classify_trade_role("limit", 0.50, 0.60, 0.005, None) == "maker"

    def test_positive_taker_fee_returns_taker(self):
        """A positive taker_fee is definitive evidence of taker execution."""
        assert classify_trade_role("limit", 0.50, 0.60, None, 0.01) == "taker"

    def test_limit_fill_within_half_percent_of_mid_is_maker(self):
        """Limit order filled within 0.5% of mid price is classified as maker."""
        mid = 0.50
        fill = mid * 1.004  # 0.4% away — inside the 0.5% threshold
        assert classify_trade_role("limit", fill, mid, None, None) == "maker"

    def test_limit_fill_outside_half_percent_of_mid_is_unknown(self):
        """Limit order filled more than 0.5% from mid cannot be classified."""
        mid = 0.50
        fill = mid * 1.01  # 1% away — outside the 0.5% threshold
        assert classify_trade_role("limit", fill, mid, None, None) == "unknown"

    def test_no_signals_returns_unknown(self):
        """With no order type, fees, or price data, classification is unknown."""
        assert classify_trade_role(None, None, None, None, None) == "unknown"

    def test_zero_maker_rebate_does_not_classify_as_maker(self):
        """A zero rebate is not a positive rebate — should not trigger maker path."""
        mid = 0.50
        fill = mid * 1.01  # outside spread threshold
        assert classify_trade_role("limit", fill, mid, 0.0, None) == "unknown"
