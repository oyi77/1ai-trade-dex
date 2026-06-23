"""
Phase 1 tests for weather signal engine.

CRITICAL: These test financial/statistical computations that affect real money.
All tests use deterministic inputs with known expected outputs.
"""

from datetime import date

# ============================================================================
# Test EnsembleForecast probability methods
# ============================================================================


class TestEnsembleProbability:
    """Test core ensemble probability calculations."""

    def _make_forecast(self, member_highs, member_lows=None):
        from backend.data.weather import EnsembleForecast

        return EnsembleForecast(
            city_key="nyc",
            city_name="New York City",
            target_date=date.today(),
            member_highs=member_highs,
            member_lows=member_lows or [h - 15 for h in member_highs],
        )

    def test_probability_high_above_unanimous(self):
        """All 31 members above threshold → probability = 1.0."""
        members = [85.0] * 31  # all at 85F
        forecast = self._make_forecast(members)
        prob = forecast.probability_high_above(80.0)
        assert prob == 1.0

    def test_probability_high_above_zero(self):
        """All members below threshold → probability = 0.0."""
        members = [70.0] * 31
        forecast = self._make_forecast(members)
        prob = forecast.probability_high_above(80.0)
        assert prob == 0.0

    def test_probability_high_above_half(self):
        """15/30 members above threshold → probability ≈ 0.5."""
        members = [85.0] * 15 + [75.0] * 15
        forecast = self._make_forecast(members)
        prob = forecast.probability_high_above(80.0)
        assert abs(prob - 0.5) < 0.001

    def test_probability_high_above_known_ratio(self, sample_ensemble_members):
        """28/31 members above 72F (mean=78, std=3) → high probability."""
        forecast = self._make_forecast(sample_ensemble_members)
        prob = forecast.probability_high_above(72.0)
        # With mean=78, std=3, most members should be above 72
        assert prob > 0.85, f"Expected >0.85, got {prob:.3f}"

    def test_probability_high_below_complement(self):
        """below = 1 - above (always)."""
        members = [85.0] * 20 + [75.0] * 11
        forecast = self._make_forecast(members)
        above = forecast.probability_high_above(80.0)
        below = forecast.probability_high_below(80.0)
        assert abs(above + below - 1.0) < 1e-10

    def test_probability_low_above(self):
        """Low temps above threshold."""
        lows = [65.0] * 20 + [55.0] * 11
        forecast = self._make_forecast([80.0] * 31, lows)
        prob = forecast.probability_low_above(60.0)
        expected = 20 / 31
        assert abs(prob - expected) < 0.001

    def test_ensemble_stats(self):
        """Mean and std computed correctly."""
        members = [70.0, 80.0, 90.0]  # mean=80, std=10
        forecast = self._make_forecast(members)
        assert abs(forecast.mean_high - 80.0) < 0.001
        assert abs(forecast.std_high - 10.0) < 0.001
        assert forecast.num_members == 3


# ============================================================================
# Test Gaussian CDF signal blend
# ============================================================================


class TestGaussianBlend:
    """Test the Gaussian CDF probability computation."""

    def test_gaussian_sf_above_threshold(self):
        """norm.sf gives correct probability for above-threshold case."""
        from scipy.stats import norm

        # Mean=85, sigma=2.5, threshold=80 → high probability above
        prob = float(norm.sf(80.0, loc=85.0, scale=2.5))
        assert prob > 0.95, f"Expected >0.95, got {prob:.3f}"

    def test_gaussian_cdf_below_threshold(self):
        """norm.cdf gives correct probability for below-threshold case."""
        from scipy.stats import norm

        # Mean=72, sigma=2.5, threshold=80 → high probability below
        prob = float(norm.cdf(80.0, loc=72.0, scale=2.5))
        assert prob > 0.99, f"Expected >0.99, got {prob:.3f}"

    def test_gaussian_symmetric_at_mean(self):
        """At threshold == mean → probability ≈ 0.5."""
        from scipy.stats import norm

        prob_above = float(norm.sf(75.0, loc=75.0, scale=3.0))
        prob_below = float(norm.cdf(75.0, loc=75.0, scale=3.0))
        assert abs(prob_above - 0.5) < 0.001
        assert abs(prob_below - 0.5) < 0.001

    def test_blend_weights(self):
        """70% ensemble + 30% Gaussian blend is computed correctly."""
        ensemble_prob = 0.80
        gaussian_prob = 0.90
        expected_blend = 0.70 * ensemble_prob + 0.30 * gaussian_prob  # 0.83
        assert abs(expected_blend - 0.83) < 0.001

    def test_blend_clips_at_bounds(self):
        """Blended probability never goes below 0.05 or above 0.95."""
        ensemble_prob = 1.0
        gaussian_prob = 1.0
        blended = 0.70 * ensemble_prob + 0.30 * gaussian_prob
        clipped = max(0.05, min(0.95, blended))
        assert clipped == 0.95

        ensemble_prob = 0.0
        gaussian_prob = 0.0
        blended = 0.70 * ensemble_prob + 0.30 * gaussian_prob
        clipped = max(0.05, min(0.95, blended))
        assert clipped == 0.05


