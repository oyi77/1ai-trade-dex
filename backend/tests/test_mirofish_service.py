"""Unit tests for MiroFish service lifecycle management."""

from unittest.mock import MagicMock, patch

from backend.services.mirofish_service import (
    MiroFishService,
    ServiceState,
)


@patch("backend.services.mirofish_service.MiroFishService.get_status", return_value={})
def test_pause_stopped_service(mock_get_status):
    """Test pausing a stopped service returns appropriate message."""
    service = MiroFishService()
    assert service.state == ServiceState.STOPPED

    result = service.pause()

    assert service.state == ServiceState.STOPPED
    assert result["message"] == "Cannot pause \u2014 service is stopped. Use start first."
    assert "state" not in result # Since get_status is mocked to return {}


@patch("backend.services.mirofish_service.MiroFishService.get_status", return_value={})
@patch("backend.services.mirofish_monitor.get_monitor")
def test_pause_running_service(mock_get_monitor, mock_get_status):
    """Test pausing a running service."""
    mock_monitor = MagicMock()
    mock_get_monitor.return_value = mock_monitor

    service = MiroFishService()
    service.start()
    assert service.state == ServiceState.RUNNING

    result = service.pause()

    assert service.state == ServiceState.PAUSED
    assert result["message"] == "Paused (was running)"


@patch("backend.services.mirofish_service.MiroFishService.get_status", return_value={})
@patch("backend.services.mirofish_monitor.get_monitor")
def test_pause_paused_service(mock_get_monitor, mock_get_status):
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

def test_record_signal_fetch_negative_count():
    from backend.services.mirofish_service import get_mirofish_service

    with patch("backend.services.mirofish_monitor.get_monitor"):
        with patch("backend.services.mirofish_monitor.reset_monitor"):
            # Avoid database imports in get_status by mocking it
            with patch("backend.services.mirofish_service.MiroFishService.get_status", return_value={}):
                service = get_mirofish_service()
                service.restart()

                initial_count = service._total_signals_fetched

                # Action: Call with negative count
                service.record_signal_fetch(count=-5)

                # Assert: The count should not have changed, because negative count is ignored
                assert service._total_signals_fetched == initial_count

def test_record_signal_fetch_positive_count():
    from backend.services.mirofish_service import get_mirofish_service

    with patch("backend.services.mirofish_monitor.get_monitor"):
        with patch("backend.services.mirofish_monitor.reset_monitor"):
            with patch("backend.services.mirofish_service.MiroFishService.get_status", return_value={}):
                service = get_mirofish_service()
                service.restart()

                initial_count = service._total_signals_fetched

                # Action: Call with positive count
                service.record_signal_fetch(count=5)

                # Assert: The count should have increased
                assert service._total_signals_fetched == initial_count + 5

def test_record_signal_fetch_zero_count():
    from backend.services.mirofish_service import get_mirofish_service

    with patch("backend.services.mirofish_monitor.get_monitor"):
        with patch("backend.services.mirofish_monitor.reset_monitor"):
            with patch("backend.services.mirofish_service.MiroFishService.get_status", return_value={}):
                service = get_mirofish_service()
                service.restart()

                initial_count = service._total_signals_fetched

                # Action: Call with zero count
                service.record_signal_fetch(count=0)

                # Assert: The count should not have changed
                assert service._total_signals_fetched == initial_count
