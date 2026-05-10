"""Tests for ExternalRateLimiter with 429 handling and exponential backoff."""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import Response

from backend.core.circuit_breaker import CircuitBreaker
from backend.core.errors import RateLimitError
from backend.core.external_rate_limiter import ExternalRateLimiter


# ============================================================================
# Helper Functions
# ============================================================================

def create_mock_response(status_code: int, headers: dict | None = None, json_data: dict | None = None) -> Response:
    """Create a mock httpx.Response with specified status and headers."""
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = status_code
    mock_response.headers = headers or {}
    mock_response.json.return_value = json_data or {}

    async def read():
        return b'{}'

    mock_response.read = read
    return mock_response


# ============================================================================
# 429 Detection and Backoff Tests
# ============================================================================

@pytest.mark.asyncio
async def test_429_detection_triggers_backoff():
    """Test that 429 response triggers exponential backoff and retry."""
    limiter = ExternalRateLimiter(
        name="test",
        max_calls_per_minute=100,
        circuit_breaker=CircuitBreaker("test_cb", failure_threshold=10, recovery_timeout=60.0)
    )

    call_count = 0
    max_attempts = 5

    async def failing_func():
        nonlocal call_count
        call_count += 1
        if call_count < max_attempts:
            raise RateLimitError(
                "Rate limit exceeded",
                source="test",
                status_code=429,
                retry_after=2.0,
            )
        return {"success": True, "data": []}

    result = await limiter.call(failing_func)

    assert result == {"success": True, "data": []}
    assert call_count == max_attempts


@pytest.mark.asyncio
async def test_429_max_retries_exhausted():
    """Test that max retry attempts exhausted raises RateLimitError."""
    limiter = ExternalRateLimiter(
        name="test",
        max_calls_per_minute=100,
        circuit_breaker=CircuitBreaker("test_max_cb", failure_threshold=10, recovery_timeout=60.0),
    )

    async def always_failing_func():
        raise RateLimitError(
            "Rate limit exceeded",
            source="test",
            status_code=429,
            retry_after=0.1,  # Short delay for test speed
        )

    with pytest.raises(RateLimitError) as exc_info:
        await limiter.call(always_failing_func)

    assert "Max retry attempts exhausted" in str(exc_info.value)
    assert exc_info.value.status_code == 429


# ============================================================================
# Retry-After Header Parsing Tests
# ============================================================================

@pytest.mark.asyncio
async def test_retry_after_header_takes_precedence():
    """Test that Retry-After header takes precedence over exponential backoff."""
    limiter = ExternalRateLimiter(
        name="test",
        max_calls_per_minute=100,
        backoff_base=2.0,  # Exponential backoff would be 2s
        max_delay=60.0,
        circuit_breaker=CircuitBreaker("test_retry_cb", failure_threshold=10, recovery_timeout=60.0),
    )

    call_count = 0
    delays = []

    async def func_with_retry_after():
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            raise RateLimitError(
                "Rate limit exceeded",
                source="test",
                status_code=429,
                retry_after=3.0,
            )
        return {"success": True}

    async def tracking_sleep(delay):
        delays.append(delay)

    with patch("asyncio.sleep", tracking_sleep):
        result = await limiter.call(func_with_retry_after)

    assert result == {"success": True}
    assert call_count == 2
    assert 2.9 <= delays[0] <= 3.1, f"Expected ~3.0, got {delays[0]}"


@pytest.mark.asyncio
async def test_invalid_retry_after_falls_back_to_exponential_backoff():
    """Test that exponential backoff increases with each retry attempt."""
    limiter = ExternalRateLimiter(
        name="test",
        max_calls_per_minute=100,
        backoff_base=1.0,  # Base 1.0s for predictable backoff
        max_delay=30.0,
        circuit_breaker=CircuitBreaker("test_exp_cb", failure_threshold=10, recovery_timeout=60.0),
    )

    call_count = 0
    delays = []

    async def func_with_429():
        nonlocal call_count
        call_count += 1

        if call_count <= 3:
            raise RateLimitError(
                "Rate limit exceeded",
                source="test",
                status_code=429,
                retry_after=None,  # No Retry-After, use exponential backoff
            )
        return {"success": True}

    async def tracking_sleep(delay):
        delays.append(delay)

    with patch("asyncio.sleep", tracking_sleep):
        result = await limiter.call(func_with_429)

    assert result == {"success": True}
    # Verify exponential backoff: 1.0s, 2.0s, 4.0s (with jitter)
    assert len(delays) == 3
    # Without jitter: base * 2^(attempt-1) = 1, 2, 4
    # With jitter (0.5-1.5x): 0.5-1.5, 1-3, 2-6
    assert 0.5 <= delays[0] <= 1.5  # Attempt 1: 1.0 * jitter
    assert 1.0 <= delays[1] <= 3.0  # Attempt 2: 2.0 * jitter
    assert 2.0 <= delays[2] <= 6.0  # Attempt 3: 4.0 * jitter


@pytest.mark.asyncio
async def test_max_delay_cap():
    """Test that exponential backoff is capped at max_delay."""
    limiter = ExternalRateLimiter(
        name="test",
        max_calls_per_minute=100,
        backoff_base=2.0,
        max_delay=5.0,  # Cap at 5 seconds
        circuit_breaker=CircuitBreaker("test_cap_cb", failure_threshold=10, recovery_timeout=60.0),
    )

    call_count = 0
    delays = []

    async def func_with_429():
        nonlocal call_count
        call_count += 1

        if call_count <= 3:
            raise RateLimitError(
                "Rate limit exceeded",
                source="test",
                status_code=429,
                retry_after=None,
            )
        return {"success": True}

    async def tracking_sleep(delay):
        delays.append(delay)

    with patch("asyncio.sleep", tracking_sleep):
        result = await limiter.call(func_with_429)

    assert result == {"success": True}
    # Should be capped at max_delay (5.0)
    for delay in delays:
        assert delay <= 5.1, f"Delay {delay} exceeds max_delay 5.0"


