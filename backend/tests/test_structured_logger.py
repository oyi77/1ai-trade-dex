"""Tests for backend/monitoring/structured_logger.py"""

import json
import logging

from backend.monitoring.structured_logger import (
    JSONFormatter,
    configure_logging,
    new_correlation_id,
    get_correlation_id,
)


def test_json_formatter_output():
    """Verify JSON format with required fields."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Test message",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)

    assert "timestamp" in data
    assert data["level"] == "INFO"
    assert data["logger"] == "test_logger"
    assert data["message"] == "Test message"
    assert "correlation_id" in data


def test_correlation_id_propagation():
    """Set correlation ID, verify it appears in log output."""
    cid = new_correlation_id()
    assert cid == get_correlation_id()
    assert len(cid) == 36  # UUID4 format

    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg="Correlated message",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)

    assert data["correlation_id"] == cid


def test_configure_logging_json_mode():
    """Verify JSON mode configures root logger correctly."""
    configure_logging(json_output=True, level="DEBUG")

    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG
    assert len(root_logger.handlers) >= 1

    handler = root_logger.handlers[0]
    assert isinstance(handler.formatter, JSONFormatter)

    # Reset to standard mode to avoid polluting other tests
    configure_logging(json_output=False, level="INFO")
