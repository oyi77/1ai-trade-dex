"""
Redis-backed cache with circuit-breaker fallback to SQLiteCache.

RQ-014: Redis cache with circuit-breaker fallback to SQLite
"""
import json
import logging
import time
from typing import Optional, Any

from redis import Redis
from redis.exceptions import RedisError

from backend.job_queue.abstract import AbstractCache
from backend.config import settings

logger = logging.getLogger("trading_bot")


class CircuitBreaker:
    """
    Simple circuit breaker with closed/open/half_open states.

    After `threshold` consecutive failures the circuit opens (blocks calls).
    After `timeout` seconds the circuit allows a single half-open trial.
    A success resets the breaker to closed; a failure keeps it open.
    """

    STATE_CLOSED = "closed"
    STATE_OPEN = "open"
    STATE_HALF_OPEN = "half_open"

    def __init__(self, threshold: int = 3, timeout: int = 60):
        """
        Args:
            threshold: Consecutive failures required to open the circuit
            timeout: Seconds to wait before allowing a half-open trial
        """
        self._threshold = threshold
        self._timeout = timeout
        self._failure_count = 0
        self._opened_at: Optional[float] = None
        self._state = self.STATE_CLOSED

    @property
    def state(self) -> str:
        return self._state

    def is_open(self) -> bool:
        """Return True if the circuit is currently open (blocking calls)."""
        if self._state == self.STATE_OPEN:
            if time.time() - self._opened_at >= self._timeout:
                self._state = self.STATE_HALF_OPEN
                return False
            return True
        return False

    def can_attempt(self) -> bool:
        """
        Return True if a call should be attempted (circuit closed or half-open).
        """
        if self._state == self.STATE_CLOSED:
            return True
        if self._state == self.STATE_HALF_OPEN:
            return True
        # STATE_OPEN: check if timeout elapsed
        if time.time() - self._opened_at >= self._timeout:
            self._state = self.STATE_HALF_OPEN
            return True
        return False

    def record_success(self) -> None:
        """Reset circuit to closed on success."""
        self._failure_count = 0
        self._opened_at = None
        self._state = self.STATE_CLOSED

    def record_failure(self) -> None:
        """Record a failure; open circuit if threshold reached."""
        self._failure_count += 1
        if self._failure_count >= self._threshold:
            self._state = self.STATE_OPEN
            self._opened_at = time.time()
            logger.warning(
                "CircuitBreaker opened after %d consecutive failures",
                self._failure_count,
            )


class RedisCache(AbstractCache):
    """
    Redis-backed cache with circuit-breaker fallback to SQLiteCache.

    All methods use the synchronous `redis.Redis` client. On RedisError or when
    the circuit breaker is open, calls fall back to the provided SQLiteCache.

    Values are JSON-serialized before storage and deserialized on retrieval.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        fallback: AbstractCache = None,
        breaker_threshold: int = 3,
        breaker_timeout: int = 60,
    ):
        self._redis_url = redis_url or settings.REDIS_URL
        self._fallback = fallback
        self._breaker = CircuitBreaker(
            threshold=breaker_threshold, timeout=breaker_timeout
        )
        self._client: Optional[Redis] = None

    def _get_client(self) -> Redis:
        """Lazily create and return the Redis sync client."""
        if self._client is None:
            self._client = Redis.from_url(self._redis_url, socket_connect_timeout=2)
        return self._client

    def _redis_op(self, op):
        """
        Execute a Redis operation with circuit-breaker protection.

        Returns (result, used_redis). If circuit is open or op raises, falls
        back transparently by returning (None, False).
        """
        if not self._breaker.can_attempt():
            return None, False
        try:
            result = op(self._get_client())
            self._breaker.record_success()
            return result, True
        except (RedisError, OSError, ConnectionError) as exc:
            logger.debug("Redis operation failed: %s", exc)
            self._breaker.record_failure()
            return None, False

    def get(self, key: str) -> Optional[Any]:
        """Retrieve value; falls back to SQLiteCache on Redis failure."""
        def _op(r: Redis):
            raw = r.get(key)
            if raw is None:
                return None
            return json.loads(raw)

        result, ok = self._redis_op(_op)
        if not ok:
            return self._fallback.get(key)
        return result

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Store value; falls back to SQLiteCache on Redis failure."""
        try:
            value_str = json.dumps(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Value is not JSON-serializable: {e}") from e

        def _op(r: Redis):
            if ttl_seconds is not None:
                r.setex(key, ttl_seconds, value_str)
            else:
                r.set(key, value_str)

        _, ok = self._redis_op(_op)
        if not ok:
            self._fallback.set(key, value, ttl_seconds=ttl_seconds)

    def delete(self, key: str) -> None:
        """Delete key; falls back to SQLiteCache on Redis failure."""
        _, ok = self._redis_op(lambda r: r.delete(key))
        if not ok:
            self._fallback.delete(key)

    def exists(self, key: str) -> bool:
        """Check key existence; falls back to SQLiteCache on Redis failure."""
        result, ok = self._redis_op(lambda r: bool(r.exists(key)))
        if not ok:
            return self._fallback.exists(key)
        return result

    def flush(self) -> None:
        """Flush all keys; falls back to SQLiteCache on Redis failure."""
        _, ok = self._redis_op(lambda r: r.flushdb())
        if not ok:
            self._fallback.flush()
