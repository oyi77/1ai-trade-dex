import asyncio
import functools
import logging
import time
from enum import Enum
from typing import Any, Callable

from backend.config import settings
from backend.core.errors import CircuitOpenError

logger = logging.getLogger(__name__)

_STATE_VALUES = {0: 0, 1: 1, 2: 2}


class State(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int | None = None,
        recovery_timeout: float | None = None,
        half_open_max: int | None = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold if failure_threshold is not None else settings.CB_FAILURE_THRESHOLD
        self.recovery_timeout = recovery_timeout if recovery_timeout is not None else settings.CB_RECOVERY_TIMEOUT
        self.half_open_max = half_open_max if half_open_max is not None else settings.CB_HALF_OPEN_MAX

        self._state = State.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: float | None = None
        self.last_state_change: float = time.monotonic()
        self._lock = asyncio.Lock()
        self._half_open_probes: int = 0  # active probe count during HALF_OPEN

    @property
    def state(self) -> str:
        if self._state == State.OPEN:
            if (
                self.last_failure_time is not None
                and time.monotonic() - self.last_failure_time >= self.recovery_timeout
            ):
                return State.HALF_OPEN
        return self._state

    async def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        is_half_open_probe = False

        async with self._lock:
            # Promote OPEN → HALF_OPEN once recovery_timeout has elapsed.
            # Do this inside the lock so at most one coroutine transitions.
            if self._state == State.OPEN:
                if (
                    self.last_failure_time is not None
                    and time.monotonic() - self.last_failure_time
                    >= self.recovery_timeout
                ):
                    self._transition(State.HALF_OPEN)
                    self._half_open_probes = 0
                else:
                    raise CircuitOpenError(self.name)

            if self._state == State.HALF_OPEN:
                if self._half_open_probes >= self.half_open_max:
                    # Limit concurrent probes to half_open_max — excess callers
                    # are rejected until a probe succeeds or fails.
                    raise CircuitOpenError(self.name)
                self._half_open_probes += 1
                is_half_open_probe = True

        try:
            result = await func(*args, **kwargs)
        except Exception as _e:
            await self._on_failure()
            logger.warning(f"Circuit breaker {self.name} caught error, failing ({self.failure_count}/{self.failure_threshold}): {_e}")
            raise
        finally:
            if is_half_open_probe:
                async with self._lock:
                    self._half_open_probes = max(0, self._half_open_probes - 1)

        await self._on_success()
        return result

    def __call__(self, func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await self.call(func, *args, **kwargs)

        return wrapper

    def reset(self) -> None:
        self._state = State.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.last_state_change = time.monotonic()
        logger.warning("CircuitBreaker '%s': manually reset to CLOSED", self.name)

    async def _on_failure(self) -> None:
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.monotonic()

            current_state = self._state
            logger.warning(
                "CircuitBreaker '%s' failure recorded: count=%d, state=%s",
                self.name,
                self.failure_count,
                current_state,
            )
            if current_state == State.HALF_OPEN:
                self._transition(State.OPEN)
            elif (
                current_state == State.CLOSED
                and self.failure_count >= self.failure_threshold
            ):
                self._transition(State.OPEN)

    async def _on_success(self) -> None:
        async with self._lock:
            current_state = self._state

            if current_state == State.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.half_open_max:
                    self._transition(State.CLOSED)
            elif current_state == State.CLOSED:
                self.failure_count = 0

    def _transition(self, new_state: State) -> None:
        old_state = self._state
        self._state = new_state
        self.last_state_change = time.monotonic()

        try:
            from backend.monitoring.metrics import set_circuit_breaker_state
            state_value = {State.OPEN: 0, State.HALF_OPEN: 1, State.CLOSED: 2}.get(new_state, 0)
            set_circuit_breaker_state(self.name, state_value)
        except Exception:
            pass

        if new_state == State.CLOSED:
            self.failure_count = 0
            self.success_count = 0
            self.last_failure_time = None
            self._half_open_probes = 0
        elif new_state == State.OPEN:
            self._half_open_probes = 0
            # Reset success count when tripping back to OPEN
            self.success_count = 0

        logger.warning(
            "CircuitBreaker '%s' TRANSITION: %s -> %s (failure_count was %d)",
            self.name,
            old_state,
            new_state,
            self.failure_count,
        )
