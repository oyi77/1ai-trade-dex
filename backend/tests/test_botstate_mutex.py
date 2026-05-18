"""Tests for G-03: BotState lock contention fix."""
import threading

from backend.models.database import botstate_mutex


class TestBotStateMutexExists:
    def test_mutex_is_asyncio_lock(self):
        import asyncio
        assert isinstance(botstate_mutex, asyncio.Lock)


class TestThreadingLockConsistency:
    """Verify strategy_executor uses the threading lock for sync BotState reads."""

    def test_threading_lock_imported(self):
        from backend.core.strategy_executor import _botstate_threading_lock
        assert isinstance(_botstate_threading_lock, type(threading.Lock()))

    def test_lock_retry_config(self):
        from backend.core.strategy_executor import _MAX_LOCK_RETRY_ATTEMPTS, _LOCK_RETRY_BASE_DELAY_SECONDS
        assert _MAX_LOCK_RETRY_ATTEMPTS >= 2
        assert _LOCK_RETRY_BASE_DELAY_SECONDS > 0


class TestLockRetryDelay:
    def test_exponential_backoff(self):
        from backend.core.strategy_executor import _lock_retry_delay
        d0 = _lock_retry_delay(0)
        d1 = _lock_retry_delay(1)
        d2 = _lock_retry_delay(2)
        assert d1 > d0
        assert d2 > d1
        assert d2 == d0 * 4  # 2^2


class TestIsLockTimeout:
    def test_detects_lock_timeout_string(self):
        from backend.core.strategy_executor import _is_lock_timeout_error
        from sqlalchemy.exc import OperationalError
        exc = OperationalError("stmt", {}, Exception("lock timeout exceeded"))
        assert _is_lock_timeout_error(exc) is True

    def test_ignores_normal_error(self):
        from backend.core.strategy_executor import _is_lock_timeout_error
        from sqlalchemy.exc import OperationalError
        exc = OperationalError("stmt", {}, Exception("table not found"))
        assert _is_lock_timeout_error(exc) is False
