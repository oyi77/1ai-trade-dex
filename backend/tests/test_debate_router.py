"""Tests for debate router with MiroFish fallback logic."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.orm import Session

from backend.ai.debate_router import (
    run_debate_with_routing,
    _convert_signals_to_debate_result,
)
from backend.ai.debate_engine import DebateResult, SignalVote
from backend.ai.mirofish_client import MiroFishSignal
from backend.models.database import SystemSettings


@pytest.fixture
def mock_db():
    db = MagicMock(spec=Session)
    return db


@pytest.fixture
def sample_mirofish_signals():
    return [
        MiroFishSignal(
            market_id="market_1",
            prediction=0.65,
            confidence=0.8,
            reasoning="Bullish technical indicators",
            source="mirofish_model_a",
        ),
        MiroFishSignal(
            market_id="market_1",
            prediction=0.70,
            confidence=0.75,
            reasoning="Strong momentum signals",
            source="mirofish_model_b",
        ),
    ]


@pytest.mark.asyncio
async def test_convert_signals_empty_list():
    result = _convert_signals_to_debate_result(
        signals=[],
        question="Will BTC hit $100k?",
        market_price=0.55,
        latency_ms=150.0,
    )

    assert result.consensus_probability == 0.55
    assert result.confidence == 0.0
    assert "No MiroFish signals" in result.reasoning
    assert result.market_question == "Will BTC hit $100k?"
    assert result.latency_ms == 150.0
    assert result.data_sources == ["mirofish"]


@pytest.mark.asyncio
async def test_convert_signals_single_signal():
    signals = [
        MiroFishSignal(
            market_id="m1",
            prediction=0.75,
            confidence=0.9,
            reasoning="Strong signal",
            source="model_x",
        )
    ]

    result = _convert_signals_to_debate_result(
        signals=signals,
        question="Test question",
        market_price=0.50,
        latency_ms=100.0,
    )

    assert result.consensus_probability == 0.75
    assert result.confidence == 0.9
    assert "model_x" in result.reasoning
    assert len(result.signal_votes) == 1
    assert result.signal_votes[0].prediction == 0.75


@pytest.mark.asyncio
async def test_convert_signals_weighted_consensus(sample_mirofish_signals):
    result = _convert_signals_to_debate_result(
        signals=sample_mirofish_signals,
        question="Test question",
        market_price=0.50,
        latency_ms=200.0,
    )

    expected_consensus = (0.65 * 0.8 + 0.70 * 0.75) / (0.8 + 0.75)
    expected_confidence = (0.8 * 0.8 + 0.75 * 0.75) / (0.8 + 0.75)

    assert abs(result.consensus_probability - expected_consensus) < 0.001
    assert abs(result.confidence - expected_confidence) < 0.001
    assert len(result.signal_votes) == 2
    assert "mirofish_model_a" in result.reasoning
    assert "mirofish_model_b" in result.reasoning


@pytest.mark.asyncio
async def test_routing_mirofish_disabled(mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None

    with patch("backend.ai.debate_router.run_debate") as mock_run_debate:
        mock_run_debate.return_value = DebateResult(
            consensus_probability=0.60,
            confidence=0.85,
            reasoning="Local debate result",
            market_question="Test",
            market_price=0.55,
        )

        result = await run_debate_with_routing(
            db=mock_db,
            question="Test question",
            market_price=0.55,
            volume=10000.0,
        )

        assert result is not None
        assert result.consensus_probability == 0.60
        assert result.reasoning == "Local debate result"
        mock_run_debate.assert_called_once()


@pytest.mark.asyncio
async def test_routing_mirofish_enabled_success(mock_db, sample_mirofish_signals):
    setting = SystemSettings(key="mirofish_enabled", value=True)
    mock_db.query.return_value.filter.return_value.first.return_value = setting

    with patch("backend.ai.debate_router.MiroFishClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.fetch_signals = AsyncMock(return_value=sample_mirofish_signals)

        result = await run_debate_with_routing(
            db=mock_db,
            question="Test question",
            market_price=0.55,
            volume=10000.0,
        )

        assert result is not None
        assert result.consensus_probability > 0.60
        assert "mirofish_model_a" in result.reasoning
        assert result.data_sources == ["mirofish"]
        mock_client.fetch_signals.assert_called_once_with(market="polymarket", question="Test question", market_price=0.55)


@pytest.mark.asyncio
async def test_routing_mirofish_empty_signals_fallback(mock_db):
    setting = SystemSettings(key="mirofish_enabled", value=True)
    mock_db.query.return_value.filter.return_value.first.return_value = setting

    with patch("backend.ai.debate_router.MiroFishClient") as MockClient, \
         patch("backend.ai.debate_router.run_debate") as mock_run_debate:

        mock_client = MockClient.return_value
        mock_client.fetch_signals = AsyncMock(return_value=[])

        mock_run_debate.return_value = DebateResult(
            consensus_probability=0.58,
            confidence=0.80,
            reasoning="Local fallback",
            market_question="Test",
            market_price=0.55,
        )

        result = await run_debate_with_routing(
            db=mock_db,
            question="Test question",
            market_price=0.55,
        )

        assert result is not None
        assert result.reasoning == "Local fallback"
        mock_run_debate.assert_called_once()


@pytest.mark.asyncio
async def test_routing_mirofish_exception_fallback(mock_db):
    setting = SystemSettings(key="mirofish_enabled", value=True)
    mock_db.query.return_value.filter.return_value.first.return_value = setting

    with patch("backend.ai.debate_router.MiroFishClient") as MockClient, \
         patch("backend.ai.debate_router.run_debate") as mock_run_debate:

        mock_client = MockClient.return_value
        mock_client.fetch_signals = AsyncMock(side_effect=Exception("API timeout"))

        mock_run_debate.return_value = DebateResult(
            consensus_probability=0.62,
            confidence=0.78,
            reasoning="Exception fallback",
            market_question="Test",
            market_price=0.55,
        )

        result = await run_debate_with_routing(
            db=mock_db,
            question="Test question",
            market_price=0.55,
        )

        assert result is not None
        assert result.reasoning == "Exception fallback"
        mock_run_debate.assert_called_once()


@pytest.mark.asyncio
async def test_routing_preserves_parameters(mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None

    with patch("backend.ai.debate_router.run_debate") as mock_run_debate:
        mock_run_debate.return_value = DebateResult(
            consensus_probability=0.60,
            confidence=0.85,
            reasoning="Test",
            market_question="Test",
            market_price=0.55,
        )

        signal_votes = [
            SignalVote(
                source="test",
                prediction=0.7,
                confidence=0.8,
                reasoning="test",
            )
        ]

        await run_debate_with_routing(
            db=mock_db,
            question="Test question",
            market_price=0.55,
            volume=50000.0,
            category="crypto",
            context="BTC analysis",
            max_rounds=3,
            data_sources=["coinbase", "kraken"],
            signal_votes=signal_votes,
        )

        call_kwargs = mock_run_debate.call_args.kwargs
        assert call_kwargs["question"] == "Test question"
        assert call_kwargs["market_price"] == 0.55
        assert call_kwargs["volume"] == 50000.0
        assert call_kwargs["category"] == "crypto"
        assert call_kwargs["context"] == "BTC analysis"
        assert call_kwargs["max_rounds"] == 3
        assert call_kwargs["data_sources"] == ["coinbase", "kraken"]
        assert call_kwargs["signal_votes"] == signal_votes
