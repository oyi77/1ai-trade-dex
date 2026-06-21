"""Tests for APEX calibration tracker."""

from __future__ import annotations


from backend.core.edge.calibration_tracker import (
    CalibrationTracker,
    CalibrationBucket,
    _bucket_key,
    MAX_ADJUSTMENT_PP,
)


class TestBucketKey:
    def test_assigns_correctly(self):
        assert _bucket_key(0.82) == "0.80-0.85"

    def test_boundary_lower(self):
        assert _bucket_key(0.85) == "0.85-0.90"

    def test_boundary_upper(self):
        assert _bucket_key(0.99) == "0.95-1.00"

    def test_low_probability(self):
        assert _bucket_key(0.12) == "0.10-0.15"


class TestCalibrationBucket:
    def test_average_predicted(self):
        b = CalibrationBucket()
        b.predicted_sum = 0.82 + 0.84 + 0.86
        b.total_count = 3
        assert abs(b.average_predicted - 0.84) < 1e-6

    def test_average_predicted_zero_count(self):
        b = CalibrationBucket()
        assert b.average_predicted == 0.5  # default

    def test_realized_rate(self):
        b = CalibrationBucket()
        b.realized_count = 2
        b.total_count = 5
        assert abs(b.realized_rate - 0.4) < 1e-6

    def test_realized_rate_zero_count(self):
        b = CalibrationBucket()
        assert b.realized_rate == 0.5  # default

    def test_adjustment_zero_below_min_samples(self):
        b = CalibrationBucket()
        b.predicted_sum = 0.80 * 10
        b.realized_count = 9
        b.total_count = 10
        # Below MIN_SAMPLES_FOR_ADJUSTMENT (20)
        assert b.adjustment == 0.0

    def test_adjustment_positive_when_realized_exceeds_predicted(self):
        b = CalibrationBucket()
        b.predicted_sum = 0.80 * 25  # avg predicted = 0.80
        b.realized_count = 22  # realized rate = 0.88
        b.total_count = 25
        expected_adj = (0.88 - 0.80) * 100  # +8pp
        assert abs(b.adjustment - expected_adj) < 0.01

    def test_adjustment_negative_when_predicted_exceeds_realized(self):
        b = CalibrationBucket()
        b.predicted_sum = 0.90 * 25  # avg predicted = 0.90
        b.realized_count = 18  # realized rate = 0.72
        b.total_count = 25
        expected_adj = (0.72 - 0.90) * 100  # -18pp
        assert abs(b.adjustment - expected_adj) < 0.01

    def test_adjustment_capped_at_max(self):
        """CalibrationTracker.get_adjustment() caps at ±5pp."""
        tracker = CalibrationTracker()
        for _ in range(25):
            tracker.record_observation("weather", 0.50, realized=True)
        adj = tracker.get_adjustment("weather", 0.50)
        assert abs(adj) <= MAX_ADJUSTMENT_PP


class TestCalibrationTracker:
    def setup_method(self):
        self.tracker = CalibrationTracker()

    def test_record_observation_increments_counts(self):
        self.tracker.record_observation("weather", 0.85, realized=True)
        self.tracker.record_observation("weather", 0.85, realized=False)
        assert self.tracker.total_trades == 2

    def test_get_adjustment_zero_initially(self):
        adj = self.tracker.get_adjustment("weather", 0.85)
        assert adj == 0.0

    def test_get_adjustment_after_observations(self):
        for _ in range(25):
            self.tracker.record_observation("weather", 0.85, realized=True)
        adj = self.tracker.get_adjustment("weather", 0.85)
        assert adj > 0  # model underestimates

    def test_get_reliability_scales_with_sample_size(self):
        # Under 50 samples
        for _ in range(30):
            self.tracker.record_observation("sports", 0.80, realized=True)
        assert self.tracker.get_reliability("sports") == 0.5

        # 50-200 samples
        for _ in range(40):
            self.tracker.record_observation("sports", 0.80, realized=False)
        assert self.tracker.get_reliability("sports") == 0.75

        # 200+ samples
        for _ in range(140):
            self.tracker.record_observation("sports", 0.80, realized=True)
        assert self.tracker.get_reliability("sports") == 1.0

    def test_get_reliability_unknown_category(self):
        assert self.tracker.get_reliability("unknown") == 0.5

    def test_total_trades_property(self):
        self.tracker.record_observation("a", 0.8, realized=True)
        self.tracker.record_observation("b", 0.7, realized=False)
        assert self.tracker.total_trades == 2

    def test_different_categories_tracked_separately(self):
        self.tracker.record_observation("weather", 0.85, realized=True)
        self.tracker.record_observation("crypto", 0.85, realized=False)
        # Both should have 1 trade each
        assert self.tracker.total_trades == 2