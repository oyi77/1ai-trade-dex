"""Unit tests for MiroFish service lifecycle management."""

import pytest
from backend.services.mirofish_service import get_mirofish_service, ServiceState

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
