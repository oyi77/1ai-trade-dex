"""Tests for RegimeConfidenceRouter - Phase G Gap G2/G6"""

import pytest
from unittest.mock import MagicMock, patch

from backend.application.meta.regime_router import RegimeConfidenceRouter
from backend.core.agi_types import MarketRegime
from backend.config import settings


@pytest.fixture
def regime_router():
    """Create a RegimeConfidenceRouter instance for testing."""
    return RegimeConfidenceRouter()


def test_regime_router_initialization(regime_router):
    """Test that RegimeConfidenceRouter initializes correctly."""
    assert regime_router is not None
    assert regime_router.regime_detector is None


def test_get_multiplier_known_strategy_bull(regime_router):
    """Test multiplier retrieval for known strategy in bull regime."""
    with patch.object(regime_router, '_get_current_regime', return_value="bull"):
        multiplier = regime_router.get_multiplier("BTC Momentum")
        assert multiplier == 0.90


def test_get_multiplier_known_strategy_bear(regime_router):
    """Test multiplier retrieval for known strategy in bear regime."""
    with patch.object(regime_router, '_get_current_regime', return_value="bear"):
        multiplier = regime_router.get_multiplier("Market Maker")
        assert multiplier == 0.90


def test_get_multiplier_unknown_strategy(regime_router):
    """Test multiplier retrieval for unknown strategy."""
    with patch.object(regime_router, '_get_current_regime', return_value="bull"):
        multiplier = regime_router.get_multiplier("Unknown Strategy")
        assert multiplier == 1.00  # Default multiplier


def test_get_multiplier_unknown_regime(regime_router):
    """Test multiplier retrieval for unknown regime."""
    with patch.object(regime_router, '_get_current_regime', return_value="unknown"):
        multiplier = regime_router.get_multiplier("BTC Momentum")
        assert multiplier == 1.00  # Default when regime not found


def test_get_adjusted_threshold_bull_momentum(regime_router):
    """Test adjusted threshold calculation for BTC Momentum in bull regime."""
    with patch.object(regime_router, '_get_current_regime', return_value="bull"):
        threshold = regime_router.get_adjusted_threshold("BTC Momentum", 0.70)
        # 0.70 * 0.90 = 0.63, capped at 0.95
        assert threshold == 0.63


def test_get_adjusted_threshold_bear_market_maker(regime_router):
    """Test adjusted threshold calculation for Market Maker in bear regime."""
    with patch.object(regime_router, '_get_current_regime', return_value="bear"):
        threshold = regime_router.get_adjusted_threshold("Market Maker", 0.70)
        # 0.70 * 0.90 = 0.63, capped at 0.95
        assert threshold == 0.63


def test_get_adjusted_threshold_volatile(regime_router):
    """Test adjusted threshold calculation in volatile regime."""
    with patch.object(regime_router, '_get_current_regime', return_value="volatile"):
        threshold = regime_router.get_adjusted_threshold("BTC Momentum", 0.60)
        # 0.60 * 1.25 = 0.75, capped at 0.95
        assert threshold == 0.75


def test_get_adjusted_threshold_cap_at_95(regime_router):
    """Test that adjusted threshold is capped at 0.95."""
    with patch.object(regime_router, '_get_current_regime', return_value="volatile"):
        threshold = regime_router.get_adjusted_threshold("BTC Momentum", 0.90)
        # 0.90 * 1.25 = 1.125, but capped at 0.95
        assert threshold == 0.95


def test_get_current_regime_disabled(regime_router):
    """Test regime detection when REGIME_ROUTING_ENABLED is False."""
    original_value = settings.REGIME_ROUTING_ENABLED
    settings.REGIME_ROUTING_ENABLED = False
    
    try:
        regime = regime_router._get_current_regime()
        assert regime == "sideways"  # Default neutral regime
    finally:
        settings.REGIME_ROUTING_ENABLED = original_value


def test_get_current_regime_with_detector(regime_router):
    """Test regime detection using regime detector."""
    original_value = settings.REGIME_ROUTING_ENABLED
    settings.REGIME_ROUTING_ENABLED = True
    
    try:
        # Create a mock regime detector
        mock_detector = MagicMock()
        mock_result = MagicMock()
        mock_result.regime = MarketRegime.BULL
        mock_detector.detect_regime.return_value = mock_result
        
        regime_router.regime_detector = mock_detector
        
        regime = regime_router._get_current_regime()
        assert regime == "bull"
        mock_detector.detect_regime.assert_called_once()
    finally:
        settings.REGIME_ROUTING_ENABLED = original_value


def test_get_current_regime_without_detector(regime_router):
    """Test regime detection without regime detector."""
    original_value = settings.REGIME_ROUTING_ENABLED
    settings.REGIME_ROUTING_ENABLED = True
    
    try:
        regime_router.regime_detector = None
        regime = regime_router._get_current_regime()
        assert regime == "unknown"  # Fallback
    finally:
        settings.REGIME_ROUTING_ENABLED = original_value


def test_regime_multipliers_structure():
    """Test that REGIME_MULTIPLIERS has expected structure."""
    assert "bull" in RegimeConfidenceRouter.REGIME_MULTIPLIERS
    assert "bear" in RegimeConfidenceRouter.REGIME_MULTIPLIERS
    assert "volatile" in RegimeConfidenceRouter.REGIME_MULTIPLIERS
    assert "sideways" in RegimeConfidenceRouter.REGIME_MULTIPLIERS
    assert "event_dense" in RegimeConfidenceRouter.REGIME_MULTIPLIERS
    
    # Check each regime has __default__
    for regime in RegimeConfidenceRouter.REGIME_MULTIPLIERS.values():
        assert "__default__" in regime


def test_event_dense_regime_multipliers():
    """Test event_dense regime has specific strategy multipliers."""
    event_dense = RegimeConfidenceRouter.REGIME_MULTIPLIERS["event_dense"]
    assert event_dense["News Catalyst"] == 0.85
    assert event_dense["Event Catalyst"] == 0.85
    assert event_dense["__default__"] == 1.05
