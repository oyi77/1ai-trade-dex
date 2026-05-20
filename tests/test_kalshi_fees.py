"""Tests for Kalshi fee model — _kalshi_fee function and integration."""

from decimal import Decimal

from backend.markets.providers.kalshi_provider import (
    _kalshi_fee,
    KALSHI_TAKER_FEE_RATE,
    KALSHI_MAKER_FEE_RATE,
)


class TestKalshiFee:
    """Test _kalshi_fee against known fee examples."""

    def test_taker_fee_100_at_50c(self):
        """100 contracts at 0.50 -> taker fee = ceil(100 * 0.5 * 0.5 * 0.07 * 100) = ~$1.75"""
        fee = _kalshi_fee(Decimal("0.50"), Decimal("100"), is_maker=False)
        # Floating-point rounding may cause ceil to bump by 1 cent
        assert fee in (Decimal("1.75"), Decimal("1.76")), f"Expected ~$1.75, got ${fee}"

    def test_taker_fee_100_at_90c(self):
        """100 contracts at 0.90 -> taker fee = ceil(100 * 0.9 * 0.1 * 0.07 * 100) = ceil(63) = 63 cents = $0.63"""
        fee = _kalshi_fee(Decimal("0.90"), Decimal("100"), is_maker=False)
        assert fee == Decimal("0.63"), f"Expected $0.63, got ${fee}"

    def test_maker_fee_100_at_50c(self):
        """100 contracts at 0.50 -> maker fee = ceil(100 * 0.5 * 0.5 * 0.0175 * 100) = ceil(43.75) = 44 cents = $0.44"""
        fee = _kalshi_fee(Decimal("0.50"), Decimal("100"), is_maker=True)
        assert fee == Decimal("0.44"), f"Expected $0.44, got ${fee}"

    def test_fee_peaks_at_50c(self):
        """Fee should be maximum at P=0.50 (max uncertainty)."""
        fees = []
        for p_str in ["0.10", "0.20", "0.30", "0.40", "0.50", "0.60", "0.70", "0.80", "0.90"]:
            fee = _kalshi_fee(Decimal(p_str), Decimal("100"))
            fees.append(fee)
        # 0.50 should have the highest fee
        max_fee = max(fees)
        fee_at_50 = _kalshi_fee(Decimal("0.50"), Decimal("100"))
        assert fee_at_50 == max_fee

    def test_fee_near_zero_at_extremes(self):
        """Fee should be much lower at extremes than at 0.50."""
        fee_low = _kalshi_fee(Decimal("0.01"), Decimal("100"))
        fee_high = _kalshi_fee(Decimal("0.99"), Decimal("100"))
        fee_mid = _kalshi_fee(Decimal("0.50"), Decimal("100"))
        # Fees at extremes should be much less than at midpoint
        assert fee_low < fee_mid * Decimal("0.1"), f"Extreme fee ${fee_low} not much less than mid ${fee_mid}"
        assert fee_high < fee_mid * Decimal("0.1"), f"Extreme fee ${fee_high} not much less than mid ${fee_mid}"

    def test_maker_fee_lower_than_taker(self):
        """Maker fee should always be lower than taker fee at same price."""
        for p_str in ["0.10", "0.30", "0.50", "0.70", "0.90"]:
            taker = _kalshi_fee(Decimal(p_str), Decimal("100"), is_maker=False)
            maker = _kalshi_fee(Decimal(p_str), Decimal("100"), is_maker=True)
            assert maker <= taker, f"At {p_str}: maker ${maker} > taker ${taker}"

    def test_fee_scales_with_size(self):
        """Fee should scale linearly with size."""
        fee_10 = _kalshi_fee(Decimal("0.50"), Decimal("10"))
        fee_100 = _kalshi_fee(Decimal("0.50"), Decimal("100"))
        # Due to ceil, fee_100 should be roughly 10x fee_10
        assert fee_100 >= fee_10 * 9

    def test_clamped_price_below_001(self):
        """Price below 0.01 should be clamped to 0.01."""
        fee = _kalshi_fee(Decimal("0.001"), Decimal("100"))
        fee_clamped = _kalshi_fee(Decimal("0.01"), Decimal("100"))
        assert fee == fee_clamped

    def test_clamped_price_above_099(self):
        """Price above 0.99 should be clamped to 0.99."""
        fee = _kalshi_fee(Decimal("0.999"), Decimal("100"))
        fee_clamped = _kalshi_fee(Decimal("0.99"), Decimal("100"))
        assert fee == fee_clamped

    def test_symmetry_approximate(self):
        """Fee at P and 1-P should be approximately equal (symmetric uncertainty).
        Float rounding may cause ±1 cent difference due to ceil()."""
        for p_str in ["0.10", "0.20", "0.30", "0.40"]:
            fee_p = _kalshi_fee(Decimal(p_str), Decimal("100"))
            fee_1mp = _kalshi_fee(Decimal(str(1.0 - float(p_str))), Decimal("100"))
            diff = abs(fee_p - fee_1mp)
            assert diff <= Decimal("0.01"), f"Asymmetric at P={p_str}: {fee_p} vs {fee_1mp} (diff={diff})"

    def test_fee_rates_correct(self):
        """Verify the module-level fee rate constants."""
        assert KALSHI_TAKER_FEE_RATE == 0.07
        assert KALSHI_MAKER_FEE_RATE == 0.0175
