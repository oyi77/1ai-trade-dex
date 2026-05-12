"""Distributed settlement lock using Redis SET NX EX with in-memory fallback.

This module provides ``DistributedSettlementLock``, a context-manager-style
lock used to coordinate settlement (and other singleton-style) operations
across multiple application instances. It uses the Redis ``SET key value NX
EX ttl`` pattern for atomic, TTL-bounded acquisition, and only releases
locks that this instance actually owns (by comparing the stored token).

When Redis is unavailable (or not configured), the lock degrades gracefully
to a process-local in-memory lock so single-instance deployments still get
mutual exclusion within the process.

Usage::

    with DistributedSettlementLock("settlement:run") as lock:
        if not lock.acquired:
            return  # Another instance is already running
        do_settlement_work()
"""

from __future__ import annotations
import threading
import time
import uuid
from typing import Optional

from loguru import logger
# ---------------------------------------------------------------------------
# Process-local fallback registry
# ---------------------------------------------------------------------------

# Maps lock_name -> (owner_token, expires_at_epoch_seconds)
_IN_MEMORY_LOCKS: dict[str, tuple[str, float]] = {}
_IN_MEMORY_LOCKS_GUARD = threading.Lock()


def _try_acquire_in_memory(lock_name: str, token: str, ttl_seconds: float) -> bool:
    """Atomically acquire an in-process lock with TTL semantics."""
    now = time.time()
    with _IN_MEMORY_LOCKS_GUARD:
        existing = _IN_MEMORY_LOCKS.get(lock_name)
        if existing is not None:
            _, expires_at = existing
            if expires_at > now:
                return False
        _IN_MEMORY_LOCKS[lock_name] = (token, now + ttl_seconds)
        return True


def _release_in_memory(lock_name: str, token: str) -> bool:
    """Release an in-process lock only if we still own it."""
    with _IN_MEMORY_LOCKS_GUARD:
        existing = _IN_MEMORY_LOCKS.get(lock_name)
        if existing is None:
            return False
        owner, _ = existing
        if owner != token:
            return False
        _IN_MEMORY_LOCKS.pop(lock_name, None)
        return True


# ---------------------------------------------------------------------------
# DistributedSettlementLock
# ---------------------------------------------------------------------------


class DistributedSettlementLock:
    """Cross-instance lock backed by Redis ``SET NX EX`` with in-memory fallback.

    Parameters
    ----------
    lock_name:
        Logical lock identifier. The Redis key is ``polyedge:lock:{lock_name}``.
    timeout:
        TTL of the lock in seconds. Acts as both the Redis key expiry and the
        in-memory fallback expiry to guarantee eventual recovery if a holder
        crashes without releasing.

    The class is non-blocking: ``acquire()`` returns ``False`` immediately if
    the lock is held by another instance. The context manager protocol
    therefore exposes the result via the ``acquired`` attribute; callers must
    check it before doing protected work.
    """

    KEY_PREFIX = "polyedge:lock:"

    def __init__(self, lock_name: str, timeout: float = 30.0) -> None:
        if not lock_name:
            raise ValueError("lock_name must be a non-empty string")
        if timeout <= 0:
            raise ValueError("timeout must be a positive number of seconds")

        self.lock_name = lock_name
        self.timeout = float(timeout)
        self._key = f"{self.KEY_PREFIX}{lock_name}"
        # Unique fencing token so we only release locks we own.
        self._token = uuid.uuid4().hex
        self.acquired: bool = False
        self._using_redis: bool = False
        self._redis_client = self._build_redis_client()

    # ------------------------------------------------------------------
    # Redis client construction
    # ------------------------------------------------------------------

    def _build_redis_client(self):
        """Construct a Redis client, or return None to use in-memory fallback."""
        try:
            from backend.config import settings  # type: ignore

            redis_url = getattr(settings, "REDIS_URL", None) or settings.REDIS_DEFAULT_URL
        except Exception:
            redis_url = "redis://localhost:6379"
            logger.warning("Could not load config for Redis URL, using default fallback")

        try:
            import redis  # type: ignore
        except Exception as exc:  # pragma: no cover - import error path
            logger.debug(
                "redis package unavailable (%s); using in-memory lock fallback",
                exc,
            )
            return None

        try:
            client = redis.from_url(
                redis_url,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            # Probe connectivity once. If it fails, fall back to in-memory.
            client.ping()
        except Exception as exc:
            logger.debug(
                "Redis unavailable at %s (%s); using in-memory lock fallback",
                redis_url,
                exc,
            )
            return None

        self._using_redis = True
        return client

    # ------------------------------------------------------------------
    # Acquire / Release
    # ------------------------------------------------------------------

    def acquire(self) -> bool:
        """Try to acquire the lock without blocking.

        Returns
        -------
        bool
            True if the lock was acquired by this instance, False otherwise.
        """
        if self.acquired:
            return True

        ttl_seconds = max(1, int(round(self.timeout)))

        # Try Redis first when available.
        if self._redis_client is not None:
            try:
                # SET key token NX EX ttl  -> True if set, None/False if not
                ok = self._redis_client.set(
                    self._key,
                    self._token,
                    nx=True,
                    ex=ttl_seconds,
                )
                if ok:
                    self.acquired = True
                    return True
                return False
            except Exception as exc:
                logger.warning(
                    "Redis lock acquire failed for %s (%s); falling back to in-memory",
                    self._key,
                    exc,
                )
                # Drop the redis client so we don't keep retrying it this call.
                self._redis_client = None
                self._using_redis = False

        # In-memory fallback (single-instance correctness only).
        ok = _try_acquire_in_memory(self.lock_name, self._token, self.timeout)
        self.acquired = bool(ok)
        return self.acquired

    def release(self) -> bool:
        """Release the lock if (and only if) this instance still owns it.

        Uses a small Lua script for the Redis path to make compare-and-delete
        atomic, preventing accidental release of a lock whose TTL has expired
        and which has since been re-acquired by another instance.
        """
        if not self.acquired:
            return False

        released = False

        if self._using_redis and self._redis_client is not None:
            # Atomic check-and-delete: only delete if value matches our token.
            lua = (
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) "
                "else return 0 end"
            )
            try:
                result = self._redis_client.eval(lua, 1, self._key, self._token)
                released = bool(result)
            except Exception as exc:
                logger.warning(
                    "Redis lock release failed for %s (%s); attempting in-memory release",
                    self._key,
                    exc,
                )
                released = _release_in_memory(self.lock_name, self._token)
        else:
            released = _release_in_memory(self.lock_name, self._token)

        self.acquired = False
        return released

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> "DistributedSettlementLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        try:
            if self.acquired:
                self.release()
        except Exception as exc:
            logger.exception("Error releasing distributed lock %s", self._key)
            logger.warning("Error releasing distributed lock %s: %s", self._key, exc)
        # Do not suppress exceptions raised within the with-block.
        return None

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    @property
    def backend(self) -> str:
        """Return ``"redis"`` or ``"memory"`` depending on the active backend."""
        return "redis" if self._using_redis and self._redis_client is not None else "memory"

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"DistributedSettlementLock(name={self.lock_name!r}, "
            f"acquired={self.acquired}, backend={self.backend})"
        )
