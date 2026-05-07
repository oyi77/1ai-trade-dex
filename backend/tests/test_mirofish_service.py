import pytest
from unittest.mock import patch, MagicMock

from backend.services.mirofish_service import MiroFishService, ServiceState


def test_start_already_running():
    service = MiroFishService()

    # Mock the monitor retrieval to avoid needing real config/imports
    with patch("backend.services.mirofish_monitor.get_monitor") as mock_get_monitor:
        mock_monitor = MagicMock()
        mock_get_monitor.return_value = mock_monitor

        # Start the service initially
        result1 = service.start()
        assert service.state == ServiceState.RUNNING
        assert "Started" in result1["message"]

        # Start the service again while it's already running
        result2 = service.start()
        assert service.state == ServiceState.RUNNING
        assert result2["message"] == "Already running"
