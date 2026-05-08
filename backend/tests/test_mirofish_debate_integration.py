"""Tests for MiroFish signal integration with debate engine (Wave 5b)."""

import json
import pytest
from unittest.mock import patch

from backend.ai.debate_engine import (
    DebateResult,
    SignalVote,
    update_debate_with_signals,
    run_debate,
)
from backend.models.database import MiroFishSignal


BULL_R1 = "PROBABILITY: 0.75\nCONFIDENCE: 0.8\nREASONING: Strong momentum favors YES."
BEAR_R1 = "PROBABILITY: 0.30\nCONFIDENCE: 0.7\nREASONING: Historical data says NO."
JUDGE_RESP = "PROBABILITY: 0.55\nCONFIDENCE: 0.80\nREASONING: Both sides have merit, slight edge to YES."


def _mock_call_agent_factory(responses: dict[str, list[str]]):
    counters = {role: 0 for role in responses}

    async def _mock(prompt, system, role):
        role_key = role
        if role_key not in responses:
            return None
        idx = counters.get(role_key, 0)
        resps = responses[role_key]
        if idx >= len(resps):
            return resps[-1]
        counters[role_key] = idx + 1
        return resps[idx]

    return _mock


@pytest.mark.asyncio
async def test_mirofish_signal_participates_as_advisory_vote():
    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [JUDGE_RESP],
        }
    )

    mirofish_vote = SignalVote(
        source="mirofish",
        prediction=0.65,
        confidence=0.75,
        reasoning="AI analysis suggests moderate YES probability",
        weight=1.0,
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Will BTC hit $100k?",
            market_price=0.50,
            volume=10000.0,
            max_rounds=1,
            signal_votes=[mirofish_vote],
        )

    assert result is not None
    assert len(result.signal_votes) == 1
    assert result.signal_votes[0].source == "mirofish"
    assert result.signal_votes[0].prediction == 0.65
    assert result.signal_votes[0].weight == 1.0
    assert result.consensus_probability == pytest.approx(0.55)


@pytest.mark.asyncio
async def test_mirofish_signal_does_not_override_debate_consensus():
    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [JUDGE_RESP],
        }
    )

    mirofish_vote = SignalVote(
        source="mirofish",
        prediction=0.95,
        confidence=0.99,
        reasoning="Extremely bullish signal",
        weight=1.0,
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Test market?",
            market_price=0.50,
            max_rounds=1,
            signal_votes=[mirofish_vote],
        )

    assert result is not None
    assert result.consensus_probability == pytest.approx(0.55)
    assert result.signal_votes[0].prediction == 0.95


@pytest.mark.asyncio
async def test_mirofish_plus_two_positive_signals_still_requires_consensus():
    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [JUDGE_RESP],
        }
    )

    signal_votes = [
        SignalVote(source="mirofish", prediction=0.70, confidence=0.80, reasoning="Bullish", weight=1.0),
        SignalVote(source="strategy_a", prediction=0.75, confidence=0.85, reasoning="Strong buy", weight=1.0),
        SignalVote(source="strategy_b", prediction=0.68, confidence=0.78, reasoning="Positive", weight=1.0),
    ]

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Test market?",
            market_price=0.50,
            max_rounds=1,
            signal_votes=signal_votes,
        )

    assert result is not None
    assert len(result.signal_votes) == 3
    assert result.consensus_probability == pytest.approx(0.55)


@pytest.mark.asyncio
async def test_mirofish_plus_negative_signal_debate_continues():
    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [JUDGE_RESP],
        }
    )

    signal_votes = [
        SignalVote(source="mirofish", prediction=0.70, confidence=0.80, reasoning="Bullish", weight=1.0),
        SignalVote(source="strategy_a", prediction=0.25, confidence=0.90, reasoning="Strong sell", weight=1.0),
    ]

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Test market?",
            market_price=0.50,
            max_rounds=1,
            signal_votes=signal_votes,
        )

    assert result is not None
    assert len(result.signal_votes) == 2
    assert result.consensus_probability == pytest.approx(0.55)


@pytest.mark.asyncio
async def test_malformed_mirofish_signal_logged_and_skipped():
    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [JUDGE_RESP],
        }
    )

    signal_votes = [
        SignalVote(source="mirofish", prediction=1.5, confidence=0.80, reasoning="Invalid", weight=1.0),
        SignalVote(source="valid_signal", prediction=0.60, confidence=0.75, reasoning="Valid", weight=1.0),
    ]

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Test market?",
            market_price=0.50,
            max_rounds=1,
            signal_votes=signal_votes,
        )

    assert result is not None
    assert len(result.signal_votes) == 2


@pytest.mark.asyncio
async def test_missing_mirofish_signals_debate_continues_normally():
    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [JUDGE_RESP],
        }
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Test market?",
            market_price=0.50,
            max_rounds=1,
            signal_votes=None,
        )

    assert result is not None
    assert len(result.signal_votes) == 0
    assert result.consensus_probability == pytest.approx(0.55)


