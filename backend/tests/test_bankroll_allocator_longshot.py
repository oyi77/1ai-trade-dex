"""Unit tests for BankrollAllocator.apply_longshot_feedback.

This method adjusts strategy allocations based on detected longshot bias:
- bias > 0.05 → zero out the strategy's allocation (strong overconfidence)
- bias > 0.03 → reduce allocation by 30% (mild overconfidence)
- no bias data → return allocations unchanged
"""

from unittest.mock import MagicMock, patch

from backend.core.bankroll_allocator import BankrollAllocator

# LongshotBiasDetector is imported inside the method body via a local import,
# so patch it at its definition module, not the caller's namespace.
_DETECTOR_PATH = "backend.core.longshot_bias.LongshotBiasDetector"


class TestApplyLongshotFeedback:
    def _allocator(self) -> BankrollAllocator:
        return BankrollAllocator(ranker=MagicMock())

    def test_no_bias_data_returns_allocations_unchanged(self):
        """When the detector returns no bias, allocations pass through unmodified."""
        allocator = self._allocator()
        allocations = {"btc_oracle": 500.0, "market_maker": 1000.0}

        with patch(_DETECTOR_PATH) as MockDetector:
            MockDetector.return_value.get_category_bias.return_value = {}
            result = allocator.apply_longshot_feedback(allocations)

        assert result == allocations

    def test_strong_bias_zeroes_out_strategy(self):
        """bias > 0.05 sets the strategy's allocation to 0."""
        allocator = self._allocator()
        allocations = {"btc_oracle": 500.0, "market_maker": 1000.0}

        with patch(_DETECTOR_PATH) as MockDetector:
            MockDetector.return_value.get_category_bias.return_value = {
                "btc_oracle": 0.06  # above 0.05 threshold
            }
            result = allocator.apply_longshot_feedback(allocations)

        assert result["btc_oracle"] == 0.0
        assert result["market_maker"] == 1000.0  # unaffected strategy unchanged

    def test_mild_bias_reduces_allocation_by_30_percent(self):
        """0.03 < bias <= 0.05 reduces the strategy's allocation by 30%."""
        allocator = self._allocator()
        allocations = {"btc_oracle": 500.0, "market_maker": 1000.0}

        with patch(_DETECTOR_PATH) as MockDetector:
            MockDetector.return_value.get_category_bias.return_value = {
                "btc_oracle": 0.04  # between 0.03 and 0.05
            }
            result = allocator.apply_longshot_feedback(allocations)

        assert result["btc_oracle"] == 500.0 * 0.7
        assert result["market_maker"] == 1000.0  # unaffected strategy unchanged

    def test_detector_exception_returns_original_allocations(self):
        """If the detector raises, the original allocations are returned safely."""
        allocator = self._allocator()
        allocations = {"btc_oracle": 500.0}

        with patch(_DETECTOR_PATH) as MockDetector:
            MockDetector.return_value.get_category_bias.side_effect = RuntimeError(
                "db down"
            )
            result = allocator.apply_longshot_feedback(allocations)

        assert result == allocations
