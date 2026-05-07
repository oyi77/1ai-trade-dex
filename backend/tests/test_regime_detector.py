"""Tests for RegimeDetector — regime classification, hysteresis, and event emission."""
from unittest.mock import patch

from backend.core.agi_types import MarketRegime, RegimeTransition
from backend.core.regime_detector import RegimeDetector


def _bull_data(**overrides):
    return {
        "prices": [100 + i * 0.5 for i in range(250)],
        "volumes": [1000 + i * 10 for i in range(250)],
        "sma_50": 115.0,
        "sma_200": 110.0,
        "atr": 2.0,
        "atr_percentile": 0.3,
        "drawdown": 0.02,
        "volume_trend": 0.5,
        **overrides,
    }


def _bear_data(**overrides):
    return {
        "prices": [200 - i * 0.5 for i in range(250)],
        "volumes": [1000 - i * 5 for i in range(250)],
        "sma_50": 95.0,
        "sma_200": 100.0,
        "atr": 5.0,
        "atr_percentile": 0.7,
        "drawdown": 0.08,
        "volume_trend": -0.5,
        **overrides,
    }


def _sideways_data(**overrides):
    return {
        "prices": [150 + (i % 10 - 5) * 0.1 for i in range(250)],
        "volumes": [500 for _ in range(250)],
        "sma_50": 150.1,
        "sma_200": 150.0,
        "atr": 1.0,
        "atr_percentile": 0.2,
        "drawdown": 0.01,
        "volume_trend": 0.0,
        **overrides,
    }


def _sideways_volatile_data(**overrides):
    return {
        "prices": [150 + (i % 20 - 10) * 0.5 for i in range(250)],
        "volumes": [800 for _ in range(250)],
        "sma_50": 150.1,
        "sma_200": 150.0,
        "atr": 8.0,
        "atr_percentile": 0.8,
        "drawdown": 0.05,
        "volume_trend": 0.1,
        **overrides,
    }


def _crisis_data(**overrides):
    return {
        "prices": [200 - i * 2 for i in range(250)],
        "volumes": [2000 for _ in range(250)],
        "sma_50": 160.0,
        "sma_200": 180.0,
        "atr": 15.0,
        "atr_percentile": 0.95,
        "drawdown": 0.25,
        "volume_trend": -0.8,
        **overrides,
    }


class TestRegimeDetection:
    def test_bull_regime(self):
        detector = RegimeDetector()
        result = detector.detect_regime(_bull_data())
        assert result.regime == MarketRegime.BULL
        assert result.confidence > 0.5

    def test_bear_regime(self):
        detector = RegimeDetector()
        result = detector.detect_regime(_bear_data())
        assert result.regime == MarketRegime.BEAR
        assert result.confidence > 0.5

    def test_sideways_regime(self):
        detector = RegimeDetector()
        result = detector.detect_regime(_sideways_data())
        assert result.regime == MarketRegime.SIDEWAYS
        assert result.confidence > 0.3

    def test_sideways_volatile_regime(self):
        detector = RegimeDetector()
        result = detector.detect_regime(_sideways_volatile_data())
        assert result.regime == MarketRegime.SIDEWAYS_VOLATILE
        assert result.confidence > 0.5

    def test_crisis_regime(self):
        detector = RegimeDetector()
        result = detector.detect_regime(_crisis_data())
        assert result.regime == MarketRegime.CRISIS
        assert result.confidence > 0.5

    def test_unknown_regime_insufficient_data(self):
        detector = RegimeDetector()
        result = detector.detect_regime({"prices": [1, 2, 3], "volumes": [1, 2, 3]})
        assert result.regime == MarketRegime.UNKNOWN
        assert result.confidence == 0.0
        assert result.indicators["reason"] == "insufficient_data"


class TestHysteresis:
    def test_hysteresis_prevents_oscillation(self):
        detector = RegimeDetector(hysteresis=0.05)
        bull_result = detector.detect_regime(_bull_data())
        assert bull_result.regime == MarketRegime.BULL
        near_bull = _sideways_data(sma_50=110.5, sma_200=110.0, atr_percentile=0.3, volume_trend=0.1)
        result = detector.detect_regime(near_bull)
        assert result.regime == MarketRegime.BULL

    def test_hysteresis_allows_large_shift(self):
        detector = RegimeDetector(hysteresis=0.05)
        detector.detect_regime(_bull_data())
        crisis_result = detector.detect_regime(_crisis_data())
        assert crisis_result.regime == MarketRegime.CRISIS


class TestRegimeResult:
    def test_result_has_all_fields(self):
        detector = RegimeDetector()
        result = detector.detect_regime(_bull_data())
        assert hasattr(result, "regime")
        assert hasattr(result, "confidence")
        assert hasattr(result, "indicators")
        assert hasattr(result, "timestamp")
        assert isinstance(result.regime, MarketRegime)
        assert 0.0 <= result.confidence <= 1.0

    def test_confidence_between_zero_and_one(self):
        detector = RegimeDetector()
        for data_fn in [_bull_data, _bear_data, _sideways_data, _crisis_data]:
            result = detector.detect_regime(data_fn())
            assert 0.0 <= result.confidence <= 1.0


class TestRegimeHistory:
    def test_history_records_transitions(self):
        detector = RegimeDetector()
        detector.detect_regime(_bull_data())
        detector.detect_regime(_crisis_data())
        history = detector.get_regime_history(hours=1)
        assert len(history) >= 1
        assert isinstance(history[0], RegimeTransition)
        assert history[0].from_regime == MarketRegime.BULL
        assert history[0].to_regime == MarketRegime.CRISIS

    def test_get_current_regime(self):
        detector = RegimeDetector()
        assert detector.get_current_regime() == MarketRegime.UNKNOWN
        detector.detect_regime(_bull_data())
        assert detector.get_current_regime() == MarketRegime.BULL

    def test_empty_history_initially(self):
        detector = RegimeDetector()
        assert detector.get_regime_history(hours=24) == []


class TestEventEmission:
    def test_regime_change_emits_event(self):
        detector = RegimeDetector()
        with patch("backend.core.event_bus.publish_event") as mock_publish:
            detector.detect_regime(_bull_data())
            detector.detect_regime(_crisis_data())
            assert mock_publish.called
            call_args = mock_publish.call_args
            assert call_args[0][0] == "regime_changed"
            assert call_args[0][1]["from_regime"] == "bull"
            assert call_args[0][1]["to_regime"] == "crisis"

    def test_no_event_on_same_regime(self):
        detector = RegimeDetector()
        with patch("backend.core.event_bus.publish_event") as mock_publish:
            detector.detect_regime(_bull_data())
            detector.detect_regime(_bull_data())
            assert not mock_publish.called