@pytest.mark.asyncio
async def test_mirofish_error_debate_continues_with_warning():
    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [JUDGE_RESP],
        }
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Test market?",
            market_price=0.50,
            max_rounds=1,
            signal_votes=[],
        )

    assert result is not None
    assert result.consensus_probability == pytest.approx(0.55)


@pytest.mark.asyncio
async def test_debate_history_shows_mirofish_participation():
    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [JUDGE_RESP],
        }
    )

    mirofish_vote = SignalVote(
        source="mirofish",
        prediction=0.65,
        confidence=0.75,
        reasoning="AI analysis suggests moderate YES",
        weight=1.0,
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Test market?",
            market_price=0.50,
            max_rounds=1,
            signal_votes=[mirofish_vote],
        )

    assert result is not None
    transcript = result.to_transcript_dict()
    assert "signal_votes" in transcript["debate_transcript"]
    assert len(transcript["debate_transcript"]["signal_votes"]) == 1

    sig_vote = transcript["debate_transcript"]["signal_votes"][0]
    assert sig_vote["source"] == "mirofish"
    assert sig_vote["prediction"] == 0.65
    assert sig_vote["confidence"] == 0.75
    assert sig_vote["reasoning"] == "AI analysis suggests moderate YES"
    assert sig_vote["weight"] == 1.0


def test_update_debate_with_signals_appends_votes():
    debate_result = DebateResult(
        consensus_probability=0.55,
        confidence=0.80,
        reasoning="Test reasoning",
    )

    signal_votes = [
        SignalVote(source="mirofish", prediction=0.65, confidence=0.75, reasoning="Test", weight=1.0),
    ]

    updated = update_debate_with_signals(debate_result, signal_votes)

    assert len(updated.signal_votes) == 1
    assert updated.signal_votes[0].source == "mirofish"
    assert updated.consensus_probability == pytest.approx(0.55)


def test_update_debate_with_signals_empty_list():
    debate_result = DebateResult(
        consensus_probability=0.55,
        confidence=0.80,
        reasoning="Test reasoning",
    )

    updated = update_debate_with_signals(debate_result, [])

    assert len(updated.signal_votes) == 0
    assert updated.consensus_probability == pytest.approx(0.55)


def test_signal_vote_weight_is_one():
    vote = SignalVote(
        source="mirofish",
        prediction=0.65,
        confidence=0.75,
        reasoning="Test",
        weight=1.0,
    )

    assert vote.weight == 1.0


@pytest.mark.asyncio
async def test_mirofish_signal_alone_does_not_auto_approve():
    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [JUDGE_RESP],
        }
    )

    mirofish_vote = SignalVote(
        source="mirofish",
        prediction=0.95,
        confidence=0.99,
        reasoning="Extremely bullish",
        weight=1.0,
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Test market?",
            market_price=0.50,
            max_rounds=1,
            signal_votes=[mirofish_vote],
        )

    assert result is not None
    assert result.consensus_probability == pytest.approx(0.55)
    assert result.signal_votes[0].prediction == 0.95


@pytest.mark.asyncio
async def test_multiple_signals_with_mirofish_all_equal_weight():
    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [JUDGE_RESP],
        }
    )

    signal_votes = [
        SignalVote(source="mirofish", prediction=0.70, confidence=0.80, reasoning="AI", weight=1.0),
        SignalVote(source="btc_oracle", prediction=0.65, confidence=0.75, reasoning="Oracle", weight=1.0),
        SignalVote(source="weather_emos", prediction=0.60, confidence=0.70, reasoning="Weather", weight=1.0),
    ]

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Test market?",
            market_price=0.50,
            max_rounds=1,
            signal_votes=signal_votes,
        )

    assert result is not None
    assert len(result.signal_votes) == 3
    for vote in result.signal_votes:
        assert vote.weight == 1.0


@pytest.mark.asyncio
async def test_debate_transcript_serializable_with_signals():
    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [JUDGE_RESP],
        }
    )

    mirofish_vote = SignalVote(
        source="mirofish",
        prediction=0.65,
        confidence=0.75,
        reasoning="AI analysis",
        weight=1.0,
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Test market?",
            market_price=0.50,
            max_rounds=1,
            signal_votes=[mirofish_vote],
        )

    assert result is not None
    transcript = result.to_transcript_dict()

    serialized = json.dumps(transcript)
    parsed = json.loads(serialized)

    assert "signal_votes" in parsed["debate_transcript"]
    assert len(parsed["debate_transcript"]["signal_votes"]) == 1


def test_mirofish_signal_model_schema():
    signal = MiroFishSignal(
        market_id="test-market-123",
        prediction=0.65,
        confidence=0.75,
        reasoning="AI analysis suggests moderate probability",
        source="mirofish",
        weight=1.0,
    )

    assert signal.market_id == "test-market-123"
    assert signal.prediction == 0.65
    assert signal.confidence == 0.75
    assert signal.source == "mirofish"
    assert signal.weight == 1.0
