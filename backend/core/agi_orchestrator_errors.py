"""AGI cycle error taxonomy + circuit-breaker state."""

from __future__ import annotations

import os
from enum import Enum

from loguru import logger


class ErrorType(Enum):
    BENIGN = "BENIGN"
    TRANSIENT = "TRANSIENT"
    PERMANENT = "PERMANENT"


TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    ConnectionError,
    OSError,
)
# Lazy-import httpx exceptions only when needed (avoids hard dependency).
_httpx_transient: tuple[type[BaseException], ...] = ()
_httpx_checked: bool = False


def _get_httpx_transient() -> tuple[type[BaseException], ...]:
    """Return httpx transient exception types, importing lazily."""
    global _httpx_transient, _httpx_checked
    if not _httpx_checked:
        try:
            import httpx

            _httpx_transient = (httpx.TimeoutException, httpx.HTTPStatusError)
        except ImportError:
            _httpx_transient = ()
        _httpx_checked = True
    return _httpx_transient


PERMANENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TypeError,
    ValueError,
    ImportError,
    AttributeError,
    KeyError,
)


def classify_exception(exc: BaseException) -> ErrorType:
    """Classify an exception as TRANSIENT, PERMANENT, or BENIGN.

    TRANSIENT — network timeouts, rate limits, service unavailable (retry-safe).
    PERMANENT — programming errors, bad data, missing config (must raise).
    BENIGN    — anything that doesn't match the above (log and continue).
    """
    if isinstance(exc, TRANSIENT_EXCEPTIONS + _get_httpx_transient()):
        return ErrorType.TRANSIENT
    if isinstance(exc, PERMANENT_EXCEPTIONS):
        return ErrorType.PERMANENT
    return ErrorType.BENIGN


# Module-level circuit breaker state for TRANSIENT-failure tracking across cycles.
_consecutive_failures: int = 0
_circuit_open: bool = False
_TRANSIENT_FAILURE_THRESHOLD: int = 3
_STATS_REPORT_CRITICAL_ERRORS: bool = os.getenv(
    "STATS_REPORT_CRITICAL_ERRORS", "false"
).lower() in ("true", "1", "yes")


def _open_circuit() -> None:
    """Halt the AGI improvement cycle after repeated TRANSIENT failures."""
    global _circuit_open
    _circuit_open = True
    logger.critical(
        "[agi_improvement_cycle] CIRCUIT OPEN: %d consecutive TRANSIENT failures — halting cycle",
        _consecutive_failures,
    )


def _alert_permanent_failure(stage: str, exc: BaseException) -> None:
    """Send a ProductionMonitor alert for a PERMANENT stage failure."""
    try:
        from backend.core.monitoring import ProductionMonitor

        ProductionMonitor().send_alert(
            severity="critical",
            message=f"AGI cycle PERMANENT failure in stage '{stage}': {exc}",
            details={"stage": stage, "error_type": "PERMANENT", "exception": str(exc)},
        )
    except Exception as alert_err:
        logger.warning(
            "[agi_improvement_cycle] ProductionMonitor alert failed: %s", alert_err
        )


def _record_transient_failure(stage: str, exc: BaseException) -> None:
    """Increment the consecutive-failure counter and open the circuit at threshold."""
    global _consecutive_failures
    _consecutive_failures += 1
    logger.error(
        "[agi_improvement_cycle] TRANSIENT failure in stage '%s' (%d/%d): %s",
        stage,
        _consecutive_failures,
        _TRANSIENT_FAILURE_THRESHOLD,
        exc,
        exc_info=True,
    )
    if _consecutive_failures >= _TRANSIENT_FAILURE_THRESHOLD:
        _open_circuit()


def _reset_circuit() -> None:
    """Reset failure counter after a fully successful cycle."""
    global _consecutive_failures, _circuit_open
    if _consecutive_failures or _circuit_open:
        logger.info(
            "[agi_improvement_cycle] resetting TRANSIENT failure counter (was %d)",
            _consecutive_failures,
        )
    _consecutive_failures = 0
    _circuit_open = False


