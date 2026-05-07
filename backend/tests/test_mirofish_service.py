"""Unit tests for MiroFish service lifecycle management."""

from unittest.mock import MagicMock, patch

from backend.services.mirofish_service import (
    MiroFishService,
    ServiceState,
    get_mirofish_service,
)


def test_pause_service():
    """Test pausing the MiroFish service."""
    service = get_mirofish_service()

    # Ensure starting state
    service.stop()
    assert service.state == ServiceState.STOPPED

    # Pausing stopped service should return error message but state should remain STOPPED
    result = service.pause()
    assert result["state"] == ServiceState.STOPPED.value
    assert "Cannot pause" in result["message"]
    assert service.state == ServiceState.STOPPED

    # Start service
    service.start()
    assert service.state == ServiceState.RUNNING

    # Pause running service
    result = service.pause()
    assert result["state"] == ServiceState.PAUSED.value
    assert "Paused" in result["message"]
    assert service.state == ServiceState.PAUSED

    # Pausing already paused service
    result = service.pause()
    assert result["state"] == ServiceState.PAUSED.value
    assert "Already paused" in result["message"]
    assert service.state == ServiceState.PAUSED


def test_pause_stopped_service():
    """Test pausing a stopped service returns appropriate message."""
    service = MiroFishService()
    assert service.state == ServiceState.STOPPED

    result = service.pause()

    assert service.state == ServiceState.STOPPED
    assert result["message"] == "Cannot pause — service is stopped. Use start first."
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
