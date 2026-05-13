"""Integration tests for Ensemble signal generator and AI components.

Tests end-to-end ensemble signal combination flows:
- Multi-model signal combination (technical + AI + orderbook + data quality)
- Ensemble confidence agreement and disagreement scenarios
- Edge and signal propagation through strategy pipeline
"""

from backend.ai.ensemble import (
    EnsembleSignal,
    EnsembleSignalGenerator,
    platt_scale,
    extremize,
)


class TestEnsembleSignalIntegration:
    """Integration tests for ensemble signal generation."""

    def setup_method(self):
        self.generator = EnsembleSignalGenerator()

    def test_combine_signals_with_all_components(self):
        """Test full ensemble combination with all signal types."""
        result = self.generator.combine_signals(
            technical_prob=0.72,
            technical_conf=0.88,
            ai_prob=0.68,
            ai_confidence=0.82,
            orderbook_imbalance=0.35,
            orderbook_conf=0.75,
            wash_trade_score=25,
            market_price=0.55,
        )

        assert isinstance(result, EnsembleSignal)
        assert 0.01 <= result.combined_probability <= 0.99
        assert 0.0 <= result.confidence <= 1.0
        assert result.edge > 0.0
        assert abs(result.combined_probability - 0.55) > 0.05  # Has meaningful edge

        # All components should be in breakdown
        assert "technical" in result.component_breakdown
        assert "ai" in result.component_breakdown
        assert "orderbook" in result.component_breakdown
        assert "data_quality" in result.component_breakdown

    def test_ensemble_confidence_agreement(self):
        """Test high confidence when all signals agree."""
        result = self.generator.combine_signals(
            technical_prob=0.68,
            ai_prob=0.70,
            orderbook_imbalance=0.20,
            wash_trade_score=10,
            market_price=0.55,
        )

        assert result.confidence >= 0.65
        assert result.combined_probability > 0.55

    def test_ensemble_confidence_disagreement(self):
        """Test reduced confidence when signals disagree."""
        result = self.generator.combine_signals(
            technical_prob=0.30,
            ai_prob=0.70,
            orderbook_imbalance=0.0,
            wash_trade_score=5,
            market_price=0.50,
        )

        # Disagreement should reduce confidence
        assert result.confidence < 0.70

    def test_wash_trade_reduces_ensemble_confidence(self):
        """Test that wash trade score reduces confidence multiplier."""
        clean_result = self.generator.combine_signals(
            technical_prob=0.65,
            ai_prob=0.60,
            orderbook_imbalance=0.1,
            wash_trade_score=0,
            market_price=0.55,
        )

        wash_result = self.generator.combine_signals(
            technical_prob=0.65,
            ai_prob=0.60,
            orderbook_imbalance=0.1,
            wash_trade_score=80,
            market_price=0.55,
        )

        # Wash trade should reduce confidence
        assert wash_result.confidence < clean_result.confidence

    def test_orderbook_impact_on_combined_probability(self):
        """Test orderbook imbalance mapping to probability."""
        # Neutral orderbook
        neutral = self.generator.combine_signals(
            technical_prob=0.60,
            ai_prob=0.60,
            orderbook_imbalance=0.0,
            wash_trade_score=0,
            market_price=0.55,
        )

        # Positive imbalance
        positive = self.generator.combine_signals(
            technical_prob=0.60,
            ai_prob=0.60,
            orderbook_imbalance=0.5,
            wash_trade_score=0,
            market_price=0.55,
        )

        # Negative imbalance
        negative = self.generator.combine_signals(
            technical_prob=0.60,
            ai_prob=0.60,
            orderbook_imbalance=-0.5,
            wash_trade_score=0,
            market_price=0.55,
        )

        # Orderbook should shift probability slightly
        assert positive.combined_probability > neutral.combined_probability
        assert neutral.combined_probability > negative.combined_probability

    def test_ensemble_with_none_ai_prob(self):
        """Test ensemble when AI prob is None (AI weight redistributed)."""
        result = self.generator.combine_signals(
            technical_prob=0.68,
            ai_prob=None,
            orderbook_imbalance=0.2,
            wash_trade_score=15,
            market_price=0.55,
        )

        assert isinstance(result, EnsembleSignal)
        # AI weight should be redistributed to technical
        assert "ai" not in result.component_breakdown or result.component_breakdown.get("ai", 0) == 0

    def test_extremize_function(self):
        """Test extremize function squares probability bias."""
        # Near 0.5 should extremize
        assert extremize(0.55, factor=1.5) > 0.55
        assert extremize(0.60, factor=1.5) > 0.60

        # Near extremes should stay near extremes
        assert extremize(0.90, factor=1.5) > 0.90
        assert extremize(0.10, factor=1.5) < 0.10

    def test_platt_scale_function(self):
        """Test Platt scaling transforms raw probability."""
        assert 0.0 < platt_scale(0.0) < 1.0
        assert 0.0 < platt_scale(0.5) < 1.0
        assert 0.0 < platt_scale(1.0) < 1.0

        assert platt_scale(0.5, a=1.0, b=-0.5) >= 0.5
        assert platt_scale(0.5, a=1.0, b=0.5) > 0.5

    def test_ensemble_propagates_to_strategy(self):
        """Test ensemble result flows to strategy decision."""
        result = self.generator.combine_signals(
            technical_prob=0.72,
            ai_prob=0.68,
            orderbook_imbalance=0.3,
            wash_trade_score=10,
            market_price=0.55,
        )

        # Simulate strategy using ensemble signal
        # Strategy should act on edge and confidence
        edge_threshold = 0.05
        confidence_threshold = 0.60

        market_price = 0.55
        should_trade = (
            abs(result.combined_probability - market_price) > edge_threshold
            and result.confidence >= confidence_threshold
        )

        assert should_trade or result.confidence < confidence_threshold

    def test_ensemble_market_price_comparison(self):
        """Test ensemble edge calculation against market price."""
        result = self.generator.combine_signals(
            technical_prob=0.80,
            ai_prob=0.75,
            orderbook_imbalance=0.4,
            wash_trade_score=5,
            market_price=0.55,
        )

        # Edge should be distance from market price
        expected_edge = abs(result.combined_probability - 0.55)
        assert abs(result.edge - expected_edge) < 0.01

    def test_ensemble_data_quality_weighting(self):
        """Test data quality (wash trade) affects confidence."""
        high_quality = self.generator.combine_signals(
            technical_prob=0.65,
            ai_prob=0.60,
            orderbook_imbalance=0.1,
            wash_trade_score=5,
            market_price=0.55,
        )

        low_quality = self.generator.combine_signals(
            technical_prob=0.65,
            ai_prob=0.60,
            orderbook_imbalance=0.1,
            wash_trade_score=70,
            market_price=0.55,
        )

        # Quality factor reduces confidence
        # high_quality should have higher confidence than low_quality
        assert high_quality.confidence > low_quality.confidence


