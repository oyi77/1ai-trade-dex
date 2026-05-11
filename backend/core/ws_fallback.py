"""WebSocket-first execution with REST fallback on disconnect.

Provides a context manager that detects WS connection state and routes
strategy execution to the appropriate path:
- WS connected: strategies receive events via EventBus → on_market_event()
- WS disconnected: activates REST fallback with rate-limit protection
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class ExecutionMode(Enum):
    WS = auto()
    REST_FALLBACK = auto()


@dataclass
class FallbackState:
    mode: ExecutionMode = ExecutionMode.WS
    switched_at: float = field(default_factory=time.time)
    rest_call_count: int = 0
    rest_last_call: float = 0.0
    consecutive_failures: int = 0
    backoff_seconds: float = 30.0


class WsFirstExecutor:
    """Manages WS-first execution with auto REST fallback."""

    def __init__(
        self,
        strategy_name: str,
        rest_interval: float = 300.0,
        max_rest_interval: float = 600.0,
        breaker_threshold: int = 5,
        breaker_timeout: float = 300.0,
    ):
        self._strategy_name = strategy_name
        self._rest_interval = rest_interval
        self._max_rest_interval = max_rest_interval
        self._breaker_threshold = breaker_threshold
        self._breaker_timeout = breaker_timeout
        self._state = FallbackState()

    @property
    def mode(self) -> ExecutionMode:
        return self._state.mode

    @property
    def ws_connected(self) -> bool:
        from backend.core.event_bus import event_bus
        return event_bus.ws_connected

    async def on_ws_disconnected(self) -> None:
        if self._state.mode == ExecutionMode.REST_FALLBACK:
            return
        self._state.mode = ExecutionMode.REST_FALLBACK
        self._state.switched_at = time.time()
        self._state.rest_call_count = 0
        self._state.consecutive_failures = 0
        self._state.backoff_seconds = min(self._rest_interval, 30.0)
        logger.warning("Strategy '%s' switched to REST fallback (WS disconnected)", self._strategy_name)

    async def on_ws_reconnected(self) -> None:
        if self._state.mode == ExecutionMode.WS:
            return
        self._state.mode = ExecutionMode.WS
        elapsed = time.time() - self._state.switched_at
        logger.info("Strategy '%s' switched back to WS (disconnected for %.0fs, %d REST calls made)",
                     self._strategy_name, elapsed, self._state.rest_call_count)

    async def execute_rest(self, rest_handler: Callable[[], Awaitable]) -> bool:
        """Call REST handler with rate-limit and circuit-breaker protection."""
        now = time.time()

        if self._state.consecutive_failures >= self._breaker_threshold:
            if now - self._state.rest_last_call < self._breaker_timeout:
                logger.debug("Strategy '%s' REST circuit breaker OPEN (%d failures)", self._strategy_name, self._state.consecutive_failures)
                return False
            self._state.consecutive_failures = 0
            self._state.backoff_seconds = self._rest_interval
            logger.info("Strategy '%s' REST circuit breaker reset after timeout", self._strategy_name)

        if now - self._state.rest_last_call < self._state.backoff_seconds:
            return False

        try:
            self._state.rest_last_call = now
            await rest_handler()
            self._state.rest_call_count += 1
            self._state.consecutive_failures = 0
            self._state.backoff_seconds = self._rest_interval
            return True
        except Exception as exc:
            self._state.consecutive_failures += 1
            self._state.rest_call_count += 1
            self._state.backoff_seconds = min(
                self._rest_interval * (2 ** self._state.consecutive_failures),
                self._max_rest_interval,
            )
            logger.warning("Strategy '%s' REST call failed (%d/%d): %s",
                           self._strategy_name, self._state.consecutive_failures, self._breaker_threshold, exc)
            return False

    def get_status(self) -> dict:
        return {
            "strategy": self._strategy_name,
            "mode": self._state.mode.name,
            "ws_connected": self.ws_connected,
            "rest_calls": self._state.rest_call_count,
            "rest_failures": self._state.consecutive_failures,
            "rest_backoff_s": round(self._state.backoff_seconds, 1),
            "switched_at": self._state.switched_at,
        }
