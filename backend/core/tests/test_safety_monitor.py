import pytest
import json
from unittest.mock import MagicMock, patch
from backend.core.safety import SafetyMonitor, AlertSeverity

def _mock_session_with_bot_state(bot_state_obj):
    mock_session = MagicMock()
    if bot_state_obj is not None:
        mock_session.query.return_value.filter.return_value.first.return_value = bot_state_obj
    return mock_session

@pytest.fixture
def bot_state_with_thresholds():
    data = {
        "safety_thresholds": {
            "max_position_size": 0.05,
            "max_daily_loss": 0.02,
            "min_confidence": 0.7
        },
        "safety_alerts": []
    }
    obj = MagicMock()
    obj.mode = "paper"
    obj.misc_data = json.dumps(data)
    return obj

@pytest.fixture
def bot_state_no_data():
    obj = MagicMock()
    obj.mode = "paper"
    obj.misc_data = None
    return obj

def test_check_trade_approved(bot_state_with_thresholds):
    mock_db = _mock_session_with_bot_state(bot_state_with_thresholds)
    with patch("backend.core.safety.SessionLocal", return_value=mock_db):
        monitor = SafetyMonitor()
        approved, reason = monitor.check_trade({"suggested_size": 0.03, "confidence": 0.8})
        assert approved is True
        assert "approved" in reason.lower()

def test_check_trade_rejected_size(bot_state_with_thresholds):
    mock_db = _mock_session_with_bot_state(bot_state_with_thresholds)
    with patch("backend.core.safety.SessionLocal", return_value=mock_db):
        monitor = SafetyMonitor()
        approved, reason = monitor.check_trade({"suggested_size": 0.1, "confidence": 0.8})
        assert approved is False
        assert "position size" in reason.lower()

def test_check_trade_rejected_confidence(bot_state_with_thresholds):
    mock_db = _mock_session_with_bot_state(bot_state_with_thresholds)
    with patch("backend.core.safety.SessionLocal", return_value=mock_db):
        monitor = SafetyMonitor()
        approved, reason = monitor.check_trade({"suggested_size": 0.03, "confidence": 0.5})
        assert approved is False
        assert "confidence" in reason.lower()

def test_check_trade_env_fallback(bot_state_no_data):
    mock_db = _mock_session_with_bot_state(bot_state_no_data)
    with patch("backend.core.safety.SessionLocal", return_value=mock_db):
        with patch.dict("os.environ", {
            "SAFETY_MAX_POSITION_SIZE": "0.1",
            "SAFETY_MAX_DAILY_LOSS": "0.05",
            "SAFETY_MIN_CONFIDENCE": "0.6"
        }, clear=False):
            monitor = SafetyMonitor()
            approved, reason = monitor.check_trade({"suggested_size": 0.05, "confidence": 0.8})
            assert approved is True

def test_check_trade_env_fallback_rejected():
    mock_db = _mock_session_with_bot_state(None)
    with patch("backend.core.safety.SessionLocal", return_value=mock_db):
        with patch.dict("os.environ", {
            "SAFETY_MAX_POSITION_SIZE": "0.1",
            "SAFETY_MAX_DAILY_LOSS": "0.05",
            "SAFETY_MIN_CONFIDENCE": "0.6"
        }, clear=False):
            monitor = SafetyMonitor()
            approved, reason = monitor.check_trade({"suggested_size": 0.2, "confidence": 0.8})
            assert approved is False

def test_record_alert_persists(bot_state_with_thresholds):
    mock_db = _mock_session_with_bot_state(bot_state_with_thresholds)
    with patch("backend.core.safety.SessionLocal", return_value=mock_db):
        monitor = SafetyMonitor()
        monitor.record_alert(AlertSeverity.CRITICAL, "Test breach", strategy_key="strat_1")
        mock_db.commit.assert_called_once()
        updated = json.loads(bot_state_with_thresholds.misc_data)
        assert len(updated["safety_alerts"]) == 1
        alert = updated["safety_alerts"][0]
        assert alert["severity"] == "CRITICAL"
        assert alert["message"] == "Test breach"
        assert alert["strategy_key"] == "strat_1"

def test_get_global_limits(bot_state_with_thresholds):
    mock_db = _mock_session_with_bot_state(bot_state_with_thresholds)
    with patch("backend.core.safety.SessionLocal", return_value=mock_db):
        monitor = SafetyMonitor()
        limits = monitor.get_global_limits()
        assert limits["max_position_size"] == 0.05
        assert limits["max_daily_loss"] == 0.02
        assert limits["min_confidence"] == 0.7
