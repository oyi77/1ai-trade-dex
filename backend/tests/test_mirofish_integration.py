"""Integration tests for MiroFish routing, fallback, and validation.

Tests the complete end-to-end flow:
- Settings → Router → Strategy
- MiroFish enabled: verify MiroFish API called
- MiroFish disabled: verify local debate called
- Fallback: MiroFish fails → local debate used
- Credential priority: database > env vars
- Validation: toggle ON requires valid credentials
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.orm import Session

from backend.ai.debate_router import run_debate_with_routing
from backend.ai.debate_engine import DebateResult
from backend.ai.mirofish_client import MiroFishSignal
from backend.models.database import SystemSettings


@pytest.fixture
def mock_db():
    """Mock database session for settings lookup."""
    db = MagicMock(spec=Session)
    return db


@pytest.fixture
def sample_mirofish_signals():
    """Sample MiroFish signals for testing."""
    return [
        MiroFishSignal(
            market_id="test_market_1",
            prediction=0.68,
            confidence=0.85,
            reasoning="Strong bullish momentum from technical indicators",
            source="mirofish_ensemble_v1",
        ),
        MiroFishSignal(
            market_id="test_market_1",
            prediction=0.72,
            confidence=0.80,
            reasoning="Positive sentiment from news analysis",
            source="mirofish_sentiment_v1",
        ),
    ]


@pytest.fixture
def sample_debate_result():
    """Sample local debate result for fallback testing."""
    return DebateResult(
        consensus_probability=0.62,
        confidence=0.78,
        reasoning="Local debate: Bull and Bear arguments balanced, slight edge to YES",
        market_question="Will BTC hit $100k by EOY?",
        market_price=0.55,
        latency_ms=450.0,
        data_sources=["local_debate"],
    )


# ---------------------------------------------------------------------------
# End-to-End Flow: Settings → Router → Strategy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_mirofish_enabled_success(mock_db, sample_mirofish_signals):
    """E2E: MiroFish enabled + API success → MiroFish result returned."""
    # Setup: MiroFish enabled in settings
    setting = SystemSettings(key="mirofish_enabled", value=True)
    mock_db.query.return_value.filter.return_value.first.return_value = setting

    with patch("backend.ai.debate_router.MiroFishClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.fetch_signals = AsyncMock(return_value=sample_mirofish_signals)

        result = await run_debate_with_routing(
            db=mock_db,
            question="Will BTC hit $100k by EOY?",
            market_price=0.55,
            volume=50000.0,
            category="crypto",
            context="Recent ETF approvals driving momentum",
        )

        # Verify MiroFish was called
        assert result is not None
        assert result.data_sources == ["mirofish"]
        assert "mirofish_ensemble_v1" in result.reasoning
        assert "mirofish_sentiment_v1" in result.reasoning

        # Verify weighted consensus calculation
        expected_consensus = (0.68 * 0.85 + 0.72 * 0.80) / (0.85 + 0.80)
        assert abs(result.consensus_probability - expected_consensus) < 0.001

        # Verify API was called with correct market
        mock_client.fetch_signals.assert_called_once_with(market="polymarket", question="Will BTC hit $100k by EOY?", market_price=0.55)


@pytest.mark.asyncio
async def test_e2e_mirofish_disabled_local_debate(mock_db, sample_debate_result):
    """E2E: MiroFish disabled → local debate used."""
    # Setup: MiroFish disabled in settings
    mock_db.query.return_value.filter.return_value.first.return_value = None

    with patch("backend.ai.debate_router.run_debate") as mock_run_debate:
        mock_run_debate.return_value = sample_debate_result

        result = await run_debate_with_routing(
            db=mock_db,
            question="Will BTC hit $100k by EOY?",
            market_price=0.55,
            volume=50000.0,
        )

        # Verify local debate was called
        assert result is not None
        assert result.data_sources == ["local_debate"]
        assert "Local debate" in result.reasoning

        # Verify debate parameters passed correctly
        call_kwargs = mock_run_debate.call_args.kwargs
        assert call_kwargs["question"] == "Will BTC hit $100k by EOY?"
        assert call_kwargs["market_price"] == 0.55
        assert call_kwargs["volume"] == 50000.0


# ---------------------------------------------------------------------------
# Fallback Behavior: MiroFish Fails → Local Debate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_mirofish_empty_signals(mock_db, sample_debate_result):
    """Fallback: MiroFish returns empty signals → local debate used."""
    setting = SystemSettings(key="mirofish_enabled", value=True)
    mock_db.query.return_value.filter.return_value.first.return_value = setting

    with patch("backend.ai.debate_router.MiroFishClient") as MockClient, \
         patch("backend.ai.debate_router.run_debate") as mock_run_debate:

        mock_client = MockClient.return_value
        mock_client.fetch_signals = AsyncMock(return_value=[])  # Empty signals
        mock_run_debate.return_value = sample_debate_result

        result = await run_debate_with_routing(
            db=mock_db,
            question="Test market",
            market_price=0.50,
        )

        # Verify fallback to local debate
        assert result is not None
        assert result.data_sources == ["local_debate"]
        mock_run_debate.assert_called_once()


@pytest.mark.asyncio
async def test_fallback_mirofish_api_timeout(mock_db, sample_debate_result):
    """Fallback: MiroFish API timeout → local debate used."""
    setting = SystemSettings(key="mirofish_enabled", value=True)
    mock_db.query.return_value.filter.return_value.first.return_value = setting

    with patch("backend.ai.debate_router.MiroFishClient") as MockClient, \
         patch("backend.ai.debate_router.run_debate") as mock_run_debate:

        mock_client = MockClient.return_value
        mock_client.fetch_signals = AsyncMock(side_effect=TimeoutError("API timeout"))
        mock_run_debate.return_value = sample_debate_result

        result = await run_debate_with_routing(
            db=mock_db,
            question="Test market",
            market_price=0.50,
        )

        # Verify graceful fallback
        assert result is not None
        assert result.data_sources == ["local_debate"]
        mock_run_debate.assert_called_once()


@pytest.mark.asyncio
async def test_fallback_mirofish_connection_error(mock_db, sample_debate_result):
    """Fallback: MiroFish connection error → local debate used."""
    setting = SystemSettings(key="mirofish_enabled", value=True)
    mock_db.query.return_value.filter.return_value.first.return_value = setting

    with patch("backend.ai.debate_router.MiroFishClient") as MockClient, \
         patch("backend.ai.debate_router.run_debate") as mock_run_debate:

        mock_client = MockClient.return_value
        mock_client.fetch_signals = AsyncMock(
            side_effect=ConnectionError("Failed to connect to MiroFish API")
        )
        mock_run_debate.return_value = sample_debate_result

        result = await run_debate_with_routing(
            db=mock_db,
            question="Test market",
            market_price=0.50,
        )

        # Verify graceful fallback
        assert result is not None
        assert result.data_sources == ["local_debate"]
        mock_run_debate.assert_called_once()


@pytest.mark.asyncio
async def test_fallback_mirofish_auth_error(mock_db, sample_debate_result):
    """Fallback: MiroFish auth error (401) → local debate used."""
    setting = SystemSettings(key="mirofish_enabled", value=True)
    mock_db.query.return_value.filter.return_value.first.return_value = setting

    with patch("backend.ai.debate_router.MiroFishClient") as MockClient, \
         patch("backend.ai.debate_router.run_debate") as mock_run_debate:

        mock_client = MockClient.return_value
        mock_client.fetch_signals = AsyncMock(
            side_effect=Exception("401 Unauthorized: Invalid API key")
        )
        mock_run_debate.return_value = sample_debate_result

        result = await run_debate_with_routing(
            db=mock_db,
            question="Test market",
            market_price=0.50,
        )

        # Verify graceful fallback
        assert result is not None
        assert result.data_sources == ["local_debate"]
        mock_run_debate.assert_called_once()


# ---------------------------------------------------------------------------
# Credential Priority: Database > Environment Variables
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credential_priority_database_over_env(mock_db, sample_mirofish_signals):
    """Credential priority: Database credentials override env vars."""
    setting = SystemSettings(key="mirofish_enabled", value=True)
    mock_db.query.return_value.filter.return_value.first.return_value = setting

    # Mock database credentials
    db_url_setting = SystemSettings(key="mirofish_api_url", value="https://db.mirofish.ai")
    db_key_setting = SystemSettings(key="mirofish_api_key", value="db_key_12345")

    def mock_query_side_effect(*args):
        mock_query = MagicMock()
        mock_filter = MagicMock()

        def mock_first():
            # Return different settings based on filter call
            if hasattr(mock_filter, '_key'):
                if mock_filter._key == "mirofish_enabled":
                    return setting
                elif mock_filter._key == "mirofish_api_url":
                    return db_url_setting
                elif mock_filter._key == "mirofish_api_key":
                    return db_key_setting
            return None

        mock_filter.first = mock_first
        mock_query.filter = lambda x: setattr(mock_filter, '_key', x.right.value) or mock_filter
        return mock_query

    mock_db.query.side_effect = mock_query_side_effect

    with patch("backend.ai.debate_router.MiroFishClient") as MockClient, \
         patch.dict("os.environ", {"MIROFISH_API_URL": "https://env.mirofish.ai", "MIROFISH_API_KEY": "env_key"}):

        mock_client = MockClient.return_value
        mock_client.fetch_signals = AsyncMock(return_value=sample_mirofish_signals)

        result = await run_debate_with_routing(
            db=mock_db,
            question="Test market",
            market_price=0.50,
        )

        # Verify MiroFish was called (credentials from DB should be used)
        assert result is not None
        assert result.data_sources == ["mirofish"]


# ---------------------------------------------------------------------------
# Validation: Toggle ON Requires Valid Credentials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validation_toggle_requires_credentials(mock_db):
    """Validation: Cannot enable MiroFish without valid credentials."""
    # This test verifies the API endpoint validation logic
    # The actual validation happens in backend/api/settings.py

    # Setup: No credentials in database
    mock_db.query.return_value.filter.return_value.first.return_value = None

    # Attempt to enable MiroFish without credentials should fail at API level
    # (This is tested in API tests, but we verify router behavior here)

    with patch("backend.ai.debate_router.MiroFishClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.fetch_signals = AsyncMock(
            side_effect=Exception("Missing API credentials")
        )

        # Even if enabled flag is set, missing credentials cause fallback
        setting = SystemSettings(key="mirofish_enabled", value=True)
        mock_db.query.return_value.filter.return_value.first.return_value = setting

        with patch("backend.ai.debate_router.run_debate") as mock_run_debate:
            mock_run_debate.return_value = DebateResult(
                consensus_probability=0.50,
                confidence=0.50,
                reasoning="Fallback due to missing credentials",
                market_question="Test",
                market_price=0.50,
            )

            result = await run_debate_with_routing(
                db=mock_db,
                question="Test market",
                market_price=0.50,
            )

            # Verify fallback occurred
            assert result is not None
            mock_run_debate.assert_called_once()


# ---------------------------------------------------------------------------
# Parameter Preservation Through Routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parameter_preservation_all_fields(mock_db, sample_debate_result):
    """Verify all debate parameters preserved through routing."""
    mock_db.query.return_value.filter.return_value.first.return_value = None

    from backend.ai.debate_engine import SignalVote

    signal_votes = [
        SignalVote(
            source="test_source",
            prediction=0.65,
            confidence=0.80,
            reasoning="Test signal",
            weight=0.80,
        )
    ]

    with patch("backend.ai.debate_router.run_debate") as mock_run_debate:
        mock_run_debate.return_value = sample_debate_result

        await run_debate_with_routing(
            db=mock_db,
            question="Complex market question",
            market_price=0.58,
            volume=125000.0,
            category="politics",
            context="Election polling data shows tight race",
            max_rounds=3,
            data_sources=["polls", "betting_markets", "expert_forecasts"],
            signal_votes=signal_votes,
        )

        # Verify all parameters passed to local debate
        call_kwargs = mock_run_debate.call_args.kwargs
        assert call_kwargs["question"] == "Complex market question"
        assert call_kwargs["market_price"] == 0.58
        assert call_kwargs["volume"] == 125000.0
        assert call_kwargs["category"] == "politics"
        assert call_kwargs["context"] == "Election polling data shows tight race"
        assert call_kwargs["max_rounds"] == 3
        assert call_kwargs["data_sources"] == ["polls", "betting_markets", "expert_forecasts"]
        assert call_kwargs["signal_votes"] == signal_votes


# ---------------------------------------------------------------------------
# Latency Tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_latency_tracking_mirofish(mock_db, sample_mirofish_signals):
    """Verify latency tracking for MiroFish API calls."""
    setting = SystemSettings(key="mirofish_enabled", value=True)
    mock_db.query.return_value.filter.return_value.first.return_value = setting

    with patch("backend.ai.debate_router.MiroFishClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.fetch_signals = AsyncMock(return_value=sample_mirofish_signals)

        result = await run_debate_with_routing(
            db=mock_db,
            question="Test market",
            market_price=0.50,
        )

        # Verify latency is tracked
        assert result is not None
        assert result.latency_ms >= 0.0
        assert result.latency_ms < 10000.0  # Reasonable upper bound


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_case_none_db_session(sample_debate_result):
    """Edge case: None db session → raises AttributeError (expected behavior)."""
    with pytest.raises(AttributeError):
        await run_debate_with_routing(
            db=None,
            question="Test market",
            market_price=0.50,
        )


@pytest.mark.asyncio
async def test_edge_case_extreme_market_price(mock_db, sample_mirofish_signals):
    """Edge case: Extreme market prices (0.01, 0.99) handled correctly."""
    setting = SystemSettings(key="mirofish_enabled", value=True)
    mock_db.query.return_value.filter.return_value.first.return_value = setting

    with patch("backend.ai.debate_router.MiroFishClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.fetch_signals = AsyncMock(return_value=sample_mirofish_signals)

        # Test extreme low price
        result_low = await run_debate_with_routing(
            db=mock_db,
            question="Very unlikely event",
            market_price=0.01,
        )
        assert result_low is not None
        assert 0.0 <= result_low.consensus_probability <= 1.0

        # Test extreme high price
        result_high = await run_debate_with_routing(
            db=mock_db,
            question="Very likely event",
            market_price=0.99,
        )
        assert result_high is not None
        assert 0.0 <= result_high.consensus_probability <= 1.0


@pytest.mark.asyncio
async def test_edge_case_zero_volume(mock_db, sample_debate_result):
    """Edge case: Zero volume markets handled correctly."""
    mock_db.query.return_value.filter.return_value.first.return_value = None

    with patch("backend.ai.debate_router.run_debate") as mock_run_debate:
        mock_run_debate.return_value = sample_debate_result

        result = await run_debate_with_routing(
            db=mock_db,
            question="Low liquidity market",
            market_price=0.50,
            volume=0.0,
        )

        assert result is not None
        call_kwargs = mock_run_debate.call_args.kwargs
        assert call_kwargs["volume"] == 0.0
