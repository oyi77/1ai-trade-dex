"""Backward-compatible structured logging module.

This module now delegates to loguru. Use `from loguru import logger` directly
in new code. The symbols here remain for backward compatibility with existing
imports (correlation_id, new_correlation_id, get_correlation_id, configure_logging).
"""

from loguru import logger

from backend.core.log import (
    InterceptHandler,
    configure_logging,
    correlation_id,
    get_correlation_id,
    new_correlation_id,
)

__all__ = [
    "logger",
    "InterceptHandler",
    "configure_logging",
    "correlation_id",
    "new_correlation_id",
    "get_correlation_id",
]
