"""MiroFish monitoring service with circuit breaker pattern.

Implements a state machine for resilient MiroFish API monitoring:
- CLOSED: Normal operation, requests pass through
- OPEN: Too many failures, requests blocked
- HALF_OPEN: Testing recovery, limited requests allowed

State transitions:
- CLOSED → OPEN: After 3 consecutive failures
- OPEN → HALF_OPEN: After 30s timeout
- HALF_OPEN → CLOSED: After 1 successful request
- HALF_OPEN → OPEN: If request fails during recovery
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any
from collections import deque

from loguru import logger


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class HealthMetrics:
    status: str
    latency_ms: float
    error_rate: float
    circuit_breaker_state: str
    total_requests: int
    failed_requests: int
    last_success_time: Optional[str] = None
    last_failure_time: Optional[str] = None
    consecutive_failures: int = 0


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 3
    recovery_timeout: float = 30.0
    success_threshold: int = 1
    request_timeout: float = 10.0


class MiroFishMonitor:
    """Monitors MiroFish API health with circuit breaker protection.

    Tracks API call latencies, error rates, and manages circuit breaker state
    to prevent cascading failures when MiroFish is unavailable.
    """

    def __init__(
        self,
        mirofish_client=None,
        config: Optional[CircuitBreakerConfig] = None
    ):
        self.client = mirofish_client
        self.config = config or CircuitBreakerConfig()

        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._last_failure_time: Optional[float] = None
        self._last_success_time: Optional[float] = None
        self._state_change_time = time.time()

        self._total_requests = 0
        self._failed_requests = 0
        self._latencies: deque = deque(maxlen=100)

        self._alert_thresholds = {
            "latency_warn_ms": 10000,
            "error_rate_warn_pct": 10.0
        }

        logger.info(
            f"MiroFish monitor initialized: "
            f"failure_threshold={self.config.failure_threshold}, "
            f"recovery_timeout={self.config.recovery_timeout}s"
        )

    @property
    def state(self) -> CircuitState:
        return self._state

    def is_mirofish_healthy(self) -> bool:
        """Check if MiroFish is healthy based on circuit breaker state.

        Returns:
            True if circuit is CLOSED or HALF_OPEN, False if OPEN
        """
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._state_change_time
            if elapsed >= self.config.recovery_timeout:
                self._transition_to(CircuitState.HALF_OPEN)
                return True
            return False

        return True

    async def call_with_circuit_breaker(
        self,
        operation: str,
        *args,
        **kwargs
    ) -> Optional[Any]:
        """Execute operation with circuit breaker protection.

        Args:
            operation: Method name to call on mirofish_client
            *args: Positional arguments for the operation
            **kwargs: Keyword arguments for the operation

        Returns:
            Operation result or None if circuit is OPEN
        """
        if not self.is_mirofish_healthy():
            logger.warning(
                f"Circuit breaker OPEN - blocking {operation} call"
            )
            return None

        if self._state == CircuitState.HALF_OPEN:
            logger.info(f"Circuit breaker HALF_OPEN - testing recovery with {operation}")

        start_time = time.time()
        self._total_requests += 1

        try:
            if self.client is None:
                raise RuntimeError("MiroFish client not initialized")

            method = getattr(self.client, operation)

            result = await asyncio.wait_for(
                method(*args, **kwargs),
                timeout=self.config.request_timeout
            )

            latency_ms = (time.time() - start_time) * 1000
            self._latencies.append(latency_ms)

            self._record_success(latency_ms)

            if latency_ms > self._alert_thresholds["latency_warn_ms"]:
                logger.warning(
                    f"MiroFish high latency: {latency_ms:.2f}ms "
                    f"(threshold: {self._alert_thresholds['latency_warn_ms']}ms)"
                )

            return result

        except asyncio.TimeoutError as e:
            latency_ms = (time.time() - start_time) * 1000
            self._record_failure(f"Timeout after {latency_ms:.2f}ms")
            logger.error(f"MiroFish {operation} timeout: {e}")
            return None

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            self._record_failure(f"{type(e).__name__}: {str(e)}")
            logger.error(f"MiroFish {operation} error: {e}", exc_info=True)
            return None

    def _record_success(self, latency_ms: float):
        """Record successful API call and update circuit breaker state."""
        self._consecutive_failures = 0
        self._consecutive_successes += 1
        self._last_success_time = time.time()

        logger.debug(
            f"MiroFish call success: latency={latency_ms:.2f}ms, "
            f"consecutive_successes={self._consecutive_successes}"
        )

        if self._state == CircuitState.HALF_OPEN:
            if self._consecutive_successes >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)

    def _record_failure(self, error_msg: str):
        """Record failed API call and update circuit breaker state."""
        self._failed_requests += 1
        self._consecutive_failures += 1
        self._consecutive_successes = 0
        self._last_failure_time = time.time()

        logger.warning(
            f"MiroFish call failure: {error_msg}, "
            f"consecutive_failures={self._consecutive_failures}"
        )

        error_rate = self.get_error_rate()
        if error_rate > self._alert_thresholds["error_rate_warn_pct"]:
            logger.warning(
                f"MiroFish high error rate: {error_rate:.2f}% "
                f"(threshold: {self._alert_thresholds['error_rate_warn_pct']}%)"
            )

        if self._state == CircuitState.CLOSED:
            if self._consecutive_failures >= self.config.failure_threshold:
                self._transition_to(CircuitState.OPEN)

        elif self._state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.OPEN)

    def _transition_to(self, new_state: CircuitState):
        """Transition circuit breaker to new state with logging."""
        old_state = self._state
        self._state = new_state
        self._state_change_time = time.time()

        timestamp = datetime.now(timezone.utc).isoformat()

        logger.warning(
            f"Circuit breaker state transition: {old_state.value} → {new_state.value} "
            f"at {timestamp} "
            f"(consecutive_failures={self._consecutive_failures}, "
            f"consecutive_successes={self._consecutive_successes})"
        )

        if new_state == CircuitState.OPEN:
            logger.error(
                f"MiroFish circuit breaker OPEN - blocking requests for "
                f"{self.config.recovery_timeout}s"
            )
        elif new_state == CircuitState.HALF_OPEN:
            logger.info("MiroFish circuit breaker HALF_OPEN - testing recovery")
        elif new_state == CircuitState.CLOSED:
            logger.info("MiroFish circuit breaker CLOSED - normal operation resumed")

    def get_health_metrics(self) -> HealthMetrics:
        """Get current health metrics for monitoring endpoint."""
        avg_latency = sum(self._latencies) / len(self._latencies) if self._latencies else 0.0
        error_rate = self.get_error_rate()

        last_success = None
        if self._last_success_time:
            last_success = datetime.fromtimestamp(
                self._last_success_time, tz=timezone.utc
            ).isoformat()

        last_failure = None
        if self._last_failure_time:
            last_failure = datetime.fromtimestamp(
                self._last_failure_time, tz=timezone.utc
            ).isoformat()

        status = "healthy" if self.is_mirofish_healthy() else "unhealthy"

        return HealthMetrics(
            status=status,
            latency_ms=avg_latency,
            error_rate=error_rate,
            circuit_breaker_state=self._state.value,
            total_requests=self._total_requests,
            failed_requests=self._failed_requests,
            last_success_time=last_success,
            last_failure_time=last_failure,
            consecutive_failures=self._consecutive_failures
        )

    def get_error_rate(self) -> float:
        """Calculate error rate as percentage."""
        if self._total_requests == 0:
            return 0.0
        return (self._failed_requests / self._total_requests) * 100.0

    def reset(self):
        """Reset circuit breaker to initial state (for testing/recovery)."""
        old_state = self._state
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._state_change_time = time.time()

        logger.info(f"Circuit breaker manually reset from {old_state.value} to CLOSED")

    def get_state_info(self) -> Dict[str, Any]:
        """Get detailed circuit breaker state information."""
        time_in_state = time.time() - self._state_change_time

        return {
            "state": self._state.value,
            "time_in_state_seconds": round(time_in_state, 2),
            "consecutive_failures": self._consecutive_failures,
            "consecutive_successes": self._consecutive_successes,
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout": self.config.recovery_timeout,
                "success_threshold": self.config.success_threshold,
                "request_timeout": self.config.request_timeout
            }
        }


_monitor_instance: Optional[MiroFishMonitor] = None


def get_monitor(mirofish_client=None) -> MiroFishMonitor:
    """Get or create singleton MiroFish monitor instance."""
    global _monitor_instance

    if _monitor_instance is None:
        _monitor_instance = MiroFishMonitor(mirofish_client=mirofish_client)

    return _monitor_instance


def reset_monitor():
    """Reset monitor singleton (for testing)."""
    global _monitor_instance
    _monitor_instance = None