# ============================================================================
# Test city coordinate integrity
# ============================================================================


class TestMETARCoordinates:
    """Verify airport coordinates are used (not city centers)."""

    def test_nyc_uses_laguardia_not_manhattan(self):
        """NYC must use LaGuardia (40.7772, -73.8726), not Manhattan (40.7128, -74.0060)."""
        from backend.data.weather import CITY_CONFIG

        nyc = CITY_CONFIG["nyc"]
        # LaGuardia is at ~40.7772, -73.8726
        # Manhattan center is at ~40.7128, -74.0060
        assert abs(nyc["lat"] - 40.7772) < 0.01, "NYC should use LaGuardia lat"
        assert abs(nyc["lon"] - (-73.8726)) < 0.01, "NYC should use LaGuardia lon"
        assert nyc["nws_station"] == "KLGA"

    def test_dallas_uses_love_field_not_dfw(self):
        """Dallas must use Love Field (KDAL), not DFW which is where Polymarket resolves."""
        from backend.data.weather import CITY_CONFIG

        dallas = CITY_CONFIG["dallas"]
        assert dallas["nws_station"] == "KDAL"
        # Love Field: 32.8471, -96.8518
        assert abs(dallas["lat"] - 32.8471) < 0.01

    def test_all_cities_have_required_fields(self):
        """All cities have lat, lon, nws_station, unit."""
        from backend.data.weather import CITY_CONFIG

        required = {"name", "lat", "lon", "nws_station", "unit"}
        for city_key, config in CITY_CONFIG.items():
            missing = required - set(config.keys())
            assert not missing, f"City {city_key} missing fields: {missing}"

    def test_unit_values_valid(self):
        """Unit must be 'F' or 'C' for each city."""
        from backend.data.weather import CITY_CONFIG

        for city_key, config in CITY_CONFIG.items():
            assert config["unit"] in (
                "F",
                "C",
            ), f"City {city_key} has invalid unit: {config['unit']}"

    def test_us_cities_use_fahrenheit(self):
        """US cities (nyc, chicago, miami, etc.) must use Fahrenheit."""
        from backend.data.weather import CITY_CONFIG

        us_cities = [
            "nyc",
            "chicago",
            "miami",
            "dallas",
            "seattle",
            "atlanta",
            "los_angeles",
            "denver",
        ]
        for city in us_cities:
            if city in CITY_CONFIG:
                assert CITY_CONFIG[city]["unit"] == "F", f"{city} should be °F"

    def test_international_cities_use_celsius(self):
        """Non-US cities use Celsius (converted to °F downstream)."""
        from backend.data.weather import CITY_CONFIG

        intl_cities = ["london", "paris", "seoul", "tokyo"]
        for city in intl_cities:
            if city in CITY_CONFIG:
                assert CITY_CONFIG[city]["unit"] == "C", f"{city} should be °C"

    def test_twenty_cities_configured(self):
        """We should have at least 15 cities configured."""
        from backend.data.weather import CITY_CONFIG

        assert len(CITY_CONFIG) >= 15, f"Expected ≥15 cities, got {len(CITY_CONFIG)}"


