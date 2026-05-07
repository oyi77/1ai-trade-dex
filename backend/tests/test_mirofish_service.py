import pytest
from unittest.mock import patch

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
