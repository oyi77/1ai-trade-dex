"""Tests for backend/ai/debate_engine.py — Bull/Bear/Judge RA-CR protocol."""

import json
import pytest
from unittest.mock import patch

from backend.ai.debate_engine import (
    DebateArgument,
    DebateResult,
    _build_opening_prompt,
    _build_rebuttal_prompt,
    _build_judge_prompt,
    _parse_agent_response,
    run_debate,
    BULL,
    BEAR,
)


# ---------------------------------------------------------------------------
# _parse_agent_response
# ---------------------------------------------------------------------------


def test_parse_structured_response():
    text = (
        "PROBABILITY: 0.72\n"
        "CONFIDENCE: 0.85\n"
        "REASONING: Strong BTC momentum and institutional buying."
    )
    prob, conf, reasoning = _parse_agent_response(text)
    assert prob == pytest.approx(0.72)
    assert conf == pytest.approx(0.85)
    assert "momentum" in reasoning.lower()


def test_parse_json_response():
    data = {"probability": 0.35, "confidence": 0.9, "reasoning": "Bear case solid."}
    prob, conf, reasoning = _parse_agent_response(json.dumps(data))
    assert prob == pytest.approx(0.35)
    assert conf == pytest.approx(0.9)
    assert "bear" in reasoning.lower()


def test_parse_json_embedded_in_prose():
    data = {"probability": 0.60, "confidence": 0.7, "reasoning": "Moderate signal."}
    text = f"My analysis: {json.dumps(data)} That's my view."
    prob, conf, reasoning = _parse_agent_response(text)
    assert prob == pytest.approx(0.60)
    assert conf == pytest.approx(0.7)


def test_parse_malformed_returns_fallback():
    result = _parse_agent_response("random gibberish !@#$")
    assert result is None


def test_parse_clamps_probability_bounds():
    text = "PROBABILITY: 1.5\nCONFIDENCE: -0.3\nREASONING: test"
    prob, conf, reasoning = _parse_agent_response(text)
    assert prob <= 1.0
    assert conf >= 0.0


def test_parse_missing_confidence_defaults():
    text = "PROBABILITY: 0.45\nREASONING: No confidence given."
    prob, conf, reasoning = _parse_agent_response(text)
    assert prob == pytest.approx(0.45)
    assert conf == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def test_build_opening_prompt_contains_market_data():
    prompt = _build_opening_prompt(
        question="Will BTC hit $100k?",
        market_price=0.55,
        volume=10000.0,
        category="crypto",
        context="Price rallying",
        stance=BULL,
    )
    assert "Will BTC hit $100k?" in prompt
    assert "0.5500" in prompt
    assert "$10,000" in prompt
    assert "crypto" in prompt
    assert "Price rallying" in prompt
    assert "YES" in prompt


def test_build_opening_prompt_bear_direction():
    prompt = _build_opening_prompt(
        question="Will it rain?",
        market_price=0.3,
        volume=500.0,
        category="",
        context="",
        stance=BEAR,
    )
    assert "NO" in prompt


def test_build_rebuttal_prompt_includes_opponent():
    prompt = _build_rebuttal_prompt(
        question="Test?",
        market_price=0.5,
        stance=BULL,
        opponent_reasoning="The bear says this is unlikely.",
        round_num=2,
    )
    assert "BEAR" in prompt
    assert "Round 2" in prompt
    assert "The bear says this is unlikely." in prompt


def test_build_judge_prompt_includes_transcript():
    bull_args = [
        DebateArgument(
            stance=BULL,
            round_num=1,
            probability=0.7,
            confidence=0.8,
            reasoning="Bull reason R1",
        ),
    ]
    bear_args = [
        DebateArgument(
            stance=BEAR,
            round_num=1,
            probability=0.3,
            confidence=0.7,
            reasoning="Bear reason R1",
        ),
    ]
    prompt = _build_judge_prompt(
        question="Test market?",
        market_price=0.5,
        volume=1000.0,
        category="test",
        context="",
        bull_args=bull_args,
        bear_args=bear_args,
    )
    assert "DEBATE TRANSCRIPT" in prompt
    assert "ROUND 1" in prompt
    assert "Bull reason R1" in prompt
    assert "Bear reason R1" in prompt
    assert "Synthesize" in prompt


# ---------------------------------------------------------------------------
# run_debate — full integration (mocked LLM)
# ---------------------------------------------------------------------------


BULL_R1 = "PROBABILITY: 0.75\nCONFIDENCE: 0.8\nREASONING: Strong momentum favors YES."
BEAR_R1 = "PROBABILITY: 0.30\nCONFIDENCE: 0.7\nREASONING: Historical data says NO."
BULL_R2 = (
    "PROBABILITY: 0.70\nCONFIDENCE: 0.85\nREASONING: Bear ignores recent catalysts."
)
BEAR_R2 = "PROBABILITY: 0.35\nCONFIDENCE: 0.75\nREASONING: Bull cherry-picks data."
JUDGE_RESP = "PROBABILITY: 0.55\nCONFIDENCE: 0.80\nREASONING: Both sides have merit, slight edge to YES."


