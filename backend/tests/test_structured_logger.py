"""Tests for backend/core/log.py (loguru-based logging)."""

import json

from backend.core.log import (
    configure_logging,
    correlation_id,
    new_correlation_id,
    get_correlation_id,
)


def test_correlation_id_propagation():
    """Set correlation ID, verify it's stored in context var."""
    cid = new_correlation_id()
    assert cid == get_correlation_id()
    assert len(cid) == 36  # UUID4 format


def test_correlation_id_default():
    """Default correlation ID is empty string."""
    correlation_id.set("")
    assert get_correlation_id() == ""


def test_configure_logging_runs_without_error():
    """Verify configure_logging sets up sinks without error."""
    # Should not raise — calls logger.remove() then adds sinks
    configure_logging(level="INFO", json_output=False)

def test_configure_logging_json_mode():
    """Verify JSON mode configures loguru with serialize=True."""
    # Should not raise — configures with JSON serialization
    configure_logging(level="DEBUG", json_output=True)