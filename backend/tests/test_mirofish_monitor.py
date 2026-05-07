"""Unit tests for MiroFish monitoring and circuit breaker."""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, Mock, patch
from backend.services.mirofish_monitor import (
    MiroFishMonitor,
    CircuitState,
    CircuitBreakerConfig,
    HealthMetrics,
    get_monitor,
    reset_monitor
)


@pytest.fixture
def mock_client():
    client = Mock()
    client.fetch_signals = AsyncMock(return_value=[])
    return client


@pytest.fixture
def monitor(mock_client):
    config = CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=30.0,
        success_threshold=1,
        request_timeout=10.0
    )
    return MiroFishMonitor(mirofish_client=mock_client, config=config)


@pytest.fixture
def fast_monitor(mock_client):
    config = CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=2.0,
        success_threshold=1,
        request_timeout=1.0
    )
    return MiroFishMonitor(mirofish_client=mock_client, config=config)


class TestCircuitBreakerStateTransitions:
    """Test circuit breaker state machine transitions."""
    
    def test_initial_state_is_closed(self, monitor):
        assert monitor.state == CircuitState.CLOSED
        assert monitor.is_mirofish_healthy() is True
    
    @pytest.mark.asyncio
    async def test_closed_to_open_after_threshold_failures(self, monitor, mock_client):
        mock_client.fetch_signals.side_effect = Exception("API Error")
        
        assert monitor.state == CircuitState.CLOSED
        
        await monitor.call_with_circuit_breaker("fetch_signals")
        assert monitor.state == CircuitState.CLOSED
        assert monitor._consecutive_failures == 1
        
        await monitor.call_with_circuit_breaker("fetch_signals")
        assert monitor.state == CircuitState.CLOSED
        assert monitor._consecutive_failures == 2
        
        await monitor.call_with_circuit_breaker("fetch_signals")
        assert monitor.state == CircuitState.OPEN
        assert monitor._consecutive_failures == 3
    
    @pytest.mark.asyncio
    async def test_open_to_half_open_after_timeout(self, fast_monitor, mock_client):
        mock_client.fetch_signals.side_effect = Exception("API Error")
        
        for _ in range(3):
            await fast_monitor.call_with_circuit_breaker("fetch_signals")
        
        assert fast_monitor.state == CircuitState.OPEN
        assert fast_monitor.is_mirofish_healthy() is False
        
        await asyncio.sleep(2.1)
        
        assert fast_monitor.is_mirofish_healthy() is True
        assert fast_monitor.state == CircuitState.HALF_OPEN
    
    @pytest.mark.asyncio
    async def test_half_open_to_closed_on_success(self, monitor, mock_client):
        mock_client.fetch_signals.side_effect = [
            Exception("Error 1"),
            Exception("Error 2"),
            Exception("Error 3"),
            []
        ]
        
        for _ in range(3):
            await monitor.call_with_circuit_breaker("fetch_signals")
        
        assert monitor.state == CircuitState.OPEN
        
        monitor._transition_to(CircuitState.HALF_OPEN)
        assert monitor.state == CircuitState.HALF_OPEN
        
        result = await monitor.call_with_circuit_breaker("fetch_signals")
        assert result == []
        assert monitor.state == CircuitState.CLOSED
    
    @pytest.mark.asyncio
    async def test_half_open_to_open_on_failure(self, monitor, mock_client):
        mock_client.fetch_signals.side_effect = Exception("API Error")
        
        for _ in range(3):
            await monitor.call_with_circuit_breaker("fetch_signals")
        
        assert monitor.state == CircuitState.OPEN
        
        monitor._transition_to(CircuitState.HALF_OPEN)
        assert monitor.state == CircuitState.HALF_OPEN
        
        await monitor.call_with_circuit_breaker("fetch_signals")
        assert monitor.state == CircuitState.OPEN


class TestRetryLogic:
    """Test exponential backoff retry logic."""
    
    @pytest.mark.asyncio
    async def test_successful_call_no_retry(self, monitor, mock_client):
        mock_client.fetch_signals.return_value = [{"signal": "data"}]
        
        result = await monitor.call_with_circuit_breaker("fetch_signals")
        
        assert result == [{"signal": "data"}]
        assert mock_client.fetch_signals.call_count == 1
        assert monitor._consecutive_failures == 0
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self, monitor, mock_client):
        async def slow_operation():
            await asyncio.sleep(15)
            return []
        
        mock_client.fetch_signals = slow_operation
        
        start = time.time()
        result = await monitor.call_with_circuit_breaker("fetch_signals")
        elapsed = time.time() - start
        
        assert result is None
        assert elapsed < 12
        assert monitor._consecutive_failures == 1


class TestHealthChecks:
    """Test health check functionality."""
    
    def test_is_healthy_when_closed(self, monitor):
        assert monitor.state == CircuitState.CLOSED
        assert monitor.is_mirofish_healthy() is True
    
    def test_is_unhealthy_when_open(self, monitor):
        monitor._transition_to(CircuitState.OPEN)
        assert monitor.is_mirofish_healthy() is False
    
    def test_is_healthy_when_half_open(self, monitor):
        monitor._transition_to(CircuitState.HALF_OPEN)
        assert monitor.is_mirofish_healthy() is True
    
    @pytest.mark.asyncio
    async def test_health_metrics_accuracy(self, monitor, mock_client):
        mock_client.fetch_signals.side_effect = [
            [],
            [],
            Exception("Error"),
            []
        ]
        
        await monitor.call_with_circuit_breaker("fetch_signals")
        await monitor.call_with_circuit_breaker("fetch_signals")
        await monitor.call_with_circuit_breaker("fetch_signals")
        await monitor.call_with_circuit_breaker("fetch_signals")
        
        metrics = monitor.get_health_metrics()
        
        assert metrics.total_requests == 4
        assert metrics.failed_requests == 1
        assert metrics.error_rate == 25.0
        assert metrics.consecutive_failures == 0
        assert metrics.last_success_time is not None


