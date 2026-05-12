from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker as CustomCircuitBreaker

_is_pybreaker_available = False

try:
    import pybreaker
    _is_pybreaker_available = True
except ImportError:
    pass

_USE_PYBREAKER = getattr(settings, "CB_USE_PYBREAKER", False) and _is_pybreaker_available

if _is_pybreaker_available:
    import logging
    from typing import Any, Callable
    from functools import wraps

    logger = logging.getLogger(__name__)

    class CircuitBreakerListener(pybreaker.CircuitBreakerListener):
        def state_change(self, cb, old_state, new_state):
            logger.warning(f"CircuitBreaker '{cb.name}': {old_state.name} -> {new_state.name}")


class UnifiedCircuitBreaker:
    def __init__(self, name, failure_threshold=None, recovery_timeout=None, half_open_max=None):
        self.name = name
        if _USE_PYBREAKER and _is_pybreaker_available:
            self._backend = pybreaker.CircuitBreaker(
                fail_max=failure_threshold or settings.CB_FAILURE_THRESHOLD,
                reset_timeout=recovery_timeout or settings.CB_RECOVERY_TIMEOUT,
                name=name,
                listeners=[CircuitBreakerListener()],
            )
            self._is_pybreaker = True
        else:
            self._backend = CustomCircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                half_open_max=half_open_max,
            )
            self._is_pybreaker = False

    async def call(self, func, *args, **kwargs):
        if self._is_pybreaker:
            return self._backend.call(func, *args, **kwargs)
        return await self._backend.call(func, *args, **kwargs)

    @property
    def state(self):
        if self._is_pybreaker:
            return self._backend.current_state
        return self._backend.state

    def current_state(self):
        return self.state