def _mock_call_agent_factory(responses: dict[str, list[str]]):
    """Create a mock that returns different responses based on role and call order."""
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
async def test_run_debate_two_rounds_with_judge():
    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1, BULL_R2, BEAR_R2],
            "judge": [JUDGE_RESP],
        }
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Will BTC close above $100k by Dec?",
            market_price=0.50,
            volume=50000.0,
            category="crypto",
            context="Recent ETF approvals",
            max_rounds=2,
        )

    assert result is not None
    assert isinstance(result, DebateResult)
    assert result.consensus_probability == pytest.approx(0.55)
    assert result.confidence == pytest.approx(0.80)
    assert "merit" in result.reasoning.lower()
    assert len(result.bull_arguments) == 2
    assert len(result.bear_arguments) == 2
    assert result.rounds_completed == 2
    assert result.market_question == "Will BTC close above $100k by Dec?"
    assert result.market_price == pytest.approx(0.50)


@pytest.mark.asyncio
async def test_run_debate_single_round():
    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [JUDGE_RESP],
        }
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Will it rain tomorrow?",
            market_price=0.40,
            volume=1000.0,
            max_rounds=1,
        )

    assert result is not None
    assert len(result.bull_arguments) == 1
    assert len(result.bear_arguments) == 1
    assert result.rounds_completed == 1


@pytest.mark.asyncio
async def test_run_debate_max_rounds_clamped():
    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1, BULL_R2, BEAR_R2],
            "judge": [JUDGE_RESP],
        }
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Test clamping?",
            market_price=0.50,
            max_rounds=10,
        )

    assert result is not None
    assert result.rounds_completed <= 2


@pytest.mark.asyncio
async def test_run_debate_both_agents_fail_returns_none():
    async def _all_fail(prompt, system, role):
        return None

    with patch("backend.ai.debate_engine._call_agent", side_effect=_all_fail):
        result = await run_debate(
            question="Will ETH flip BTC?",
            market_price=0.10,
        )

    assert result is None


@pytest.mark.asyncio
async def test_run_debate_judge_fails_uses_weighted_fallback():
    call_count = {"n": 0}

    async def _judge_fails(prompt, system, role):
        call_count["n"] += 1
        if role == "judge":
            return None
        if role == "debate_agent":
            if call_count["n"] <= 2:
                return (
                    "PROBABILITY: 0.70\nCONFIDENCE: 0.80\n"
                    "REASONING: Bull/bear argument."
                )
            return "PROBABILITY: 0.30\nCONFIDENCE: 0.60\nREASONING: Rebuttal."
        return None

    with patch("backend.ai.debate_engine._call_agent", side_effect=_judge_fails):
        result = await run_debate(
            question="Test judge failure?",
            market_price=0.50,
            max_rounds=1,
        )

    assert result is not None
    assert result.confidence == pytest.approx(0.3)
    assert "Judge unavailable" in result.reasoning
    assert 0.01 <= result.consensus_probability <= 0.99


@pytest.mark.asyncio
async def test_run_debate_one_agent_fails_still_produces_result():
    call_count = {"n": 0}

    async def _bull_only(prompt, system, role):
        call_count["n"] += 1
        if role == "judge":
            return JUDGE_RESP
        if role == "debate_agent":
            if call_count["n"] == 1:
                return BULL_R1
            return None
        return None

    with patch("backend.ai.debate_engine._call_agent", side_effect=_bull_only):
        result = await run_debate(
            question="Partial failure test?",
            market_price=0.50,
            max_rounds=1,
        )

    assert result is not None
    assert len(result.bull_arguments) >= 1 or len(result.bear_arguments) >= 1


@pytest.mark.asyncio
async def test_run_debate_consensus_probability_clamped():
    extreme_judge = "PROBABILITY: 1.5\nCONFIDENCE: 2.0\nREASONING: Extreme values."

    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [extreme_judge],
        }
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Extreme value test?",
            market_price=0.50,
            max_rounds=1,
        )

    assert result is not None
    assert 0.01 <= result.consensus_probability <= 0.99
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_run_debate_json_format_responses():
    bull_json = json.dumps(
        {"probability": 0.80, "confidence": 0.9, "reasoning": "JSON bull."}
    )
    bear_json = json.dumps(
        {"probability": 0.20, "confidence": 0.85, "reasoning": "JSON bear."}
    )
    judge_json = json.dumps(
        {"probability": 0.60, "confidence": 0.88, "reasoning": "JSON judge."}
    )

    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [bull_json, bear_json],
            "judge": [judge_json],
        }
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="JSON response test?",
            market_price=0.50,
            max_rounds=1,
        )

    assert result is not None
    assert result.consensus_probability == pytest.approx(0.60)
    assert result.confidence == pytest.approx(0.88)


