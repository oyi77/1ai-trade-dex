"""Unit tests for MiroFish service lifecycle management."""

import time
from unittest.mock import MagicMock, patch

from backend.services.mirofish_service import MiroFishService, ServiceState


def test_initial_state():
    service = MiroFishService()
    assert service.state == ServiceState.STOPPED


def test_stop_when_already_stopped():
    service = MiroFishService()
    assert service.state == ServiceState.STOPPED

    result = service.stop()

    assert result["state"] == ServiceState.STOPPED.value
    assert "Already stopped" in result["message"]
    assert service.state == ServiceState.STOPPED


@patch("backend.services.mirofish_monitor.get_monitor")
def test_stop_when_running(mock_get_monitor):
    mock_monitor = MagicMock()
    mock_get_monitor.return_value = mock_monitor

    service = MiroFishService()
    service.start()
    assert service.state == ServiceState.RUNNING

    result = service.stop()

    assert result["state"] == ServiceState.STOPPED.value
    assert "Stopped (was running)" in result["message"]
    assert service.state == ServiceState.STOPPED


@patch("backend.services.mirofish_monitor.get_monitor")
def test_stop_when_paused(mock_get_monitor):
    mock_monitor = MagicMock()
    mock_get_monitor.return_value = mock_monitor

    service = MiroFishService()
    service.start()
    service.pause()
    assert service.state == ServiceState.PAUSED

    result = service.stop()

    assert result["state"] == ServiceState.STOPPED.value
    assert "Stopped (was paused)" in result["message"]
    assert service.state == ServiceState.STOPPED


@patch("backend.services.mirofish_monitor.get_monitor")
def test_stop_clears_state(mock_get_monitor):
    mock_monitor = MagicMock()
    mock_get_monitor.return_value = mock_monitor

    service = MiroFishService()
    service.start()

    # Manually set some state that stop() should clear
    service.record_error("some error")

    assert service._error_message == "some error"
    assert service._started_at is not None

    service.stop()

    assert service._error_message is None
    assert service._started_at is None


def test_pause_stopped_service():
    """Test pausing a stopped service returns appropriate message."""
    service = MiroFishService()
    assert service.state == ServiceState.STOPPED

    result = service.pause()

    assert service.state == ServiceState.STOPPED
    assert result["message"] == "Cannot pause \u2014 service is stopped. Use start first."
    assert result["state"] == "stopped"


@patch("backend.services.mirofish_monitor.get_monitor")
def test_pause_running_service(mock_get_monitor):
    """Test pausing a running service."""
    mock_monitor = MagicMock()
    mock_get_monitor.return_value = mock_monitor

    service = MiroFishService()
    service.start()
    assert service.state == ServiceState.RUNNING

    result = service.pause()

    assert service.state == ServiceState.PAUSED
    assert result["message"] == "Paused (was running)"
    assert result["state"] == "paused"


@patch("backend.services.mirofish_monitor.get_monitor")
def test_pause_paused_service(mock_get_monitor):
    """Test pausing an already paused service returns appropriate message."""
    mock_monitor = MagicMock()
    mock_get_monitor.return_value = mock_monitor

    service = MiroFishService()
    service.start()
    service.pause()
    assert service.state == ServiceState.PAUSED

    result = service.pause()

    assert service.state == ServiceState.PAUSED
    assert result["message"] == "Already paused"
    assert result["state"] == "paused"