class TestEnsembleIntegrationWithStrategy:
    """Integration tests between ensemble and strategy components."""

    def setup_method(self):
        self.generator = EnsembleSignalGenerator()

    def test_ensemble_enriches_strategy_signal(self):
        """Test ensemble result enriches strategy signal with confidence."""

        signal = {
            "market_ticker": "BTC-USD",
            "direction": "up",
            "entry_price": 0.65,
            "strategy": "test_strategy",
        }

        result = self.generator.combine_signals(
            technical_prob=0.70,
            ai_prob=0.65,
            orderbook_imbalance=0.2,
            wash_trade_score=15,
            market_price=0.55,
        )

        # Enrich signal with ensemble data
        enriched_signal = {
            **signal,
            "ensemble_probability": result.combined_probability,
            "ensemble_confidence": result.confidence,
            "ensemble_edge": result.edge,
            "component_breakdown": result.component_breakdown,
        }

        assert enriched_signal["ensemble_probability"] > enriched_signal["entry_price"]
        assert enriched_signal["ensemble_confidence"] >= 0.0
        assert enriched_signal["ensemble_edge"] > 0.0


class TestEnsembleIntegrationWithOrderbook:
    """Integration tests for ensemble with orderbook data."""

    def setup_method(self):
        self.generator = EnsembleSignalGenerator()

    def test_ensemble_with_orderbook_imbalance(self):
        """Test ensemble combines orderbook imbalance correctly."""
        # Strong positive imbalance
        result_pos = self.generator.combine_signals(
            technical_prob=0.60,
            ai_prob=0.58,
            orderbook_imbalance=0.7,
            wash_trade_score=10,
            market_price=0.55,
        )

        # Strong negative imbalance
        result_neg = self.generator.combine_signals(
            technical_prob=0.60,
            ai_prob=0.58,
            orderbook_imbalance=-0.7,
            wash_trade_score=10,
            market_price=0.55,
        )

        # Orderbook should shift result
        assert result_pos.combined_probability > result_neg.combined_probability

    def test_ensemble_orderbook_weight_distribution(self):
        """Test orderbook weight is properly distributed in combination."""
        # Orderbook weight is 0.15 in default weights
        result = self.generator.combine_signals(
            technical_prob=0.5,
            ai_prob=0.5,
            orderbook_imbalance=1.0,  # Maximum positive
            wash_trade_score=0,
            market_price=0.5,
        )

        # Orderbook_prob = 0.5 + 1.0 * 0.15 = 0.65
        # Combined should reflect weighted average
        assert result.combined_probability > 0.5
