import pytest
import time
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

def test_stop_when_running():
    service = MiroFishService()
    service.start()
    assert service.state == ServiceState.RUNNING

    result = service.stop()

    assert result["state"] == ServiceState.STOPPED.value
    assert "Stopped (was running)" in result["message"]
    assert service.state == ServiceState.STOPPED

def test_stop_when_paused():
    service = MiroFishService()
    service.start()
    service.pause()
    assert service.state == ServiceState.PAUSED

    result = service.stop()

    assert result["state"] == ServiceState.STOPPED.value
    assert "Stopped (was paused)" in result["message"]
    assert service.state == ServiceState.STOPPED

def test_stop_clears_state():
    service = MiroFishService()
    service.start()

    # Manually set some state that stop() should clear
    service.record_error("some error")

    assert service._error_message == "some error"
    assert service._started_at is not None

    service.stop()

    assert service._error_message is None
    assert service._started_at is None
