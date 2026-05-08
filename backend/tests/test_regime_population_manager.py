"""Tests for regime_population_manager.py - Wave 9 Meta-Learning Layer."""

from unittest.mock import MagicMock, patch

from backend.application.agi.regime_population_manager import (
    detect_regime_and_rebalance,
    REGIME_STRATEGY_PREFERENCES
)


def test_regime_strategy_preferences():
    """Test regime strategy preferences structure."""
    assert "volatile" in REGIME_STRATEGY_PREFERENCES
    assert "trending" in REGIME_STRATEGY_PREFERENCES
    assert "event_dense" in REGIME_STRATEGY_PREFERENCES
    assert "sideways" in REGIME_STRATEGY_PREFERENCES

    volatile_prefs = REGIME_STRATEGY_PREFERENCES["volatile"]
    assert "statistical_arb" in volatile_prefs["boost"]
    assert "momentum_surfer" in volatile_prefs["suppress"]


def test_detect_regime_and_rebalance():
    """Test regime detection and rebalancing."""
    db = MagicMock()

    with patch('backend.application.agi.regime_population_manager.RegimeDetector') as mock_detector:
        with patch('backend.application.agi.regime_population_manager.regime_changed', return_value=True):
            with patch('backend.application.agi.regime_population_manager.publish_event') as mock_publish:
                # Mock regime detection
                mock_detector.return_value.detect_regime.return_value.regime.value = "volatile"

                regime = detect_regime_and_rebalance(db)

                assert regime == "volatile"

                # Check event publishing
                assert mock_publish.called
                call_args = [call[0][0] for call in mock_publish.call_args_list]
                assert "regime_shift" in call_args


def test_detect_regime_and_rebalance_no_change():
    """Test regime detection when regime hasn't changed."""
    db = MagicMock()

    with patch('backend.application.agi.regime_population_manager.RegimeDetector') as mock_detector:
        with patch('backend.application.agi.regime_population_manager.regime_changed', return_value=False):
            with patch('backend.application.agi.regime_population_manager.publish_event') as mock_publish:
                # Mock regime detection
                mock_detector.return_value.detect_regime.return_value.regime.value = "neutral"

                regime = detect_regime_and_rebalance(db)

                assert regime == "neutral"

                # Check no rebalancing events
                call_args = [call[0][0] for call in mock_publish.call_args_list]
                assert "regime_shift" not in call_args


def test_regime_detector_integration():
    """Test integration with RegimeDetector."""
    db = MagicMock()

    with patch('backend.application.agi.regime_population_manager.RegimeDetector') as mock_detector_class:
        mock_detector = MagicMock()
        mock_detector.detect_regime.return_value.regime.value = "trending"
        mock_detector_class.return_value = mock_detector

        with patch('backend.application.agi.regime_population_manager.regime_changed', return_value=True):
            with patch('backend.application.agi.regime_population_manager.increase_archetype_allocation') as mock_increase:
                with patch('backend.application.agi.regime_population_manager.decrease_archetype_allocation') as mock_decrease:
                    regime = detect_regime_and_rebalance(db)

                    assert regime == "trending"

                    # Check allocation adjustments
                    assert mock_increase.called
                    assert mock_decrease.called
