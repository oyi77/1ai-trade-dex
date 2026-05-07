"""Unit tests for MiroFish service lifecycle management."""

from unittest.mock import patch

import pytest

from backend.services.mirofish_service import ServiceState, get_mirofish_service


@pytest.fixture
def clean_service():
    """Fixture to ensure a clean MiroFishService instance for each test."""
    import backend.services.mirofish_service as mfs

    mfs._service_instance = None
    service = mfs.get_mirofish_service()
    yield service
    mfs._service_instance = None


def test_pause_service(clean_service):
    """Test pausing the MiroFish service."""
    # Ensure starting state
    clean_service.stop()
    assert clean_service.state == ServiceState.STOPPED

    # Pausing stopped service should return error message but state should remain STOPPED
    result = clean_service.pause()
    assert result["state"] == ServiceState.STOPPED.value
    assert "Cannot pause" in result["message"]
    assert clean_service.state == ServiceState.STOPPED

    # Start service
    clean_service.start()
    assert clean_service.state == ServiceState.RUNNING

    # Pause running service
    result = clean_service.pause()
    assert result["state"] == ServiceState.PAUSED.value
    assert "Paused" in result["message"]
    assert clean_service.state == ServiceState.PAUSED

    # Pausing already paused service
    result = clean_service.pause()
    assert result["state"] == ServiceState.PAUSED.value
    assert "Already paused" in result["message"]
    assert clean_service.state == ServiceState.PAUSED


def test_mirofish_service_restart_from_stopped(clean_service):
    """Test restarting the MiroFish service from STOPPED state."""
    assert clean_service.state == ServiceState.STOPPED

    with patch("backend.services.mirofish_monitor.reset_monitor") as mock_reset:
        result = clean_service.restart()

        assert clean_service.state == ServiceState.RUNNING
        assert "Restarted (was stopped" in result["message"]
        mock_reset.assert_called_once()
        assert clean_service._total_signals_fetched == 0
        assert clean_service._error_message is None


def test_mirofish_service_restart_from_running(clean_service):
    """Test restarting the MiroFish service from RUNNING state."""
    clean_service.start()
    assert clean_service.state == ServiceState.RUNNING

    clean_service.record_signal_fetch(5)
    clean_service.record_error("Some error")

    assert clean_service.get_status()["total_signals_fetched"] == 5
    assert clean_service.get_status()["error_message"] == "Some error"

    with patch("backend.services.mirofish_monitor.reset_monitor") as mock_reset:
        result = clean_service.restart()

        assert clean_service.state == ServiceState.RUNNING
        assert "Restarted (was running" in result["message"]
        mock_reset.assert_called_once()

        status = clean_service.get_status()
        assert status["total_signals_fetched"] == 0
        assert status["error_message"] is None


def test_mirofish_service_restart_from_paused(clean_service):
    """Test restarting the MiroFish service from PAUSED state."""
    clean_service.start()
    clean_service.pause()
    assert clean_service.state == ServiceState.PAUSED

    with patch("backend.services.mirofish_monitor.reset_monitor") as mock_reset:
        result = clean_service.restart()

        assert clean_service.state == ServiceState.RUNNING
        assert "Restarted (was paused" in result["message"]
        mock_reset.assert_called_once()


def test_mirofish_service_restart_monitor_error_handled(clean_service, caplog):
    """Test restarting handles exceptions when resetting the monitor."""
    assert clean_service.state == ServiceState.STOPPED

    with patch(
        "backend.services.mirofish_monitor.reset_monitor",
        side_effect=Exception("Reset failed"),
    ):
        result = clean_service.restart()

        assert clean_service.state == ServiceState.RUNNING
        assert "Restarted (was stopped" in result["message"]
        assert any(
            "Could not reset monitor on restart: Reset failed" in record.message
            for record in caplog.records
        )
