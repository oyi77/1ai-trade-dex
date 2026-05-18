import pytest
from unittest.mock import patch

from backend.core.risk.circuit_breaker_unified import UnifiedCircuitBreaker


class TestUnifiedCircuitBreaker:
    def test_default_to_custom_when_pybreaker_disabled(self):
        cb = UnifiedCircuitBreaker("test_cb", failure_threshold=3)
        assert not cb._is_pybreaker
        assert cb.name == "test_cb"

    @pytest.mark.asyncio
    async def test_call_success_custom(self):
        cb = UnifiedCircuitBreaker("test_cb", failure_threshold=3)

        async def hello():
            return "ok"

        result = await cb.call(hello)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_call_failure_custom(self):
        cb = UnifiedCircuitBreaker("test_cb", failure_threshold=2)

        async def fail():
            raise ValueError("boom")

        for _ in range(2):
            try:
                await cb.call(fail)
            except ValueError:
                pass

    @pytest.mark.asyncio
    async def test_state_closed_initially(self):
        cb = UnifiedCircuitBreaker("test_cb")
        state = cb.state
        assert state in ("CLOSED", "closed")

    def test_factory_uses_config_defaults(self):
        cb = UnifiedCircuitBreaker("test_cb")
        assert cb.name == "test_cb"


class TestCircuitBreakerWithPybreaker:
    @patch("backend.core.risk.circuit_breaker_unified._is_pybreaker_available", True)
    @patch("backend.core.risk.circuit_breaker_unified._USE_PYBREAKER", True)
    def test_uses_pybreaker_when_enabled(self):
        cb = UnifiedCircuitBreaker("test_cb", failure_threshold=3)
        assert cb._is_pybreaker
        assert cb.name == "test_cb"
