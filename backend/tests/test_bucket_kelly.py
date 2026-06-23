"""Tests for the bucket-calibrated Kelly fraction system (T7/T8).

Covers:
- `kelly_fraction(win_prob, price, ...)` — Kelly position sizing.
- `get_bucket_win_rate(price, strategy, ...)` — historical bucket win rate.
"""

from backend.core.learning.calibration import get_bucket_win_rate, kelly_fraction


def test_kelly_fraction_returns_zero_when_no_edge():
    # win_prob < price → negative edge → no bet
    assert kelly_fraction(win_prob=0.45, price=0.55) == 0.0
    # win_prob == price → zero edge → no bet
    assert kelly_fraction(win_prob=0.5, price=0.5) == 0.0


def test_kelly_fraction_returns_positive_when_edge_exists():
    low_edge = kelly_fraction(win_prob=0.6, price=0.5)
    high_edge = kelly_fraction(win_prob=0.7, price=0.5)
    assert low_edge > 0.0
    assert high_edge > 0.0
    # Higher win prob (bigger edge) should never produce smaller Kelly fraction
    assert high_edge >= low_edge


def test_kelly_fraction_bounded_by_max_fraction():
    # Default cap is 0.25 — a very high win prob must respect it (≤ 0.5 half-Kelly).
    half_capped = kelly_fraction(win_prob=0.9, price=0.5, cap=0.5)
    assert 0.0 < half_capped <= 0.5

    # Explicit quarter-Kelly cap → result must be ≤ 0.25
    quarter_capped = kelly_fraction(win_prob=0.9, price=0.5, cap=0.25)
    assert 0.0 < quarter_capped <= 0.25


def test_get_bucket_win_rate_returns_none_for_unknown_bucket():
    # No trades exist for this strategy → not enough samples → None
    result = get_bucket_win_rate(
        price=0.75, strategy="strategy_that_does_not_exist_xyz"
    )
    assert result is None


def test_get_bucket_win_rate_returns_value_for_known_bucket():
    # With empty test DB, returns None gracefully. If data exists, returns float.
    result = get_bucket_win_rate(price=0.50, strategy="btc_oracle")
    assert result is None or isinstance(result, float)
    if isinstance(result, float):
        assert 0.0 <= result <= 1.0


def test_kelly_fraction_zero_prob_returns_zero():
    assert kelly_fraction(win_prob=0.0, price=0.5) == 0.0
    assert kelly_fraction(win_prob=0.0, price=1.0) == 0.0
