"""T16: Ensemble confidence agreement metric tests [#47]."""
import numpy as np
import pytest

from backend.ai.ensemble import EnsembleSignalGenerator


@pytest.fixture
def gen():
    return EnsembleSignalGenerator()


class TestAgreementConfidence:
    def test_high_agreement(self, gen):
        result = gen.combine_signals(
            technical_prob=0.70,
            ai_prob=0.70,
            orderbook_imbalance=0.0,
            market_price=0.5,
        )
        assert result.confidence > 0.8, f"Expected high confidence for agreement, got {result.confidence}"

    def test_moderate_agreement(self, gen):
        result = gen.combine_signals(
            technical_prob=0.60,
            ai_prob=0.65,
            orderbook_imbalance=0.0,
            market_price=0.5,
        )
        assert 0.5 < result.confidence <= 1.0, f"Expected moderate confidence, got {result.confidence}"

    def test_disagreement(self, gen):
        result = gen.combine_signals(
            technical_prob=0.30,
            ai_prob=0.70,
            orderbook_imbalance=0.0,
            market_price=0.5,
        )
        assert result.confidence < 0.8, f"Expected reduced confidence for disagreement, got {result.confidence}"

    def test_single_provider(self, gen):
        result = gen.combine_signals(
            technical_prob=0.65,
            orderbook_imbalance=0.0,
            market_price=0.5,
        )
        assert result.confidence >= 0.0, f"Single provider confidence should be non-negative, got {result.confidence}"

    def test_extreme_disagreement(self, gen):
        result = gen.combine_signals(
            technical_prob=0.01,
            ai_prob=0.99,
            orderbook_imbalance=0.0,
            market_price=0.5,
        )
        assert result.confidence < 0.3, f"Expected low confidence for extreme disagreement, got {result.confidence}"

    def test_combined_probability_bounded(self, gen):
        result = gen.combine_signals(
            technical_prob=0.80,
            ai_prob=0.85,
            orderbook_imbalance=0.5,
            market_price=0.5,
        )
        assert 0.01 <= result.combined_probability <= 0.99, "Probability must be clamped"

    def test_edge_computed(self, gen):
        result = gen.combine_signals(
            technical_prob=0.80,
            ai_prob=0.75,
            orderbook_imbalance=0.0,
            market_price=0.50,
        )
        assert result.edge > 0.0, "Edge should be positive when probability differs from market"

    def test_wash_trade_reduces_confidence(self, gen):
        clean = gen.combine_signals(
            technical_prob=0.70,
            ai_prob=0.70,
            orderbook_imbalance=0.0,
            wash_trade_score=0,
            market_price=0.5,
        )
        dirty = gen.combine_signals(
            technical_prob=0.70,
            ai_prob=0.70,
            orderbook_imbalance=0.0,
            wash_trade_score=50,
            market_price=0.5,
        )
        assert dirty.confidence < clean.confidence, "Wash trade should reduce confidence"
