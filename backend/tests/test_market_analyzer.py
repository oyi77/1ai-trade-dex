"""Tests for backend/ai/market_analyzer.py"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ai.market_analyzer import (
    AIAnalysis,
    _build_prompt,
    _format_research_context,
    _parse_ai_response,
    analyze_market,
    check_ai_budget,
)
from backend.research.models import ResearchItem

# ---------------------------------------------------------------------------
# _parse_ai_response tests
# ---------------------------------------------------------------------------


def test_parse_ai_response_structured():
    """Parse standard PROBABILITY/CONFIDENCE/REASONING format."""
    text = (
        "PROBABILITY: 0.65\n"
        "CONFIDENCE: 0.8\n"
        "REASONING: Strong momentum and low volatility support YES outcome."
    )
    prob, conf, reasoning = _parse_ai_response(text)
    assert prob == pytest.approx(0.65)
    assert conf == pytest.approx(0.8)
    assert "momentum" in reasoning.lower()


def test_parse_ai_response_json():
    """Parse JSON format response."""
    data = {
        "probability": 0.65,
        "confidence": 0.75,
        "reasoning": "Market fundamentals favor YES.",
    }
    text = json.dumps(data)
    prob, conf, reasoning = _parse_ai_response(text)
    assert prob == pytest.approx(0.65)
    assert conf == pytest.approx(0.75)
    assert "fundamentals" in reasoning.lower()


def test_parse_ai_response_json_embedded():
    """Parse JSON embedded in prose text."""
    data = {"probability": 0.3, "confidence": 0.9, "reasoning": "Unlikely event."}
    text = f"Here is my analysis: {json.dumps(data)} Hope that helps."
    prob, conf, reasoning = _parse_ai_response(text)
    assert prob == pytest.approx(0.3)
    assert conf == pytest.approx(0.9)


def test_parse_handles_malformed():
    """Handles garbage input gracefully — returns neutral fallback."""
    result = _parse_ai_response("lkjasldfkj 123 !!!! gibberish")
    prob, conf, reasoning = result
    # Should not raise; returns fallback probability and zero confidence
    assert isinstance(prob, float)
    assert isinstance(conf, float)
    assert 0.0 <= prob <= 1.0
    assert conf == 0.0  # parse failed sentinel


def test_parse_clamps_out_of_range_values():
    """Values outside [0,1] are clamped."""
    text = "PROBABILITY: 1.5\nCONFIDENCE: -0.2\nREASONING: test"
    prob, conf, reasoning = _parse_ai_response(text)
    assert prob == pytest.approx(1.0)
    assert conf == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# analyze_market tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_market_returns_analysis():
    """Mock AI provider, verify AIAnalysis is returned with correct fields."""
    groq_text = "PROBABILITY: 0.40\nCONFIDENCE: 0.75\nREASONING: Price action bearish."

    with (
        patch(
            "backend.ai.market_analyzer._call_groq",
            new=AsyncMock(return_value=groq_text),
        ),
        patch(
            "backend.ai.market_analyzer.check_ai_budget",
            new=AsyncMock(
                return_value={
                    "spent_today": 0.01,
                    "limit": 1.0,
                    "remaining": 0.99,
                    "can_call": True,
                }
            ),
        ),
        patch(
            "backend.ai.market_analyzer.get_ai_logger",
            return_value=MagicMock(
                get_daily_stats=MagicMock(return_value={"total_cost_usd": 0.01})
            ),
        ),
    ):
        result = await analyze_market(
            question="Will BTC close above $70k?",
            current_price=0.45,
            volume=5000.0,
            category="crypto",
            research_items=[],
        )

    assert result is not None
    assert isinstance(result, AIAnalysis)
    assert result.probability == pytest.approx(0.40)
    assert result.confidence == pytest.approx(0.75)
    assert result.provider == "groq"
    assert "bearish" in result.reasoning.lower()


@pytest.mark.asyncio
async def test_budget_exceeded_returns_none():
    """When budget is exceeded, analyze_market returns None immediately."""
    with patch(
        "backend.ai.market_analyzer.check_ai_budget",
        new=AsyncMock(
            return_value={
                "spent_today": 1.05,
                "limit": 1.0,
                "remaining": 0.0,
                "can_call": False,
            }
        ),
    ):
        result = await analyze_market(
            question="Will it rain in NYC?",
            current_price=0.5,
            volume=100.0,
            research_items=[],
        )

    assert result is None


@pytest.mark.asyncio
async def test_groq_api_error_returns_none():
    """When Groq raises / returns None, analyze_market returns None."""
    with (
        patch(
            "backend.ai.market_analyzer._call_groq", new=AsyncMock(return_value=None)
        ),
        patch(
            "backend.ai.market_analyzer.check_ai_budget",
            new=AsyncMock(
                return_value={
                    "spent_today": 0.0,
                    "limit": 1.0,
                    "remaining": 1.0,
                    "can_call": True,
                }
            ),
        ),
    ):
        result = await analyze_market(
            question="Will ETH hit $5k?",
            current_price=0.3,
            volume=200.0,
            research_items=[],
        )

    assert result is None


@pytest.mark.asyncio
async def test_escalates_to_claude_when_edge_large():
    """When Groq returns edge > 5%, Claude is called for deeper analysis."""
    # current_price=0.45, groq_prob=0.72 => edge=0.27 > 0.05 => escalate
    groq_text = "PROBABILITY: 0.72\nCONFIDENCE: 0.6\nREASONING: Strong signal."
    claude_text = (
        "PROBABILITY: 0.70\nCONFIDENCE: 0.85\nREASONING: Claude deep analysis."
    )

    budget_ok = {"spent_today": 0.01, "limit": 1.0, "remaining": 0.99, "can_call": True}

    with (
        patch(
            "backend.ai.market_analyzer._call_groq",
            new=AsyncMock(return_value=groq_text),
        ),
        patch(
            "backend.ai.market_analyzer._call_claude",
            new=AsyncMock(return_value=claude_text),
        ),
        patch(
            "backend.ai.market_analyzer.check_ai_budget",
            new=AsyncMock(return_value=budget_ok),
        ),
    ):
        result = await analyze_market(
            question="Will BTC double?",
            current_price=0.45,
            volume=9999.0,
            category="crypto",
            research_items=[],
        )

    assert result is not None
    assert result.provider == "claude"
    assert result.probability == pytest.approx(0.70)
    assert result.confidence == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# check_ai_budget tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_ai_budget_structure():
    """check_ai_budget returns required keys with correct types."""
    mock_logger = MagicMock()
    mock_logger.get_daily_stats.return_value = {"total_cost_usd": 0.25}

    with (
        patch("backend.ai.market_analyzer.get_ai_logger", return_value=mock_logger),
        patch("backend.config.settings") as mock_settings,
    ):
        mock_settings.AI_DAILY_BUDGET_USD = 1.0
        # Re-patch within module namespace
        with patch("backend.ai.market_analyzer.check_ai_budget", wraps=check_ai_budget):
            pass

    # Call with real implementation but mocked logger
    with patch("backend.ai.market_analyzer.get_ai_logger", return_value=mock_logger):
        result = await check_ai_budget()

    assert "spent_today" in result
    assert "limit" in result
    assert "remaining" in result
    assert "can_call" in result
    assert isinstance(result["can_call"], bool)
    assert result["remaining"] >= 0.0


# ---------------------------------------------------------------------------
# _format_research_context tests
# ---------------------------------------------------------------------------


def _make_research_item(title="Test", source="rss", content="Body", score=0.7):
    return ResearchItem(
        title=title,
        source=source,
        content=content,
        relevance_score=score,
        url="https://example.com",
        fingerprint="abc123",
        timestamp=datetime.now(timezone.utc),
    )


def test_format_research_context_empty():
    assert _format_research_context([]) == ""


def test_format_research_context_single_item():
    items = [
        _make_research_item(title="BTC rallies", content="Bitcoin up 10%", score=0.85)
    ]
    result = _format_research_context(items)
    assert "BTC rallies" in result
    assert "0.85" in result
    assert "Bitcoin up 10%" in result


def test_format_research_context_truncates_long_content():
    long_content = "A" * 300
    items = [_make_research_item(content=long_content)]
    result = _format_research_context(items)
    assert "..." in result
    assert len(result) < 300


def test_format_research_context_caps_at_five():
    items = [_make_research_item(title=f"Item {i}") for i in range(10)]
    result = _format_research_context(items)
    assert "Item 0" in result
    assert "Item 4" in result
    assert "Item 5" not in result


# ---------------------------------------------------------------------------
# _build_prompt research injection tests
# ---------------------------------------------------------------------------


def test_build_prompt_includes_research_context():
    prompt = _build_prompt(
        question="Will BTC hit 100k?",
        current_price=0.6,
        volume=1000,
        research_context="- [0.85] BTC surge (reuters): Bitcoin reached new highs...",
    )
    assert "RESEARCH CONTEXT" in prompt
    assert "BTC surge" in prompt
    assert "reuters" in prompt


def test_build_prompt_no_research_section_when_empty():
    prompt = _build_prompt(
        question="Will it rain?",
        current_price=0.5,
        volume=100,
        research_context="",
    )
    assert "RESEARCH CONTEXT" not in prompt


def test_build_prompt_no_research_section_by_default():
    prompt = _build_prompt(
        question="Will it rain?",
        current_price=0.5,
        volume=100,
    )
    assert "RESEARCH CONTEXT" not in prompt


# ---------------------------------------------------------------------------
# analyze_market with research context tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_market_with_explicit_research_items():
    groq_text = "PROBABILITY: 0.55\nCONFIDENCE: 0.7\nREASONING: Informed by research."
    items = [
        _make_research_item(
            title="Fed rate cut", content="Fed cuts rates by 25bp", score=0.9
        )
    ]

    with (
        patch(
            "backend.ai.market_analyzer._call_groq",
            new=AsyncMock(return_value=groq_text),
        ) as mock_groq,
        patch(
            "backend.ai.market_analyzer.check_ai_budget",
            new=AsyncMock(
                return_value={
                    "spent_today": 0.01,
                    "limit": 1.0,
                    "remaining": 0.99,
                    "can_call": True,
                }
            ),
        ),
        patch(
            "backend.ai.market_analyzer.get_ai_logger",
            return_value=MagicMock(
                get_daily_stats=MagicMock(return_value={"total_cost_usd": 0.01})
            ),
        ),
    ):
        result = await analyze_market(
            question="Will Fed cut rates?",
            current_price=0.50,
            volume=5000.0,
            research_items=items,
        )
        prompt_sent = mock_groq.call_args[0][0]

    assert result is not None
    assert "RESEARCH CONTEXT" in prompt_sent
    assert "Fed rate cut" in prompt_sent
    assert "25bp" in prompt_sent


@pytest.mark.asyncio
async def test_analyze_market_empty_research_no_crash():
    groq_text = "PROBABILITY: 0.40\nCONFIDENCE: 0.75\nREASONING: No research available."

    with (
        patch(
            "backend.ai.market_analyzer._call_groq",
            new=AsyncMock(return_value=groq_text),
        ),
        patch(
            "backend.ai.market_analyzer.check_ai_budget",
            new=AsyncMock(
                return_value={
                    "spent_today": 0.01,
                    "limit": 1.0,
                    "remaining": 0.99,
                    "can_call": True,
                }
            ),
        ),
        patch(
            "backend.ai.market_analyzer.get_ai_logger",
            return_value=MagicMock(
                get_daily_stats=MagicMock(return_value={"total_cost_usd": 0.01})
            ),
        ),
    ):
        result = await analyze_market(
            question="Random market?",
            current_price=0.45,
            volume=100.0,
            research_items=[],
        )

    assert result is not None
    assert result.probability == pytest.approx(0.40)


@pytest.mark.asyncio
async def test_analyze_market_auto_fetches_research_when_none():
    groq_text = "PROBABILITY: 0.60\nCONFIDENCE: 0.8\nREASONING: Research-informed."
    items = [
        _make_research_item(
            title="Relevant news", content="Something happened", score=0.8
        )
    ]

    mock_storage = MagicMock()
    mock_storage.get_for_market = AsyncMock(return_value=items)

    with (
        patch(
            "backend.ai.market_analyzer._call_groq",
            new=AsyncMock(return_value=groq_text),
        ) as mock_groq,
        patch(
            "backend.ai.market_analyzer.check_ai_budget",
            new=AsyncMock(
                return_value={
                    "spent_today": 0.01,
                    "limit": 1.0,
                    "remaining": 0.99,
                    "can_call": True,
                }
            ),
        ),
        patch(
            "backend.ai.market_analyzer.get_ai_logger",
            return_value=MagicMock(
                get_daily_stats=MagicMock(return_value={"total_cost_usd": 0.01})
            ),
        ),
        patch("backend.ai.market_analyzer.ResearchStorage", return_value=mock_storage),
    ):
        result = await analyze_market(
            question="Will BTC moon?",
            current_price=0.55,
            volume=3000.0,
        )
        prompt_sent = mock_groq.call_args[0][0]

    assert result is not None
    assert "Relevant news" in prompt_sent
    mock_storage.get_for_market.assert_called_once_with("Will BTC moon?", limit=5)


@pytest.mark.asyncio
async def test_analyze_market_research_fetch_failure_graceful():
    groq_text = (
        "PROBABILITY: 0.45\nCONFIDENCE: 0.6\nREASONING: Analysis without research."
    )

    with (
        patch(
            "backend.ai.market_analyzer._call_groq",
            new=AsyncMock(return_value=groq_text),
        ) as mock_groq,
        patch(
            "backend.ai.market_analyzer.check_ai_budget",
            new=AsyncMock(
                return_value={
                    "spent_today": 0.01,
                    "limit": 1.0,
                    "remaining": 0.99,
                    "can_call": True,
                }
            ),
        ),
        patch(
            "backend.ai.market_analyzer.get_ai_logger",
            return_value=MagicMock(
                get_daily_stats=MagicMock(return_value={"total_cost_usd": 0.01})
            ),
        ),
        patch(
            "backend.ai.market_analyzer.ResearchStorage",
            side_effect=RuntimeError("DB unavailable"),
        ),
        # Edge vs current_price exceeds 0.05, which triggers Claude
        # escalation — keep the test offline and deterministic.
        patch(
            "backend.ai.market_analyzer._call_claude",
            new=AsyncMock(return_value=None),
        ),
    ):
        result = await analyze_market(
            question="Will ETH flip BTC?",
            current_price=0.10,
            volume=500.0,
        )
        prompt_sent = mock_groq.call_args[0][0]

    assert result is not None
    assert "RESEARCH CONTEXT" not in prompt_sent
    assert result.probability == pytest.approx(0.45)
