"""
Circuit breaker implementation using pybreaker library.

Provides circuit breakers for:
- Database operations (fail_max=5, timeout=60s)
- Polymarket API calls (fail_max=3, timeout=30s)
- Kalshi API calls (fail_max=3, timeout=30s)
- Redis operations (fail_max=5, timeout=60s)

Circuit breaker states:
- CLOSED: Normal operation, requests pass through
- OPEN: Too many failures, requests fail fast without calling the protected function
- HALF_OPEN: Testing recovery, limited requests allowed to check if service recovered
"""

from typing import Any, Callable
from functools import wraps

from loguru import logger

import pybreaker


class CircuitBreakerListener(pybreaker.CircuitBreakerListener):
    """Listener to log circuit breaker state transitions."""

    def state_change(
        self,
        cb: pybreaker.CircuitBreaker,
        old_state: pybreaker.CircuitBreakerState,
        new_state: pybreaker.CircuitBreakerState,
    ) -> None:
        """Log state transitions."""
        logger.warning(
            f"CircuitBreaker '{cb.name}': {old_state.name} -> {new_state.name}"
        )

    def before_call(
        self, cb: pybreaker.CircuitBreaker, func: Callable, *args: Any, **kwargs: Any
    ) -> None:
        """Called before the circuit breaker calls the protected function."""
        logger.debug(f"CircuitBreaker '{cb.name}': calling {func.__name__}")

    def failure(self, cb: pybreaker.CircuitBreaker, exc: Exception) -> None:
        """Called when a failure occurs."""
        logger.debug(f"CircuitBreaker '{cb.name}': failure - {exc}")

    def success(self, cb: pybreaker.CircuitBreaker) -> None:
        """Called when a call succeeds."""
        logger.debug(f"CircuitBreaker '{cb.name}': success")


# Create listener instance
listener = CircuitBreakerListener()


# Database circuit breaker
db_breaker = pybreaker.CircuitBreaker(
    fail_max=5, reset_timeout=60, name="database", listeners=[listener]
)


# Polymarket API circuit breaker
polymarket_breaker = pybreaker.CircuitBreaker(
    fail_max=3, reset_timeout=30, name="polymarket_api", listeners=[listener]
)


# Kalshi API circuit breaker
kalshi_breaker = pybreaker.CircuitBreaker(
    fail_max=3, reset_timeout=30, name="kalshi_api", listeners=[listener]
)


# Redis circuit breaker
redis_breaker = pybreaker.CircuitBreaker(
    fail_max=5, reset_timeout=60, name="redis", listeners=[listener]
)


def with_db_breaker(func: Callable) -> Callable:
    """Decorator to wrap database operations with circuit breaker."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return db_breaker.call(func, *args, **kwargs)

    return wrapper


def with_polymarket_breaker(func: Callable) -> Callable:
    """Decorator to wrap Polymarket API calls with circuit breaker."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return polymarket_breaker.call(func, *args, **kwargs)

    return wrapper


def with_kalshi_breaker(func: Callable) -> Callable:
    """Decorator to wrap Kalshi API calls with circuit breaker."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return kalshi_breaker.call(func, *args, **kwargs)

    return wrapper


def with_redis_breaker(func: Callable) -> Callable:
    """Decorator to wrap Redis operations with circuit breaker."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return redis_breaker.call(func, *args, **kwargs)

    return wrapper


def get_breaker_status() -> dict[str, dict[str, Any]]:
    """
    Get status of all circuit breakers for health check endpoint.

    Returns:
        Dictionary with breaker name as key and status dict as value.
        Status includes: state, fail_counter, reset_timeout, fail_max
    """
    breakers = {
        "database": db_breaker,
        "polymarket_api": polymarket_breaker,
        "kalshi_api": kalshi_breaker,
        "redis": redis_breaker,
    }

    status = {}
    for name, breaker in breakers.items():
        status[name] = {
            "state": breaker.current_state,
            "fail_counter": breaker.fail_counter,
            "reset_timeout": breaker.reset_timeout,
            "fail_max": breaker.fail_max,
        }

    return status
