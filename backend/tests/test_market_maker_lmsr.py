import pytest
from backend.strategies.market_maker import MarketMakerStrategy


class TestLMSRSpread:
    def setup_method(self):
        self.mm = MarketMakerStrategy()

    def test_balanced_inventory(self):
        result = self.mm.lmsr_spread(5.0, 5.0)
        assert result["yes_price"] == pytest.approx(0.5, abs=0.01)
        assert result["no_price"] == pytest.approx(0.5, abs=0.01)

    def test_yes_heavy_inventory(self):
        result = self.mm.lmsr_spread(10.0, 2.0)
        assert result["yes_price"] > result["no_price"]

    def test_no_heavy_inventory(self):
        result = self.mm.lmsr_spread(2.0, 10.0)
        assert result["no_price"] > result["yes_price"]

    def test_liquidity_param_affects_spread(self):
        tight = self.mm.lmsr_spread(8.0, 2.0, liquidity_param=5.0)
        wide = self.mm.lmsr_spread(8.0, 2.0, liquidity_param=20.0)
        tight_spread = abs(tight["yes_price"] - 0.5)
        wide_spread = abs(wide["yes_price"] - 0.5)
        assert tight_spread > wide_spread

    def test_static_mode_preserves_behavior(self):
        spread = self.mm.calculate_spread(0.1, 0.5)
        assert 0.03 <= spread <= 0.18
