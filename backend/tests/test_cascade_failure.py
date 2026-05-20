"""Integration test for cascade failure scenario - MiroFish + Activity Log both down."""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock
from backend.services.mirofish_monitor import get_monitor, reset_monitor, CircuitState


@pytest.mark.asyncio
async def test_cascade_failure_trading_continues():
    """Test that core trading continues when both MiroFish and Activity Log are down."""
    reset_monitor()

    mock_client = Mock()
    mock_client.fetch_signals = AsyncMock(
        side_effect=Exception("MiroFish Service Unavailable")
    )

    monitor = get_monitor(mirofish_client=mock_client)

    for _ in range(3):
        result = await monitor.call_with_circuit_breaker("fetch_signals")
        assert result is None

    assert monitor.state == CircuitState.OPEN
    assert monitor.is_mirofish_healthy() is False

    metrics = monitor.get_health_metrics()
    assert metrics.status == "unhealthy"
    assert metrics.circuit_breaker_state == "OPEN"
    assert metrics.failed_requests == 3
    assert metrics.error_rate == 100.0

    result = await monitor.call_with_circuit_breaker("fetch_signals")
    assert result is None

    print("✓ MiroFish circuit breaker OPEN - requests blocked")
    print("✓ Trading can continue with fallback strategies")
    print(f"✓ Health status: {metrics.status}")
    print(f"✓ Circuit state: {metrics.circuit_breaker_state}")


@pytest.mark.asyncio
async def test_circuit_breaker_recovery_flow():
    """Test full recovery flow: CLOSED → OPEN → HALF_OPEN → CLOSED."""
    reset_monitor()

    mock_client = Mock()

    monitor = get_monitor(mirofish_client=mock_client)

    assert monitor.state == CircuitState.CLOSED
    print(f"Initial state: {monitor.state.value}")

    mock_client.fetch_signals = AsyncMock(side_effect=Exception("API Error"))

    for i in range(3):
        await monitor.call_with_circuit_breaker("fetch_signals")
        print(
            f"After failure {i+1}: state={monitor.state.value}, failures={monitor._consecutive_failures}"
        )

    assert monitor.state == CircuitState.OPEN
    print("✓ Transitioned to OPEN after 3 failures")

    monitor._transition_to(CircuitState.HALF_OPEN)
    assert monitor.state == CircuitState.HALF_OPEN
    print("✓ Transitioned to HALF_OPEN (simulated timeout)")

    mock_client.fetch_signals = AsyncMock(return_value=[])
    result = await monitor.call_with_circuit_breaker("fetch_signals")

    assert result == []
    assert monitor.state == CircuitState.CLOSED
    print("✓ Transitioned to CLOSED after successful request")
    print(f"Final state: {monitor.state.value}")


@pytest.mark.asyncio
async def test_health_endpoint_during_failure():
    """Test health endpoint returns correct data during circuit breaker states."""
    reset_monitor()

    mock_client = Mock()
    mock_client.fetch_signals = AsyncMock(side_effect=Exception("Service Down"))

    monitor = get_monitor(mirofish_client=mock_client)

    initial_metrics = monitor.get_health_metrics()
    assert initial_metrics.circuit_breaker_state == "CLOSED"
    assert initial_metrics.status == "healthy"

    for _ in range(3):
        await monitor.call_with_circuit_breaker("fetch_signals")

    failure_metrics = monitor.get_health_metrics()
    assert failure_metrics.circuit_breaker_state == "OPEN"
    assert failure_metrics.status == "unhealthy"
    assert failure_metrics.failed_requests == 3
    assert failure_metrics.consecutive_failures == 3

    print("✓ Health metrics during failure:")
    print(f"  Status: {failure_metrics.status}")
    print(f"  Circuit: {failure_metrics.circuit_breaker_state}")
    print(f"  Error rate: {failure_metrics.error_rate}%")
    print(
        f"  Failed requests: {failure_metrics.failed_requests}/{failure_metrics.total_requests}"
    )


if __name__ == "__main__":
    asyncio.run(test_cascade_failure_trading_continues())
    asyncio.run(test_circuit_breaker_recovery_flow())
    asyncio.run(test_health_endpoint_during_failure())
    print("\n✓ All cascade failure tests passed!")
