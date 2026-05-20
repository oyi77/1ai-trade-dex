"""
Tests for the LearningSystem component.
"""

import pytest
from unittest.mock import MagicMock
from datetime import datetime

from backend.core.learning_system import (
    LearningSystem,
    LearningExample,
    CalibrationReport,
)


# Mock SQLAlchemy session
class MockSession:
    def __init__(self):
        self.examples = []
        self.filter_calls = []

    def __call__(self, **kwargs):
        return self

    def query(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        self.filter_calls.append((args, kwargs))
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        # Return a list of mock objects that behave like LearningExampleModel
        return [
            MockExampleModel("strat1", "mkt1", 0.7, 1.0, 0.01, 0.8, "domain1"),
            MockExampleModel("strat1", "mkt2", 0.4, 0.0, -0.005, 0.6, "domain1"),
        ]

    def add(self, obj):
        self.examples.append(obj)

    def commit(self):
        pass

    def rollback(self):
        pass


class MockExampleModel:
    def __init__(self, strategy, market, prediction, actual, pnl, confidence, domain):
        self.strategy_key = strategy
        self.market_id = market
        self.prediction = prediction
        self.actual = actual
        self.pnl = pnl
        self.confidence = confidence
        self.domain = domain
        self.timestamp = datetime.utcnow()

    def to_learning_example(self):
        return LearningExample(
            domain=self.domain,
            strategy_key=self.strategy_key,
            market_id=self.market_id,
            prediction=self.prediction,
            actual=self.actual,
            pnl=self.pnl,
            timestamp=self.timestamp,
            confidence=self.confidence,
        )


@pytest.fixture
def learning_system():
    mock_session = MockSession()
    return LearningSystem(session=mock_session)


def test_record_outcome(learning_system):
    """Test recording learning outcomes."""
    # Test valid recording
    learning_system.record_outcome(
        strategy_key="strategy1",
        market_id="market1",
        prediction=0.7,
        actual=1.0,
        pnl=0.01,
        confidence=0.8,
    )
    assert len(learning_system.session.examples) == 1

    # Test invalid confidence
    with pytest.raises(ValueError):
        learning_system.record_outcome(
            strategy_key="strategy1",
            market_id="market1",
            prediction=0.7,
            actual=1.0,
            pnl=0.01,
            confidence=1.5,
        )


def test_get_learning_examples(learning_system):
    """Test retrieving learning examples."""
    examples = learning_system.get_learning_examples("domain1")
    assert len(examples) == 2
    assert isinstance(examples[0], LearningExample)


def test_compute_calibration(learning_system):
    """Test calibration computation."""
    examples = [
        LearningExample("domain1", "s1", "m1", 0.7, 1.0, 0.01, datetime.utcnow(), 0.8),
        LearningExample("domain1", "s1", "m2", 0.4, 0.0, -0.01, datetime.utcnow(), 0.6),
        LearningExample("domain1", "s1", "m3", 0.9, 1.0, 0.02, datetime.utcnow(), 0.95),
    ]

    learning_system.get_learning_examples = lambda domain, n=100: examples
    report = learning_system.compute_calibration("domain1")

    assert isinstance(report, CalibrationReport)
    assert 0 <= report.brier_score <= 1
    assert report.accuracy == 1.0  # All 3都是对的 (0.7->1, 0.4->0, 0.9->1)
    assert len(report.bins) > 0


def test_get_learning_stats(learning_system):
    """Test statistics generation."""
    # Mock the a litte more for stats
    learning_system.session.query = MagicMock()
    learning_system.session.query.return_value.group_by.return_value.all.return_value = [
        ("domain1", 10)
    ]

    stats = learning_system.get_learning_stats()
    assert stats["total_examples"] == 10
    assert "domain1" in stats["domains"]