class TestAlertThresholds:
    """Test alert threshold detection."""
    
    @pytest.mark.asyncio
    async def test_high_latency_warning(self, monitor, mock_client, caplog):
        async def slow_fetch():
            await asyncio.sleep(0.1)
            return []
        
        mock_client.fetch_signals = slow_fetch
        monitor._alert_thresholds["latency_warn_ms"] = 50
        
        with caplog.at_level("WARNING"):
            await monitor.call_with_circuit_breaker("fetch_signals")
        
        assert any("high latency" in record.message.lower() for record in caplog.records)
    
    @pytest.mark.asyncio
    async def test_high_error_rate_warning(self, monitor, mock_client, caplog):
        mock_client.fetch_signals.side_effect = Exception("API Error")
        monitor._alert_thresholds["error_rate_warn_pct"] = 10.0
        
        with caplog.at_level("WARNING"):
            await monitor.call_with_circuit_breaker("fetch_signals")
        
        assert monitor.get_error_rate() == 100.0


class TestCircuitBreakerBlocking:
    """Test that circuit breaker blocks requests when OPEN."""
    
    @pytest.mark.asyncio
    async def test_open_circuit_blocks_requests(self, monitor, mock_client):
        mock_client.fetch_signals.side_effect = Exception("API Error")
        
        for _ in range(3):
            await monitor.call_with_circuit_breaker("fetch_signals")
        
        assert monitor.state == CircuitState.OPEN
        
        mock_client.fetch_signals.reset_mock()
        mock_client.fetch_signals.side_effect = None
        mock_client.fetch_signals.return_value = []
        
        result = await monitor.call_with_circuit_breaker("fetch_signals")
        
        assert result is None
        assert mock_client.fetch_signals.call_count == 0


class TestMetricsTracking:
    """Test latency and error tracking."""
    
    @pytest.mark.asyncio
    async def test_latency_tracking(self, monitor, mock_client):
        async def timed_fetch():
            await asyncio.sleep(0.05)
            return []
        
        mock_client.fetch_signals = timed_fetch
        
        await monitor.call_with_circuit_breaker("fetch_signals")
        await monitor.call_with_circuit_breaker("fetch_signals")
        
        metrics = monitor.get_health_metrics()
        assert metrics.latency_ms > 40
        assert len(monitor._latencies) == 2
    
    @pytest.mark.asyncio
    async def test_error_rate_calculation(self, monitor, mock_client):
        mock_client.fetch_signals.side_effect = [
            [],
            Exception("Error"),
            [],
            Exception("Error")
        ]
        
        for _ in range(4):
            await monitor.call_with_circuit_breaker("fetch_signals")
        
        assert monitor.get_error_rate() == 50.0


class TestManualReset:
    """Test manual circuit breaker reset."""
    
    @pytest.mark.asyncio
    async def test_reset_from_open_to_closed(self, monitor, mock_client):
        mock_client.fetch_signals.side_effect = Exception("API Error")
        
        for _ in range(3):
            await monitor.call_with_circuit_breaker("fetch_signals")
        
        assert monitor.state == CircuitState.OPEN
        
        monitor.reset()
        
        assert monitor.state == CircuitState.CLOSED
        assert monitor._consecutive_failures == 0
        assert monitor.is_mirofish_healthy() is True


class TestStateInfo:
    """Test state information retrieval."""
    
    def test_get_state_info(self, monitor):
        info = monitor.get_state_info()
        
        assert "state" in info
        assert "time_in_state_seconds" in info
        assert "consecutive_failures" in info
        assert "consecutive_successes" in info
        assert "config" in info
        
        assert info["state"] == "CLOSED"
        assert info["config"]["failure_threshold"] == 3
        assert info["config"]["recovery_timeout"] == 30.0


class TestSingletonPattern:
    """Test monitor singleton behavior."""
    
    def test_get_monitor_returns_singleton(self):
        reset_monitor()
        
        monitor1 = get_monitor()
        monitor2 = get_monitor()
        
        assert monitor1 is monitor2
    
    def test_reset_monitor_clears_singleton(self):
        monitor1 = get_monitor()
        reset_monitor()
        monitor2 = get_monitor()
        
        assert monitor1 is not monitor2


class TestCascadeFailureScenario:
    """Test that trading continues when MiroFish is down."""
    
    @pytest.mark.asyncio
    async def test_mirofish_down_trading_continues(self, monitor, mock_client):
        mock_client.fetch_signals.side_effect = Exception("Service Unavailable")
        
        for _ in range(3):
            await monitor.call_with_circuit_breaker("fetch_signals")
        
        assert monitor.state == CircuitState.OPEN
        assert monitor.is_mirofish_healthy() is False
        
        result = await monitor.call_with_circuit_breaker("fetch_signals")
        assert result is None
        
        metrics = monitor.get_health_metrics()
        assert metrics.status == "unhealthy"
        assert metrics.circuit_breaker_state == "OPEN"