@pytest.mark.asyncio
async def test_run_debate_latency_tracked():
    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [JUDGE_RESP],
        }
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Latency test?",
            market_price=0.50,
            max_rounds=1,
        )

    assert result is not None
    assert result.latency_ms >= 0.0


@pytest.mark.asyncio
async def test_run_debate_bull_bearish_consensus():
    bearish_judge = (
        "PROBABILITY: 0.15\nCONFIDENCE: 0.90\nREASONING: Bear wins decisively."
    )

    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [bearish_judge],
        }
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Bear consensus test?",
            market_price=0.50,
            max_rounds=1,
        )

    assert result is not None
    assert result.consensus_probability == pytest.approx(0.15)
    assert result.confidence == pytest.approx(0.90)


@pytest.mark.asyncio
async def test_run_debate_bullish_consensus():
    bullish_judge = (
        "PROBABILITY: 0.88\nCONFIDENCE: 0.92\nREASONING: Bull arguments dominate."
    )

    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [bullish_judge],
        }
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Bull consensus test?",
            market_price=0.50,
            max_rounds=1,
        )

    assert result is not None
    assert result.consensus_probability == pytest.approx(0.88)
    assert result.confidence == pytest.approx(0.92)


@pytest.mark.asyncio
async def test_run_debate_neutral_consensus():
    neutral_judge = (
        "PROBABILITY: 0.50\nCONFIDENCE: 0.60\nREASONING: Arguments are balanced."
    )

    mock_fn = _mock_call_agent_factory(
        {
            "debate_agent": [BULL_R1, BEAR_R1],
            "judge": [neutral_judge],
        }
    )

    with patch("backend.ai.debate_engine._call_agent", side_effect=mock_fn):
        result = await run_debate(
            question="Neutral consensus test?",
            market_price=0.50,
            max_rounds=1,
        )

    assert result is not None
    assert result.consensus_probability == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# to_transcript_dict
# ---------------------------------------------------------------------------


class TestToTranscriptDict:
    def test_basic_structure(self):
        arg = DebateArgument(
            stance="bull",
            round_num=1,
            probability=0.75,
            confidence=0.8,
            reasoning="Strong momentum",
            raw_response="PROBABILITY: 0.75\nCONFIDENCE: 0.8\nREASONING: Strong momentum",
        )
        result = DebateResult(
            consensus_probability=0.65,
            confidence=0.85,
            reasoning="Balanced view",
            bull_arguments=[arg],
            bear_arguments=[],
            judge_raw="raw judge text",
            rounds_completed=1,
            latency_ms=123.4,
            market_question="Will X happen?",
            market_price=0.60,
            data_sources=["order_book", "clob_order_book", "market_data"],
        )
        d = result.to_transcript_dict()
        assert "debate_transcript" in d
        assert "data_sources" in d
        assert "market_question" in d
        assert "market_price" in d
        transcript = d["debate_transcript"]
        assert len(transcript["bull_arguments"]) == 1
        assert transcript["bull_arguments"][0]["stance"] == "bull"
        assert transcript["bull_arguments"][0]["probability"] == 0.75
        assert transcript["rounds_completed"] == 1
        assert transcript["latency_ms"] == 123.4
        judge = transcript["judge"]
        assert judge["consensus_probability"] == 0.65
        assert judge["confidence"] == 0.85
        assert judge["raw_response"] == "raw judge text"
        assert d["data_sources"] == ["order_book", "clob_order_book", "market_data"]
        assert d["market_question"] == "Will X happen?"
        assert d["market_price"] == 0.60

    def test_empty_arguments(self):
        result = DebateResult(
            consensus_probability=0.5,
            confidence=0.5,
            reasoning="",
        )
        d = result.to_transcript_dict()
        assert d["debate_transcript"]["bull_arguments"] == []
        assert d["debate_transcript"]["bear_arguments"] == []
        assert d["data_sources"] == []

    def test_json_serializable(self):
        import json

        arg = DebateArgument(
            stance="bear",
            round_num=1,
            probability=0.3,
            confidence=0.9,
            reasoning="Weak case",
        )
        result = DebateResult(
            consensus_probability=0.4,
            confidence=0.7,
            reasoning="Judge says no",
            bull_arguments=[],
            bear_arguments=[arg],
            data_sources=["bigbrain_memory"],
        )
        serialized = json.dumps(result.to_transcript_dict())
        parsed = json.loads(serialized)
        assert parsed["data_sources"] == ["bigbrain_memory"]
