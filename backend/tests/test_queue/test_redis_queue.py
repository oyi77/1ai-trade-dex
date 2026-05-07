"""
Tests for arq-based Redis queue and factory routing.

RQ-015: arq-based Redis queue
"""
import socket

import pytest


def _redis_available() -> bool:
    """Return True if a local Redis server is reachable on 127.0.0.1:6379."""
    try:
        s = socket.create_connection(("127.0.0.1", 6379), timeout=0.1)
        s.close()
        return True
    except OSError:
        return False


def _arq_available() -> bool:
    """Return True if arq is installed."""
    try:
        import arq  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Factory routing tests
# ---------------------------------------------------------------------------

class TestQueueFactory:
    def test_redis_queue_factory_selects_sqlite(self, monkeypatch):
        """
        When JOB_QUEUE_URL is a sqlite:// URL, create_queue() returns AsyncSQLiteQueue.
        """
        from backend.config import settings
        monkeypatch.setattr(settings, "JOB_QUEUE_URL", "sqlite:///./test.db")

        from backend.job_queue.abstract import create_queue
        from backend.job_queue.sqlite_queue import AsyncSQLiteQueue

        queue = create_queue()
        assert isinstance(queue, AsyncSQLiteQueue)

    @pytest.mark.skipif(not _arq_available(), reason="arq not installed")
    def test_redis_queue_factory_selects_redis(self, monkeypatch):
        """
        When JOB_QUEUE_URL starts with redis://, create_queue() returns RedisQueue.
        """
        from backend.config import settings
        monkeypatch.setattr(settings, "JOB_QUEUE_URL", "redis://localhost:6379")

        from backend.job_queue.abstract import create_queue
        from backend.job_queue.redis_queue import RedisQueue

        queue = create_queue()
        assert isinstance(queue, RedisQueue)


# ---------------------------------------------------------------------------
# RedisQueue unit tests (no live Redis required)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _arq_available(), reason="arq not installed")
class TestRedisQueueUnit:
    @pytest.mark.asyncio
    async def test_dequeue_returns_none(self):
        from backend.job_queue.redis_queue import RedisQueue
        q = RedisQueue("redis://127.0.0.1:1")
        assert await q.dequeue() is None

    @pytest.mark.asyncio
    async def test_complete_is_noop(self):
        from backend.job_queue.redis_queue import RedisQueue
        q = RedisQueue("redis://127.0.0.1:1")
        # Should not raise
        await q.complete("some-job-id")

    @pytest.mark.asyncio
    async def test_fail_is_noop(self):
        from backend.job_queue.redis_queue import RedisQueue
        q = RedisQueue("redis://127.0.0.1:1")
        # Should not raise
        await q.fail("some-job-id", "some error")

    @pytest.mark.asyncio
    async def test_get_pending_count_returns_zero_on_error(self):
        """get_pending_count() returns 0 when Redis is unreachable."""
        from backend.job_queue.redis_queue import RedisQueue
        q = RedisQueue("redis://127.0.0.1:1")
        # Should not raise; returns 0 gracefully
        count = await q.get_pending_count()
        assert count == 0

    @pytest.mark.asyncio
    async def test_enqueue_raises_on_empty_job_type(self):
        from backend.job_queue.redis_queue import RedisQueue
        q = RedisQueue("redis://127.0.0.1:1")
        with pytest.raises(ValueError, match="job_type cannot be empty"):
            await q.enqueue("", {})

    @pytest.mark.asyncio
    async def test_enqueue_raises_on_non_dict_payload(self):
        from backend.job_queue.redis_queue import RedisQueue
        q = RedisQueue("redis://127.0.0.1:1")
        with pytest.raises(ValueError, match="payload must be a dictionary"):
            await q.enqueue("market_scan", "not a dict")


# ---------------------------------------------------------------------------
# Live arq tests (requires Redis)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (_arq_available() and _redis_available()),
    reason="arq not installed or no live Redis on 127.0.0.1:6379",
)
class TestRedisQueueLive:
    @pytest.mark.asyncio
    async def test_enqueue_returns_job_id(self):
        from backend.job_queue.redis_queue import RedisQueue
        q = RedisQueue("redis://127.0.0.1:6379")
        job_id = await q.enqueue("market_scan", {"test": True})
        assert job_id is not None
        assert isinstance(job_id, str)

    @pytest.mark.asyncio
    async def test_idempotency_key(self):
        from backend.job_queue.redis_queue import RedisQueue
        q = RedisQueue("redis://127.0.0.1:6379")
        job_id_1 = await q.enqueue("market_scan", {}, idempotency_key="idem-test-1")
        job_id_2 = await q.enqueue("market_scan", {}, idempotency_key="idem-test-1")
        # Both calls with same key return same (or compatible) id
        assert job_id_1 == job_id_2 or job_id_2 == ""
