"""Tests for performance_attributor.py - Wave 9 Meta-Learning Layer."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from backend.domain.genome.models import StrategyGenome, FitnessMetrics
from backend.application.agi.performance_attributor import (
    attribute_trade_to_chromosomes,
    evaluate_signal_quality,
    evaluate_entry_exit_timing,
    evaluate_fill_quality,
    evaluate_sizing_optimality,
    evaluate_regime_alignment
)


def create_test_genome():
    """Create a test genome for attribution testing."""
    return StrategyGenome(
        genome_id="test_genome",
        strategy_name="test_strategy",
        archetype="momentum_surfer",
        chromosomes={
            "perception": {},
            "cognition": {},
            "execution": {},
            "risk": {},
            "meta": {}
        },
        fitness_metrics=FitnessMetrics(total_capital=10000.0)
    )


def create_test_trade():
    """Create a mock trade object for testing."""
    trade = MagicMock()
    trade.edge_at_entry = 0.05
    trade.confidence = 0.8
    trade.result = "win"
    trade.filled_size = 100.0
    trade.size = 100.0
    trade.hold_time_seconds = 3600  # 1 hour
    trade.pnl = 50.0
    trade.slippage = 0.01
    return trade


def test_evaluate_signal_quality():
    """Test signal quality evaluation."""
    trade = create_test_trade()
    market_state = {}
    
    score = evaluate_signal_quality(trade, market_state)
    assert 0.0 <= score <= 1.0


def test_evaluate_entry_exit_timing():
    """Test entry/exit timing evaluation."""
    trade = create_test_trade()
    market_state = {}
    
    score = evaluate_entry_exit_timing(trade, market_state)
    assert 0.0 <= score <= 1.0


def test_evaluate_fill_quality():
    """Test fill quality evaluation."""
    trade = create_test_trade()
    
    score = evaluate_fill_quality(trade)
    assert 0.0 <= score <= 1.0


def test_evaluate_sizing_optimality():
    """Test sizing optimality evaluation."""
    trade = create_test_trade()
    genome = create_test_genome()
    
    score = evaluate_sizing_optimality(trade, genome)
    assert 0.0 <= score <= 1.0


def test_evaluate_regime_alignment():
    """Test regime alignment evaluation."""
    genome = create_test_genome()
    genome.chromosomes["meta"]["optimal_regime"] = "trending"
    
    # Test perfect match
    market_state = {"regime": "trending"}
    score = evaluate_regime_alignment(genome, market_state)
    assert score == 1.0
    
    # Test mismatch
    market_state = {"regime": "volatile"}
    score = evaluate_regime_alignment(genome, market_state)
    assert score == 0.3


def test_attribute_trade_to_chromosomes():
    """Test full attribution workflow."""
    trade = create_test_trade()
    genome = create_test_genome()
    market_state = {"regime": "trending"}
    
    with patch('backend.core.event_bus.publish_event') as mock_publish:
        attribution = attribute_trade_to_chromosomes(trade, genome, market_state)
        
        # Check attribution scores
        assert "perception" in attribution
        assert "cognition" in attribution
        assert "execution" in attribution
        assert "risk" in attribution
        assert "meta" in attribution
        
        # Check performance history tracking
        assert "perception" in genome.chromosome_performance_history
        assert len(genome.chromosome_performance_history["perception"]) == 1
        
        # Check event publishing
        assert mock_publish.call_count == 0  # No flagging with single trade


def test_chromosome_flagging():
    """Test chromosome flagging after 5 consecutive low scores."""
    trade = create_test_trade()
    genome = create_test_genome()
    market_state = {"regime": "trending"}
    
    # Set up 5 consecutive low scores for perception
    with patch('backend.application.agi.performance_attributor.evaluate_signal_quality', return_value=0.2):
        with patch('backend.application.agi.performance_attributor.publish_event') as mock_publish:
            for _ in range(5):
                attribute_trade_to_chromosomes(trade, genome, market_state)
            
            # Check flagging event
            assert mock_publish.called
            call_args = mock_publish.call_args[0]
            assert call_args[0] == "chromosome_flagged"
            assert call_args[1]["chromosome"] == "perception"
            assert call_args[1]["avg_score"] < 0.3
