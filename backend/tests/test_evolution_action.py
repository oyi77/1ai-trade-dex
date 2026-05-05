"""Tests for EvolutionAction dataclass and event publishing.

Wave 10: Evolution Scheduler — Part 9
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from backend.domain.evolution.evolution_action import EvolutionAction


def test_evolution_action_creation():
    """Test EvolutionAction dataclass creation."""
    action = EvolutionAction(
        action_type="mutation",
        genome_id="genome_123",
        strategy_name="test_strategy",
        details={"mutation_type": "random_tweak"},
        from_stage="DRAFT",
        to_stage="DRAFT"
    )
    
    assert action.action_type == "mutation"
    assert action.genome_id == "genome_123"
    assert action.strategy_name == "test_strategy"
    assert action.details == {"mutation_type": "random_tweak"}
    assert action.from_stage == "DRAFT"
    assert action.to_stage == "DRAFT"
    assert isinstance(action.timestamp, datetime)


def test_evolution_action_to_dict():
    """Test EvolutionAction.to_dict() method."""
    timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    with patch('backend.domain.evolution.evolution_action.datetime') as mock_datetime:
        mock_datetime.now.return_value = timestamp
        
        action = EvolutionAction(
            action_type="fitness_eval",
            genome_id="genome_456",
            strategy_name="fitness_test",
            details={"fitness_score": 0.85}
        )
        
        action_dict = action.to_dict()
        
        assert action_dict["action_type"] == "fitness_eval"
        assert action_dict["genome_id"] == "genome_456"
        assert action_dict["strategy_name"] == "fitness_test"
        assert action_dict["details"] == {"fitness_score": 0.85}
        assert action_dict["timestamp"] == "2024-01-01T12:00:00+00:00"
        assert action_dict["from_stage"] is None
        assert action_dict["to_stage"] is None


def test_evolution_action_defaults():
    """Test EvolutionAction with default values."""
    action = EvolutionAction(
        action_type="selection",
        genome_id="genome_789",
        strategy_name="selection_test"
    )
    
    assert action.details == {}
    assert action.from_stage is None
    assert action.to_stage is None
    assert isinstance(action.timestamp, datetime)
