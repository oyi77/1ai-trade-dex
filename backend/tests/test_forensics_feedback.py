"""Tests for forensics_feedback.py - Wave 9 Meta-Learning Layer."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, Mock

from backend.application.agi.forensics_feedback import (
    ForensicsFeedbackApplicator,
    StrategyConfigMutation,
    increase_param,
    decrease_param,
    add_to_list
)
from backend.models.database import StrategyConfig


def test_increase_param():
    """Test parameter increase mutation."""
    config = MagicMock()
    config.strategy_name = "test_strategy"
    config.min_edge_threshold = 0.10
    
    mutation = increase_param(config, "min_edge_threshold", delta=0.02, max_val=0.50)
    
    assert mutation.strategy_name == "test_strategy"
    assert mutation.param == "min_edge_threshold"
    assert mutation.old_value == 0.10
    assert abs(mutation.new_value - 0.12) < 0.001
    assert mutation.reason == "increase_min_edge_threshold"


def test_decrease_param():
    """Test parameter decrease mutation."""
    config = MagicMock()
    config.strategy_name = "test_strategy"
    config.interval_seconds = 100
    
    mutation = decrease_param(config, "interval_seconds", factor=0.80, min_val=30)
    
    assert mutation.strategy_name == "test_strategy"
    assert mutation.param == "interval_seconds"
    assert mutation.old_value == 100
    assert mutation.new_value == 80
    assert mutation.reason == "decrease_interval_seconds"


def test_add_to_list():
    """Test adding value to list parameter."""
    config = MagicMock()
    config.strategy_name = "test_strategy"
    config.params = '[]'
    
    mutation = add_to_list(config, "skip_regimes", value="volatile")
    
    assert mutation.strategy_name == "test_strategy"
    assert mutation.param == "params"
    assert mutation.old_value == '[]'
    assert mutation.new_value == '["volatile"]'


def test_add_to_list_duplicate():
    """Test adding duplicate value to list."""
    config = MagicMock()
    config.strategy_name = "test_strategy"
    config.params = '["volatile"]'
    
    mutation = add_to_list(config, "skip_regimes", value="volatile")
    assert mutation is None


def test_forensics_feedback_applicator_apply_disabled():
    """Test applicator when auto-mutation is disabled."""
    applicator = ForensicsFeedbackApplicator()
    
    with patch('backend.config.settings.FORENSICS_AUTO_MUTATE', False):
        with patch('backend.application.agi.forensics_feedback.publish_event') as mock_publish:
            db = MagicMock()
            result = applicator.apply("test_strategy", "CAUSE_SLIPPAGE_HIGH", "BTC", db)
            
            assert result is None
            assert mock_publish.called
            call_args = mock_publish.call_args[0]
            assert call_args[0] == "mutation_proposed"


def test_forensics_feedback_applicator_apply_success():
    """Test successful mutation application."""
    applicator = ForensicsFeedbackApplicator()
    
    with patch('backend.config.settings.FORENSICS_AUTO_MUTATE', True):
        with patch('backend.application.agi.forensics_feedback.publish_event') as mock_publish:
            # Mock database and config
            db = MagicMock()
            config = StrategyConfig(strategy_name="test_strategy", params="[]")
            db.query.return_value.filter_by.return_value.first.return_value = config
            
            result = applicator.apply("test_strategy", "CAUSE_SLIPPAGE_HIGH", "BTC", db)
            
            assert result is not None
            assert result.strategy_name == "test_strategy"
            assert result.param == "min_edge_threshold"
            assert mock_publish.called
            call_args = mock_publish.call_args[0]
            assert call_args[0] == "strategy_param_mutated"


def test_forensics_feedback_applicator_max_mutations():
    """Test mutation limit enforcement."""
    applicator = ForensicsFeedbackApplicator()
    
    with patch('backend.config.settings.FORENSICS_AUTO_MUTATE', True):
        with patch.object(applicator, '_mutations_today', return_value=1):
            db = MagicMock()
            result = applicator.apply("test_strategy", "CAUSE_SLIPPAGE_HIGH", "BTC", db)
            
            assert result is None


def test_forensics_feedback_applicator_unknown_rule():
    """Test unknown root cause handling."""
    applicator = ForensicsFeedbackApplicator()
    
    with patch('backend.config.settings.FORENSICS_AUTO_MUTATE', True):
        db = MagicMock()
        result = applicator.apply("test_strategy", "UNKNOWN_CAUSE", "BTC", db)
        
        assert result is None
