"""Tests for backend.core.settlement.dispute_tracker."""

import pytest

from backend.core.settlement.dispute_tracker import (
    DisputeTracker,
    ResolutionRisk,
)


@pytest.fixture()
def tracker():
    return DisputeTracker()


# ---------------------------------------------------------------------------
# 1. Low-risk market: sports category, clear resolution criteria
# ---------------------------------------------------------------------------
def test_low_risk_market(tracker):
    market_data = {
        "market_id": "sports-001",
        "category": "sports",
        "resolution_criteria": "The team with the highest score at the end of 90 minutes wins.",
        "volume": 5_000.0,
        "seconds_remaining": 172_800,  # 2 days
    }
    assessment = tracker.assess_dispute_risk(market_data)
    assert assessment.risk == ResolutionRisk.LOW
    assert assessment.risk_score < 30


# ---------------------------------------------------------------------------
# 2. High-risk market: politics category with subjective keywords
# ---------------------------------------------------------------------------
def test_high_risk_market(tracker):
    market_data = {
        "market_id": "politics-999",
        "category": "politics",
        "resolution_criteria": (
            "Resolves YES if the candidate is generally considered to have "
            "substantially won the debate based on public opinion."
        ),
        "volume": 2_000_000.0,  # > $1M
        "seconds_remaining": 1_800,  # 30 min — time pressure
    }
    assessment = tracker.assess_dispute_risk(market_data)
    assert assessment.risk in (ResolutionRisk.HIGH, ResolutionRisk.VERY_HIGH)
    assert assessment.risk_score >= 50
    assert len(assessment.warnings) >= 2


# ---------------------------------------------------------------------------
# 3. Risk score is always in [0, 100] regardless of input
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "market_data",
    [
        # Minimum inputs
        {},
        # Maximum stress: every factor maxed
        {
            "market_id": "stress",
            "category": "legal",
            "resolution_criteria": (
                "likely substantially significant major generally mostly roughly "
                "approximately effectively considered deemed arguably unclear "
                "ambiguous discretion judgment opinion"
            ),
            "volume": 99_999_999.0,
            "seconds_remaining": 60,
        },
        # Negative / zero values
        {
            "market_id": "zeros",
            "category": "regulatory",
            "volume": -500,
            "seconds_remaining": 0,
        },
    ],
)
def test_risk_score_range(tracker, market_data):
    assessment = tracker.assess_dispute_risk(market_data)
    assert 0 <= assessment.risk_score <= 100
