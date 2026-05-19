"""
External Rate Limiter for API calls with 429 handling and exponential backoff.

This module provides an async rate limiter that:
- Detects HTTP 429 responses
- Parses Retry-After header for server guidance
- Falls back to exponential backoff with jitter when no Retry-After
- Integrates with the existing CircuitBreaker for failure tracking
- Supports per-API configurable rate limits
"""

import asyncio
import functools
import random
import time
from typing import Any, Callable

from loguru import logger

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker
from backend.core.errors import RateLimitError


class ExternalRateLimiter:
    """Rate limiter for external API calls with 429 handling and circuit breaker integration."""

    def __init__(
        self,
        name: str,
        max_calls_per_minute: int,
        circuit_breaker: CircuitBreaker | None = None,
        backoff_base: float | None = None,
        max_delay: float | None = None,
    ):
        """
        Initialize the rate limiter.

        Args:
            name: Unique identifier for this rate limiter (e.g., "gamma", "kalshi")
            max_calls_per_minute: Maximum API calls allowed per minute
            circuit_breaker: Optional CircuitBreaker instance; creates one if not provided
            backoff_base: Base multiplier for exponential backoff (default: settings.RATE_LIMIT_BACKOFF_BASE)
            max_delay: Maximum delay between retries (default: settings.RATE_LIMIT_MAX_DELAY)
        """
        self.name = name
        self.max_calls_per_minute = max_calls_per_minute
        self.backoff_base = backoff_base if backoff_base is not None else settings.RATE_LIMIT_BACKOFF_BASE
        self.max_delay = max_delay if max_delay is not None else settings.RATE_LIMIT_MAX_DELAY

        # Use provided circuit breaker or create one with settings-based defaults
        self._circuit_breaker = circuit_breaker or CircuitBreaker(
            name=f"{name}_circuit",
            failure_threshold=settings.CB_FAILURE_THRESHOLD,
            recovery_timeout=settings.CB_RECOVERY_TIMEOUT,
            half_open_max=settings.CB_HALF_OPEN_MAX,
        )

        # Token bucket for rate limiting
        self._tokens = max_calls_per_minute
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Return the circuit breaker instance for this rate limiter."""
        return self._circuit_breaker

    def _get_retry_after(self, response_headers: dict[str, str]) -> float | None:
        """
        Parse the Retry-After header from HTTP response.

        Args:
            response_headers: Response headers dict

        Returns:
            Wait time in seconds if Retry-After is present, None otherwise
        """
        retry_after = response_headers.get("Retry-After")
        if retry_after is None:
            return None

        try:
            # Retry-After can be seconds (integer) or HTTP-date
            # We only handle seconds format for simplicity
            return float(retry_after)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid Retry-After header value: %s", retry_after
            )
            return None

    def _calculate_backoff_delay(self, attempt: int) -> float:
        """
        Calculate exponential backoff delay with jitter.

        Args:
            attempt: Current retry attempt (1-indexed)

        Returns:
            Delay in seconds with jitter
        """
        # Exponential backoff: base * 2^(attempt-1)
        exponential_delay = self.backoff_base * (2 ** (attempt - 1))
        # Add random jitter (0.5x to 1.5x)
        jitter = random.uniform(0.5, 1.5)
        delay = min(exponential_delay * jitter, self.max_delay)
        return delay

    async def _wait_for_token(self) -> None:
        """
        Wait for a rate limit token to become available.
        Uses token bucket algorithm with refill.
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update

            # Refill tokens based on elapsed time
            tokens_to_add = (elapsed / 60.0) * self.max_calls_per_minute
            self._tokens = min(
                self._tokens + tokens_to_add, self.max_calls_per_minute
            )
            self._last_update = now

            # Wait if no tokens available
            wait_time = 0.0
            while self._tokens < 1:
                # Calculate time until next token
                tokens_needed = 1 - self._tokens
                wait_time = (tokens_needed / self.max_calls_per_minute) * 60.0
                self._tokens = 0
                self._last_update = now

        if wait_time > 0:
            await asyncio.sleep(wait_time)

            # Re-acquire lock after sleep to refill tokens
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_update
                tokens_to_add = (elapsed / 60.0) * self.max_calls_per_minute
                self._tokens = min(
                    self._tokens + tokens_to_add, self.max_calls_per_minute
                )
                self._last_update = now

    async def _handle_rate_limit(
        self, response_headers: dict[str, str], attempt: int, retry_after: float | None = None
    ) -> float:
        """
        Handle a 429 rate limit response.

        Args:
            response_headers: Response headers from the 429 response
            attempt: Current retry attempt (1-indexed)
            retry_after: Retry-After value from RateLimitError.retry_after (takes precedence)

        Returns:
            Wait time in seconds before retry
        """
        # If retry_after is passed from RateLimitError, use it directly (no jitter)
        if retry_after is not None:
            logger.info(
                "Rate limited by %s, retry after %.1fs (from RateLimitError.retry_after)",
                self.name,
                retry_after,
            )
            return retry_after

        # Try to get Retry-After from headers
        header_retry_after = self._get_retry_after(response_headers)
        if header_retry_after is not None:
            logger.info(
                "Rate limited by %s, retry after %.1fs (from Retry-After header)",
                self.name,
                header_retry_after,
            )
            return header_retry_after

        # Fall back to exponential backoff
        delay = self._calculate_backoff_delay(attempt)
        logger.warning(
            "Rate limited by %s, backing off for %.1fs (attempt %d)",
            self.name,
            delay,
            attempt,
        )
        return delay

    async def call(
        self,
        func: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a function with rate limiting and 429 handling.

        Args:
            func: The async function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            The return value from func

        Raises:
            RateLimitError: If rate limit is hit and max retries exhausted
            CircuitOpenError: If circuit breaker is open
            Exception: Any other exception from func
        """
        max_attempts = 5  # Max retry attempts after rate limit

        for attempt in range(1, max_attempts + 1):
            try:
                # Wait for rate limit token
                await self._wait_for_token()

                # Check circuit breaker
                result = await self._circuit_breaker.call(func, *args, **kwargs)

                return result

            except RateLimitError as e:
                # Get Retry-After from error directly or from headers
                response_headers = {}
                if e.details and "headers" in e.details:
                    response_headers = e.details["headers"]

                # Calculate wait time (uses Retry-After if available, or handles 429)
                wait_time = await self._handle_rate_limit(response_headers, attempt, e.retry_after)

                # Rate limit errors are transient - don't trip circuit breaker permanently
                # await self._circuit_breaker._on_failure()

                # Wait before retry
                await asyncio.sleep(wait_time)
                continue  # Retry with next attempt

            except Exception:
                # For non-rate-limit errors, let circuit breaker handle it
                logger.exception(f"ExternalRateLimiter {self.name}: unexpected error during rate-limited call")
                raise

        # Max attempts exhausted
        logger.error(
            "Max retry attempts exhausted for %s after %d attempts",
            self.name,
            max_attempts,
        )
        raise RateLimitError(
            f"Max retry attempts exhausted for {self.name}",
            source=self.name,
            status_code=429,
        )

    async def __aenter__(self) -> "ExternalRateLimiter":
        """Async context manager entry."""
        return self

    async def __aexit__(self, *args: Any) -> bool:
        """No cleanup needed for rate limiter."""
        return False


def rate_limited(
    name: str,
    max_calls_per_minute: int,
    backoff_base: float | None = None,
    max_delay: float | None = None,
):
    """
    Decorator for rate limiting external API calls.

    Args:
        name: Unique identifier for this rate limiter
        max_calls_per_minute: Maximum API calls per minute
        backoff_base: Base multiplier for exponential backoff (default: settings.RATE_LIMIT_BACKOFF_BASE)
        max_delay: Maximum delay between retries (default: settings.RATE_LIMIT_MAX_DELAY)

    Returns:
        Decorated function with rate limiting
    """

    def decorator(func: Callable) -> Callable:
        # Create a rate limiter instance per function
        limiter = ExternalRateLimiter(
            name=name,
            max_calls_per_minute=max_calls_per_minute,
            backoff_base=backoff_base,
            max_delay=max_delay,
        )

        if not asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                # For sync functions, run in event loop
                import asyncio

                return asyncio.run(
                    limiter.call(func, *args, **kwargs)
                )

            return sync_wrapper

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await limiter.call(func, *args, **kwargs)

        return async_wrapper

    return decorator


class TokenBucketRateLimiter:
    """Token bucket rate limiter for order submission.

    Enforces:
    - Per-market: max 1 order per 10 seconds
    - Global: max 3 orders per second
    """

    def __init__(
        self,
        per_market_limit: int = 1,
        per_market_window: float = 10.0,
        global_limit: int = 3,
        global_window: float = 1.0,
    ):
        self.per_market_limit = per_market_limit
        self.per_market_window = per_market_window
        self.global_limit = global_limit
        self.global_window = global_window
        self._market_timestamps: dict[str, list[float]] = {}
        self._global_timestamps: list[float] = []

    def acquire(self, market_id: str) -> None:
        """Acquire a token for the given market. Raises RateLimitError if limit exceeded."""
        now = time.monotonic()

        # Clean up old timestamps (sliding window)
        cutoff = now - self.per_market_window
        if market_id in self._market_timestamps:
            self._market_timestamps[market_id] = [
                t for t in self._market_timestamps[market_id] if t > cutoff
            ]

        global_cutoff = now - self.global_window
        self._global_timestamps = [t for t in self._global_timestamps if t > global_cutoff]

        # Check per-market limit
        market_count = len(self._market_timestamps.get(market_id, []))
        if market_count >= self.per_market_limit:
            raise RateLimitError(
                f"Per-market rate limit exceeded for {market_id}: "
                f"{market_count} orders in {self.per_market_window}s (max {self.per_market_limit})"
            )

        # Check global limit
        if len(self._global_timestamps) >= self.global_limit:
            raise RateLimitError(
                f"Global rate limit exceeded: "
                f"{len(self._global_timestamps)} orders in {self.global_window}s (max {self.global_limit})"
            )

        # Record this order
        if market_id not in self._market_timestamps:
            self._market_timestamps[market_id] = []
        self._market_timestamps[market_id].append(now)
        self._global_timestamps.append(now)

    def reset(self) -> None:
        """Clear all rate limit state."""
        self._market_timestamps.clear()
        self._global_timestamps.clear()
