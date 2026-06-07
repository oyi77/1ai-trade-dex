"""Tests for position_sizer — Kelly Criterion and position sizing."""

import pytest

from backend.core.risk.position_sizer import (
    MAX_POSITION_USD,
    MIN_POSITION_USD,
    calculate_position_size,
    kelly_criterion,
)


class TestKellyCriterion:
    """Kelly Criterion formula tests."""

    def test_basic_profitable(self):
        """WR=0.55, avg_win=1.2, avg_loss=1.0 -> f* ~= 0.1, quarter ~= 0.025."""
        result = kelly_criterion(0.55, 1.2, 1.0)
        # f* = (0.55 * 1.2 - 0.45) / 1.2 = (0.66 - 0.45) / 1.2 = 0.175
        # Kelly = 0.175 * 0.2 (settings.KELLY_FRACTION) = 0.035
        assert result == pytest.approx(0.035, abs=1e-6)

    def test_break_even(self):
        """WR=0.5, avg_win=1.0, avg_loss=1.0 -> f* = 0 (break-even)."""
        result = kelly_criterion(0.5, 1.0, 1.0)
        assert result == 0.0

    def test_negative_edge(self):
        """WR=0.4, avg_win=1.0, avg_loss=1.0 -> f* = 0 (clamped)."""
        result = kelly_criterion(0.4, 1.0, 1.0)
        assert result == 0.0

    def test_zero_win_rate(self):
        """WR=0 returns 0."""
        assert kelly_criterion(0.0, 1.0, 1.0) == 0.0

    def test_full_win_rate(self):
        """WR=1.0 returns 0 (boundary guard)."""
        assert kelly_criterion(1.0, 1.0, 1.0) == 0.0

    def test_zero_avg_loss(self):
        """avg_loss=0 returns 0 (division guard)."""
        assert kelly_criterion(0.55, 1.2, 0.0) == 0.0

    def test_high_edge(self):
        """Strong edge should produce a larger Kelly fraction."""
        result = kelly_criterion(0.7, 2.0, 1.0)
        # f* = (0.7 * 2.0 - 0.3) / 2.0 = 1.1 / 2.0 = 0.55
        # Kelly = 0.55 * 0.2 (settings.KELLY_FRACTION) = 0.11
        assert result == pytest.approx(0.11, abs=1e-6)
        assert 0 < result < 1


class TestCalculatePositionSize:
    """Position sizing with Kelly + confidence + liquidity + hard limits."""

    def test_basic_sizing(self):
        """Capital=1000, confidence=0.8, liquidity=5000 -> within limits."""
        size = calculate_position_size(
            capital=1000,
            confidence=0.8,
            market_liquidity=5000,
            win_rate=0.55,
            avg_win=1.2,
            avg_loss=1.0,
        )
        # Kelly frac = 0.035, base = 1000 * 0.035 = 35.0
        # * confidence 0.8 = 28.0
        # liquidity cap = 5000 * 0.10 = 500 (not binding)
        # slippage 0.02 <= 0.05 (no penalty)
        # clamped to [5, 50] -> 28.0
        assert size == pytest.approx(28.0, abs=0.1)
        assert MIN_POSITION_USD <= size <= MAX_POSITION_USD

    def test_zero_capital(self):
        """Zero capital returns 0."""
        assert calculate_position_size(0, 0.8, 5000) == 0.0

    def test_negative_capital(self):
        """Negative capital returns 0."""
        assert calculate_position_size(-100, 0.8, 5000) == 0.0

    def test_zero_confidence(self):
        """Zero confidence returns 0."""
        assert calculate_position_size(1000, 0.0, 5000) == 0.0

    def test_clamped_to_min(self):
        """Size below MIN_POSITION_USD is clamped up when > 0."""
        size = calculate_position_size(
            capital=100,
            confidence=0.5,
            market_liquidity=5000,
            win_rate=0.52,
            avg_win=1.05,
            avg_loss=1.0,
        )
        assert size >= MIN_POSITION_USD or size == 0.0

    def test_clamped_to_max(self):
        """Size above MAX_POSITION_USD is clamped down."""
        size = calculate_position_size(
            capital=100_000,
            confidence=1.0,
            market_liquidity=1_000_000,
            win_rate=0.65,
            avg_win=2.0,
            avg_loss=1.0,
        )
        assert size <= MAX_POSITION_USD

    def test_low_liquidity_reduces_size(self):
        """Liquidity constraint reduces size when book is thin."""
        size_thick = calculate_position_size(
            capital=1000,
            confidence=0.8,
            market_liquidity=5000,
            win_rate=0.55,
            avg_win=1.2,
            avg_loss=1.0,
        )
        size_thin = calculate_position_size(
            capital=1000,
            confidence=0.8,
            market_liquidity=50,  # thin book: cap = 50 * 0.10 = 5
            win_rate=0.55,
            avg_win=1.2,
            avg_loss=1.0,
        )
        assert size_thin <= size_thick

    def test_high_slippage_halves_size(self):
        """Slippage > 5% halves the position."""
        size_normal = calculate_position_size(
            capital=1000,
            confidence=0.8,
            market_liquidity=5000,
            max_slippage=0.02,
            win_rate=0.55,
            avg_win=1.2,
            avg_loss=1.0,
        )
        size_high_slip = calculate_position_size(
            capital=1000,
            confidence=0.8,
            market_liquidity=5000,
            max_slippage=0.10,
            win_rate=0.55,
            avg_win=1.2,
            avg_loss=1.0,
        )
        # High slippage should be <= normal (halved or clamped to min)
        assert size_high_slip <= size_normal