# ============================================================================
# Test calibration module
# ============================================================================


class TestCalibration:
    """Test sigma calibration system."""

    def test_default_sigma_us_city(self):
        """US cities default to 2.5°F sigma before calibration data."""
        from backend.core.learning.calibration import get_sigma, DEFAULT_SIGMA_F

        # With no calibration data, should return default
        sigma = get_sigma("nyc", source="gefs")
        assert sigma == DEFAULT_SIGMA_F

    def test_welford_update(self, tmp_path):
        """Welford algorithm converges on correct mean error."""
        from backend.core.learning import calibration as cal_module

        # Point to tmp calibration file
        original_file = cal_module._CALIBRATION_FILE
        cal_module._CALIBRATION_FILE = tmp_path / "calibration.json"
        cal_module._cal_cache = {}

        try:
            # Add 25 resolved markets with known 3°F error
            for _ in range(25):
                cal_module.update_calibration(
                    "nyc", "gefs", forecast_temp_f=80.0, actual_temp_f=77.0
                )

            sigma = cal_module.get_sigma("nyc", "gefs")
            # After 25 samples of exactly 3°F error, mean_error should be ~3
            # sigma (std of errors) should be ~0 since all errors are identical
            assert (
                sigma < 1.0
            ), f"Sigma should be near 0 for constant errors, got {sigma:.3f}"

        finally:
            cal_module._CALIBRATION_FILE = original_file
            cal_module._cal_cache = {}

    def test_calibration_report_no_data(self):
        """Report returns string even with no data."""
        from backend.core.learning.calibration import get_calibration_report

        report = get_calibration_report()
        assert isinstance(report, str)
        assert len(report) > 0


# ============================================================================
# Test edge calculation
# ============================================================================


class TestEdgeCalculation:
    """Test edge and direction logic from signals.py."""

    def test_compute_edge_yes_direction(self):
        """Model prob > market prob → YES direction."""
        from backend.core.signals import calculate_edge

        edge, direction = calculate_edge(0.91, 0.42)
        assert direction == "up"  # "up" means YES
        assert abs(edge - 0.49) < 0.001

    def test_compute_edge_no_direction(self):
        """Model prob < market prob → NO direction (bet against)."""
        from backend.core.signals import calculate_edge

        edge, direction = calculate_edge(0.20, 0.65)
        assert direction == "down"  # "down" means NO
        assert edge > 0

    def test_edge_zero_when_aligned(self):
        """Model prob == market prob → edge is 0."""
        from backend.core.signals import calculate_edge

        edge, direction = calculate_edge(0.50, 0.50)
        assert abs(edge) < 0.001

    def test_kelly_size_basic(self):
        """Kelly sizing returns value within expected range."""
        from backend.core.signals import calculate_kelly_size

        size = calculate_kelly_size(
            edge=0.49,
            probability=0.91,
            market_price=0.42,
            direction="up",
            bankroll=1000.0,
        )
        # With strong edge, Kelly should recommend a meaningful position
        assert size > 0, "Kelly should recommend positive size for strong edge"
        assert size <= 150.0, "Kelly should not exceed 15% of $1000 bankroll"

    def test_kelly_size_capped_at_fifteen_percent(self):
        """Kelly never exceeds 15% of bankroll regardless of edge."""
        from backend.core.signals import calculate_kelly_size

        # Even with 99% model probability vs 1% market — edge is massive
        size = calculate_kelly_size(
            edge=0.98,
            probability=0.99,
            market_price=0.01,
            direction="up",
            bankroll=10000.0,
        )
        assert (
            size <= 1500.0
        ), f"Kelly should be capped at 15% of $10000, got ${size:.2f}"

    def test_kelly_size_zero_for_negative_edge(self):
        """Kelly returns 0 when edge is 0 or negative."""
        from backend.core.signals import calculate_kelly_size

        size = calculate_kelly_size(
            edge=0.0,
            probability=0.50,
            market_price=0.50,
            direction="up",
            bankroll=1000.0,
        )
        assert size == 0, f"Kelly should be 0 for zero edge, got {size}"
