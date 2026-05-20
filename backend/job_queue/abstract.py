"""
Abstract queue and cache interfaces for PolyEdge job queue system.

This module defines the contracts for queue and cache implementations, enabling
seamless migration from SQLite to Redis in Phase 2 without changing application code.

RQ-002: Abstract interfaces for SQLite → Redis migration
"""

from abc import ABC, abstractmethod
from typing import Optional, Any, Dict
from dataclasses import dataclass


@dataclass
class Job:
    """
    Represents a job in the queue.

    Attributes:
        job_id: Unique identifier for the job
        job_type: Type of job (e.g., 'market_scan', 'settlement', 'signal_generation')
        payload: Job-specific data (JSON-serializable)
        priority: Job priority level (critical, high, medium, low)
        idempotency_key: Optional key to prevent duplicate job execution
        retry_count: Number of retry attempts
        max_retries: Maximum allowed retry attempts
        status: Current job status (pending, processing, completed, failed)
        error_message: Error details if job failed
    """

    job_id: str
    job_type: str
    payload: Dict[str, Any]
    priority: str = "medium"
    idempotency_key: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    status: str = "pending"
    error_message: Optional[str] = None


class AbstractQueue(ABC):
    """
    Abstract queue interface for job management.

    This interface defines the contract for queue implementations, supporting
    both SQLite (Phase 1) and Redis (Phase 2) backends.

    Implementations must be thread-safe for concurrent access by multiple workers.
    """

    @abstractmethod
    async def enqueue(
        self,
        job_type: str,
        payload: Dict[str, Any],
        priority: str = "medium",
        idempotency_key: Optional[str] = None,
    ) -> str:
        """
        Add a job to the queue.

        Args:
            job_type: Type of job (e.g., 'market_scan', 'settlement')
            payload: Job-specific data (must be JSON-serializable)
            priority: Priority level ('critical', 'high', 'medium', 'low')
            idempotency_key: Optional key to prevent duplicate jobs

        Returns:
            job_id: Unique identifier for the enqueued job

        Raises:
            ValueError: If job_type or payload is invalid
        """
        pass

    @abstractmethod
    async def dequeue(self) -> Optional[Job]:
        """
        Retrieve the next pending job from the queue.

        Jobs are returned in priority order:
        - critical > high > medium > low
        - Within priority: FIFO by scheduled time

        Returns:
            Job object if available, None if queue is empty

        Note:
            Implementations should atomically mark the job as 'processing'
            to prevent multiple workers from picking up the same job.
        """
        pass

    @abstractmethod
    async def complete(self, job_id: str) -> None:
        """
        Mark a job as successfully completed.

        Args:
            job_id: Unique identifier of the job to complete

        Raises:
            ValueError: If job_id not found or not in 'processing' state
        """
        pass

    @abstractmethod
    async def fail(self, job_id: str, error_message: str) -> None:
        """
        Mark a job as failed and optionally retry.

        If retry_count < max_retries, the job is requeued with status='pending'.
        Otherwise, the job is marked as permanently failed.

        Args:
            job_id: Unique identifier of the job to fail
            error_message: Human-readable error description

        Raises:
            ValueError: If job_id not found or not in 'processing' state
        """
        pass

    @abstractmethod
    async def get_pending_count(self) -> int:
        """
        Get the number of jobs currently pending (not processing or completed).

        Returns:
            Count of pending jobs
        """
        pass


class AbstractCache(ABC):
    """
    Abstract cache interface for key-value storage.

    This interface defines the contract for cache implementations, supporting
    both SQLite (Phase 1) and Redis (Phase 2) backends.

    Use cases:
    - Rate limiting and deduplication (idempotency keys)
    - Job result caching
    - Session state storage
    - API response caching
    """

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve a value from the cache.

        Args:
            key: Cache key to retrieve

        Returns:
            Cached value if exists and not expired, None otherwise
        """
        pass

    @abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """
        Store a value in the cache.

        Args:
            key: Cache key to store
            value: Value to cache (must be JSON-serializable)
            ttl_seconds: Optional time-to-live in seconds; None = no expiration

        Raises:
            ValueError: If value is not JSON-serializable
        """
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """
        Remove a key from the cache.

        Args:
            key: Cache key to delete

        Note:
            No error is raised if the key doesn't exist (idempotent operation).
        """
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """
        Check if a key exists in the cache and hasn't expired.

        Args:
            key: Cache key to check

        Returns:
            True if key exists and is valid, False otherwise
        """
        pass

    @abstractmethod
    def flush(self) -> None:
        """
        Clear all cached data.

        Warning:
            This is a destructive operation that cannot be undone.
            Use with caution in production environments.
        """
        pass


def create_queue() -> AbstractQueue:
    """
    Factory function to create a queue instance.

    Phase 1: Returns AsyncSQLiteQueue implementation
    Phase 2: Returns RedisQueue when JOB_QUEUE_URL starts with 'redis://'

    Returns:
        AbstractQueue implementation instance
    """
    from backend.config import settings

    if settings.JOB_QUEUE_URL.startswith("redis://"):
        from backend.job_queue.redis_queue import RedisQueue

        return RedisQueue(settings.JOB_QUEUE_URL)

    from backend.job_queue.sqlite_queue import AsyncSQLiteQueue

    return AsyncSQLiteQueue()


def create_cache() -> AbstractCache:
    """
    Factory function to create a cache instance.

    Phase 1: Returns SQLiteCache implementation
    Phase 2: Returns RedisCache with SQLiteCache fallback when CACHE_URL starts with 'redis://'

    Returns:
        AbstractCache implementation instance
    """
    from backend.config import settings

    if settings.CACHE_URL.startswith("redis://"):
        from backend.job_queue.sqlite_cache import SQLiteCache
        from backend.cache.redis_cache import RedisCache

        fallback = SQLiteCache()
        return RedisCache(redis_url=settings.CACHE_URL, fallback=fallback)

    from backend.job_queue.sqlite_cache import SQLiteCache

    return SQLiteCache()
