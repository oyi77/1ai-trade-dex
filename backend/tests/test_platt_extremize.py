import pytest
from backend.ai.ensemble import platt_scale, extremize
from backend.ai.probability_utils import clamp_probability


class TestPlattScale:
    def test_identity_params(self):
        assert platt_scale(0.5, a=1.0, b=0.0) == pytest.approx(0.6225, abs=0.01)

    def test_extreme_high(self):
        result = platt_scale(0.99, a=1.0, b=0.0)
        assert result > 0.5

    def test_extreme_low(self):
        result = platt_scale(0.01, a=4.0, b=-2.0)
        assert result < 0.5

    def test_monotonic(self):
        results = [platt_scale(p / 10.0, a=1.0, b=0.0) for p in range(1, 10)]
        for i in range(len(results) - 1):
            assert results[i] < results[i + 1]


class TestExtremize:
    def test_extremize_0_5_unchanged(self):
        assert extremize(0.5, factor=1.2) == pytest.approx(0.5)

    def test_extremize_amplifies_high(self):
        result = extremize(0.7, factor=1.5)
        assert result > 0.7

    def test_extremize_amplifies_low(self):
        result = extremize(0.3, factor=1.5)
        assert result < 0.3

    def test_extremize_clamped(self):
        result = extremize(0.9, factor=3.0)
        assert result >= 0.0
        assert result <= 1.0

    def test_combined_platt_extremize(self):
        raw = 0.7
        scaled = platt_scale(raw, a=1.0, b=0.0)
        final = extremize(scaled, factor=1.2)
        assert final >= 0.0
        assert final <= 1.0
        assert final > 0.5
