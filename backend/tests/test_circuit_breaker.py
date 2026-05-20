import asyncio
import pytest
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError, State


async def failing_func():
    raise ValueError("boom")


async def succeeding_func():
    return "ok"


@pytest.mark.asyncio
async def test_starts_closed():
    cb = CircuitBreaker("test", failure_threshold=3)
    assert cb.state == State.CLOSED


@pytest.mark.asyncio
async def test_opens_after_threshold_failures():
    cb = CircuitBreaker("test", failure_threshold=3)
    for _ in range(3):
        with pytest.raises(ValueError):
            await cb.call(failing_func)
    assert cb.state == State.OPEN


@pytest.mark.asyncio
async def test_raises_circuit_open_when_open():
    cb = CircuitBreaker("test", failure_threshold=2)
    for _ in range(2):
        with pytest.raises(ValueError):
            await cb.call(failing_func)
    assert cb.state == State.OPEN
    with pytest.raises(CircuitOpenError):
        await cb.call(succeeding_func)


@pytest.mark.asyncio
async def test_half_open_after_recovery_timeout():
    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
    with pytest.raises(ValueError):
        await cb.call(failing_func)
    assert cb.state == State.OPEN
    await asyncio.sleep(0.15)
    assert cb.state == State.HALF_OPEN


@pytest.mark.asyncio
async def test_closes_after_success_in_half_open():
    cb = CircuitBreaker(
        "test", failure_threshold=1, recovery_timeout=0.1, half_open_max=1
    )
    with pytest.raises(ValueError):
        await cb.call(failing_func)
    await asyncio.sleep(0.15)
    assert cb.state == State.HALF_OPEN
    result = await cb.call(succeeding_func)
    assert result == "ok"
    assert cb.state == State.CLOSED


@pytest.mark.asyncio
async def test_reopens_on_failure_in_half_open():
    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
    with pytest.raises(ValueError):
        await cb.call(failing_func)
    await asyncio.sleep(0.15)
    assert cb.state == State.HALF_OPEN
    with pytest.raises(ValueError):
        await cb.call(failing_func)
    assert cb.state == State.OPEN


@pytest.mark.asyncio
async def test_reset():
    cb = CircuitBreaker("test", failure_threshold=2)
    for _ in range(2):
        with pytest.raises(ValueError):
            await cb.call(failing_func)
    assert cb.state == State.OPEN
    cb.reset()
    assert cb.state == State.CLOSED
    assert cb.failure_count == 0
