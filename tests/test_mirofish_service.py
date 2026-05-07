import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add the current directory to sys.path so we can import backend
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock things that might cause issues during import
sys.modules['backend.services.mirofish_monitor'] = MagicMock()
sys.modules['backend.config'] = MagicMock()

from backend.services.mirofish_service import MiroFishService, ServiceState

class TestMiroFishService(unittest.TestCase):
    def setUp(self):
        """Return a fresh MiroFishService instance for each test."""
        self.service = MiroFishService()

    def test_record_error(self):
        """Test that record_error sets the error message."""
        error_msg = "Test error message"
        self.service.record_error(error_msg)
        self.assertEqual(self.service._error_message, error_msg)

        status = self.service.get_status()
        self.assertEqual(status["error_message"], error_msg)

    def test_error_cleared_on_start(self):
        """Test that error message is cleared when service starts."""
        self.service.record_error("some error")
        self.service.start()
        self.assertIsNone(self.service._error_message)
        self.assertIsNone(self.service.get_status()["error_message"])

    def test_error_cleared_on_stop(self):
        """Test that error message is cleared when service stops."""
        self.service.start()
        self.service.record_error("some error")
        self.service.stop()
        self.assertIsNone(self.service._error_message)
        self.assertIsNone(self.service.get_status()["error_message"])

    def test_error_cleared_on_restart(self):
        """Test that error message is cleared when service restarts."""
        self.service.record_error("some error")
        self.service.restart()
        self.assertIsNone(self.service._error_message)
        self.assertIsNone(self.service.get_status()["error_message"])

    def test_error_cleared_on_signal_fetch(self):
        """Test that error message is cleared when a signal fetch is recorded."""
        self.service.record_error("some error")
        self.service.record_signal_fetch(1)
        self.assertIsNone(self.service._error_message)
        self.assertIsNone(self.service.get_status()["error_message"])

    def test_get_status_structure(self):
        """Test that get_status returns the expected structure."""
        status = self.service.get_status()
        self.assertIn("state", status)
        self.assertIn("error_message", status)
        self.assertIn("total_signals_fetched", status)
        self.assertIsNone(status["error_message"])

if __name__ == '__main__':
    unittest.main()
