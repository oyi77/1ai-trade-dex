"""Tests for the time-decay probability model."""

from __future__ import annotations



from backend.core.edge.time_decay import (
    BrownianBridge,
    TimeDecayModel,
    _norm_cdf,
    _norm_ppf,
    DEFAULT_VOLATILITY,
    MAX_BOOST_PP,
)


class TestBrownianBridge:
    def test_probability_converges_near_resolution(self):
        """As t_remaining → 0, probability should stay near p0."""
        p0 = 0.92
        result = BrownianBridge.probability_at_time(p0, t_remaining=0.001, t_total=168.0, sigma=0.02)
        assert abs(result - p0) < 0.05, f"Expected near {p0}, got {result}"

    def test_no_change_with_zero_sigma(self):
        """Zero volatility means no adjustment."""
        p0 = 0.85
        result = BrownianBridge.probability_at_time(p0, t_remaining=24.0, t_total=168.0, sigma=0.0)
        assert result == p0

    def test_zero_remaining_returns_clamped(self):
        """t_remaining=0 returns clamped p0."""
        result = BrownianBridge.probability_at_time(0.92, t_remaining=0, t_total=168.0, sigma=0.02)
        assert 0.0 <= result <= 1.0

    def test_zero_total_returns_clamped(self):
        """t_total=0 returns clamped p0."""
        result = BrownianBridge.probability_at_time(0.92, t_remaining=24.0, t_total=0, sigma=0.02)
        assert 0.0 <= result <= 1.0


class TestNormHelpers:
    def test_norm_cdf_at_zero(self):
        assert abs(_norm_cdf(0.0) - 0.5) < 1e-6

    def test_norm_cdf_symmetry(self):
        assert abs(_norm_cdf(1.0) - (1.0 - _norm_cdf(-1.0))) < 1e-6

    def test_norm_ppf_at_half(self):
        assert abs(_norm_ppf(0.5)) < 0.01

    def test_norm_ppf_inverse(self):
        """ppf(cdf(x)) ≈ x for moderate x."""
        for x in [-1.0, 0.0, 1.0]:
            assert abs(_norm_ppf(_norm_cdf(x)) - x) < 0.01


class TestTimeDecayModel:
    def setup_method(self):
        self.model = TimeDecayModel()

    def test_no_adjustment_below_min_prob(self):
        """Prob < 0.70 gets no boost."""
        result = self.model.adjust_probability(0.50, time_to_resolution_h=1.0, category="weather")
        assert result == 0.50

    def test_no_adjustment_above_max_prob(self):
        """Prob > 0.99 gets no boost."""
        result = self.model.adjust_probability(0.995, time_to_resolution_h=1.0, category="weather")
        assert result == 0.995

    def test_no_adjustment_beyond_7_days(self):
        """Time > 168h (7 days) gets no boost."""
        result = self.model.adjust_probability(0.92, time_to_resolution_h=200.0, category="weather")
        assert result == 0.92

    def test_boost_applied_for_weather_near_resolution(self):
        """Weather market with 0.92 prob, 1 day to resolution should get boost."""
        result = self.model.adjust_probability(0.92, time_to_resolution_h=24.0, category="weather")
        assert result > 0.92, f"Expected boost, got {result}"
        assert result <= 1.0

    def test_no_boost_for_crypto_beyond_1_min(self):
        """Crypto with >1 min to resolution gets no boost."""
        result = self.model.adjust_probability(0.92, time_to_resolution_h=0.5, category="crypto")
        assert result == 0.92

    def test_boost_for_crypto_under_60_seconds(self):
        """Crypto with <60s to resolution gets boost."""
        result = self.model.adjust_probability(0.92, time_to_resolution_h=0.01, category="crypto")
        assert result > 0.92

    def test_max_boost_capped(self):
        """Maximum boost should be ~3pp (0.03)."""
        result = self.model.adjust_probability(0.92, time_to_resolution_h=0.1, category="weather")
        boost = result - 0.92
        assert boost <= MAX_BOOST_PP + 0.005, f"Boost {boost} exceeds max {MAX_BOOST_PP}"

    def test_probability_clamped_to_one(self):
        """Final probability can't exceed 1.0."""
        result = self.model.adjust_probability(0.99, time_to_resolution_h=0.1, category="weather")
        assert result <= 1.0

    def test_probability_not_negative(self):
        """Final probability can't go below 0."""
        result = self.model.adjust_probability(0.70, time_to_resolution_h=0.1, category="weather")
        assert result >= 0.0

    def test_zero_time_no_crash(self):
        """t=0 doesn't crash."""
        result = self.model.adjust_probability(0.92, time_to_resolution_h=0.0, category="weather")
        assert result == 0.92

    def test_negative_time_no_crash(self):
        """Negative time treated as already resolved."""
        result = self.model.adjust_probability(0.92, time_to_resolution_h=-1.0, category="weather")
        assert result == 0.92


class TestVolatilityEstimate:
    def setup_method(self):
        self.model = TimeDecayModel()

    def test_weather(self):
        assert self.model.volatility_estimate("weather") == 0.02

    def test_politics(self):
        assert self.model.volatility_estimate("politics") == 0.02

    def test_crypto(self):
        assert self.model.volatility_estimate("crypto") == 0.15

    def test_sports(self):
        assert self.model.volatility_estimate("sports") == 0.03

    def test_unknown_uses_default(self):
        assert self.model.volatility_estimate("unknown_category") == DEFAULT_VOLATILITY

    def test_partial_match(self):
        """Partial category match works."""
        assert self.model.volatility_estimate("us-politics") == 0.02

    def test_case_insensitive(self):
        assert self.model.volatility_estimate("Weather") == 0.02