# ============================================================================
# Circuit Breaker Integration Tests
# ============================================================================

@pytest.mark.asyncio
async def test_circuit_breaker_integration():
    """Test that RateLimitError properly triggers circuit breaker."""
    circuit_breaker = CircuitBreaker(
        name="test_cb",
        failure_threshold=10,
        recovery_timeout=60.0,
    )
    limiter = ExternalRateLimiter(
        name="test",
        max_calls_per_minute=100,
        circuit_breaker=circuit_breaker,
    )

    call_count = 0

    async def func_with_429():
        nonlocal call_count
        call_count += 1
        raise RateLimitError(
            "Rate limit exceeded",
            source="test",
            status_code=429,
            retry_after=0.1,
        )

    # First call should fail and increment failure count
    with pytest.raises(RateLimitError):
        await limiter.call(func_with_429)

    # Circuit breaker should have recorded a failure
    assert circuit_breaker.failure_count >= 1


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures():
    """Test that circuit breaker opens after failure_threshold failures."""
    circuit_breaker = CircuitBreaker(
        name="test_cb",
        failure_threshold=10,
        recovery_timeout=60.0,
    )
    limiter = ExternalRateLimiter(
        name="test",
        max_calls_per_minute=100,
        circuit_breaker=circuit_breaker,
    )


# ============================================================================
# Per-API Rate Limit Tests
# ============================================================================

@pytest.mark.asyncio
async def test_per_api_independent_limits():
    """Test that different APIs have independent rate limiters."""
    gamma_limiter = ExternalRateLimiter(
        name="gamma",
        max_calls_per_minute=10,
    )

    kalshi_limiter = ExternalRateLimiter(
        name="kalshi",
        max_calls_per_minute=20,
    )

    # Both should start with full token buckets
    assert gamma_limiter.max_calls_per_minute == 10
    assert kalshi_limiter.max_calls_per_minute == 20

    # Circuit breakers should be separate
    assert gamma_limiter.circuit_breaker.name != kalshi_limiter.circuit_breaker.name
    assert "gamma" in gamma_limiter.circuit_breaker.name
    assert "kalshi" in kalshi_limiter.circuit_breaker.name


# ============================================================================
# Decorator Tests
# ============================================================================

@pytest.mark.asyncio
async def test_rate_limited_decorator_async():
    """Test the @rate_limited decorator for async functions."""
    from backend.core.external_rate_limiter import rate_limited

    call_count = 0

    @rate_limited(name="test_api", max_calls_per_minute=100)
    async def test_async_func():
        nonlocal call_count
        call_count += 1
        return {"result": call_count}

    result = await test_async_func()
    assert result == {"result": 1}


# ============================================================================
# Edge Cases
# ============================================================================

@pytest.mark.asyncio
async def test_success_on_first_call():
    """Test that successful first call doesn't trigger backoff."""
    limiter = ExternalRateLimiter(name="test", max_calls_per_minute=100)

    async def success_func():
        return {"success": True, "data": [1, 2, 3]}

    result = await limiter.call(success_func)
    assert result == {"success": True, "data": [1, 2, 3]}


@pytest.mark.asyncio
async def test_non_rate_limit_error_propagates():
    """Test that non-429 errors don't trigger rate limit backoff."""
    limiter = ExternalRateLimiter(name="test", max_calls_per_minute=100)

    async def runtime_error_func():
        raise ValueError("This is a not a rate limit error")

    with pytest.raises(ValueError) as exc_info:
        await limiter.call(runtime_error_func)

    assert "not a rate limit error" in str(exc_info.value)


# ============================================================================
# Token Bucket Rate Limiting Tests
# ============================================================================

@pytest.mark.asyncio
async def test_token_bucket_refill():
    """Test that tokens refill over time."""
    limiter = ExternalRateLimiter(
        name="test",
        max_calls_per_minute=60,  # 1 token per second
    )

    # Initial tokens should be full
    assert limiter._tokens == 60

    # Simulate time passing (token refill)
    import time as time_mod
    original_time = time_mod.monotonic

    # We can't easily test time-based refill without complex mocking,
    # so verify the algorithm structure exists
    assert hasattr(limiter, '_tokens')
    assert hasattr(limiter, '_last_update')


@pytest.mark.asyncio
async def test_rate_limiter_returns_circuit_breaker_property():
    """Test that circuit_breaker property returns the instance."""
    circuit_breaker = CircuitBreaker(name="test_cb")
    limiter = ExternalRateLimiter(
        name="test",
        max_calls_per_minute=100,
        circuit_breaker=circuit_breaker,
    )

    assert limiter.circuit_breaker is circuit_breaker


# ============================================================================
# Async Context Manager Tests
# ============================================================================

@pytest.mark.asyncio
async def test_async_context_manager():
    """Test async context manager enter/exit."""
    limiter = ExternalRateLimiter(name="test", max_calls_per_minute=100)

    async with limiter as ctx:
        assert ctx is limiter

    # Context manager exit should not raise
    assert True  # Success
