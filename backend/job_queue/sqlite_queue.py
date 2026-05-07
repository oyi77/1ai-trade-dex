"""
Async SQLite-backed queue implementation using ThreadPoolExecutor.

This module provides an async interface to SQLite-backed job queue, using
ThreadPoolExecutor to run synchronous SQLAlchemy operations in async context.

RQ-003: AsyncSQLiteQueue implementation
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone


def _now() -> datetime:
    """Naive UTC datetime — replacement for deprecated _now()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
from typing import Optional, Dict, Any  # noqa: E402

from sqlalchemy import case, func  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from backend.models.database import SessionLocal, JobQueue  # noqa: E402
from backend.job_queue.abstract import AbstractQueue, Job  # noqa: E402


class AsyncSQLiteQueue(AbstractQueue):
    """
    Async SQLite-backed job queue using ThreadPoolExecutor.

    This implementation provides async methods that internally use a thread pool
    to execute synchronous SQLAlchemy database operations. Each database operation
    runs in its own thread with its own session to ensure thread safety.

    Architecture:
        - ThreadPoolExecutor with max_workers=4 for concurrent DB operations
        - Each async method wraps sync DB calls via run_in_thread()
        - Sessions created per-operation within the thread pool
    """

    # Priority mapping for database ordering
    PRIORITY_MAP = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
    }

    def __init__(self, max_workers: int = 4):
        """
        Initialize the async SQLite queue.

        Args:
            max_workers: Maximum number of threads for DB operations
        """
        self._db_executor = ThreadPoolExecutor(max_workers=max_workers)

    async def recover_stale_jobs(self, stale_threshold_seconds: int = 600) -> int:
        """Reset jobs stuck in 'processing' state back to 'pending'.

        Call on startup or periodically to recover from worker crashes.

        Args:
            stale_threshold_seconds: Seconds since started_at to consider stale.

        Returns:
            Number of recovered jobs.
        """
        def _recover():
            session = SessionLocal()
            try:
                cutoff = _now()
                from datetime import timedelta
                cutoff = cutoff - timedelta(seconds=stale_threshold_seconds)
                updated = session.query(JobQueue).filter(
                    JobQueue.status == "processing",
                    JobQueue.started_at < cutoff,
                ).all()
                count = 0
                for job in updated:
                    job.status = "pending"
                    job.started_at = None
                    job.retry_count += 1
                    count += 1
                session.commit()
                return count
            except SQLAlchemyError as e:
                session.rollback()
                raise ValueError(f"Failed to recover stale jobs: {e}")
            finally:
                session.close()

        return await self._run_in_thread(_recover)

    def _run_in_thread(self, sync_func):
        """
        Execute a synchronous function in the thread pool.

        Args:
            sync_func: Synchronous function to execute

        Returns:
            Coroutine that resolves to the function's return value

        Example:
            result = await self._run_in_thread(lambda: db.query(Job).all())
        """
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(self._db_executor, sync_func)

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
        if not job_type:
            raise ValueError("job_type cannot be empty")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dictionary")
        if priority not in self.PRIORITY_MAP:
            raise ValueError(f"Invalid priority: {priority}. Must be one of {list(self.PRIORITY_MAP.keys())}")

        def _insert_job():
            session = SessionLocal()
            try:
                # Check idempotency BEFORE insert to avoid NULL-key bypass
                if idempotency_key is not None:
                    existing = session.query(JobQueue).filter(
                        JobQueue.job_type == job_type,
                        JobQueue.idempotency_key == idempotency_key
                    ).first()
                    if existing:
                        return str(existing.id)

                job = JobQueue(
                    job_type=job_type,
                    payload=payload,
                    priority=priority,
                    idempotency_key=idempotency_key,
                    status="pending",
                    scheduled_at=_now(),
                )
                session.add(job)
                session.commit()
                session.refresh(job)
                return str(job.id)
            except SQLAlchemyError as e:
                session.rollback()
                raise ValueError(f"Failed to enqueue job: {e}")
            finally:
                session.close()

        return await self._run_in_thread(_insert_job)

    async def dequeue(self) -> Optional[Job]:
        """
        Retrieve the next pending job from the queue.

        Jobs are returned in priority order:
        - critical > high > medium > low
        - Within priority: FIFO by scheduled time

        Returns:
            Job object if available, None if queue is empty

        Note:
            Atomically marks the job as 'processing' to prevent multiple workers
            from picking up the same job.
        """
        def _fetch_and_update_job():
            session = SessionLocal()
            try:
                # Build priority ordering using CASE
                priority_order = case(
                    *[(JobQueue.priority == p, i) for p, i in self.PRIORITY_MAP.items()],
                    else_=99
                )

                # Fetch next pending job with row-level locking (SELECT FOR UPDATE)
                job = session.query(JobQueue).filter(
                    JobQueue.status == "pending"
                ).order_by(
                    priority_order,
                    JobQueue.scheduled_at.asc()
                ).with_for_update().first()

                if not job:
                    return None

                # Update status to processing
                job.status = "processing"
                job.started_at = _now()
                session.commit()
                session.refresh(job)

                # Return as Job dataclass
                return Job(
                    job_id=str(job.id),
                    job_type=job.job_type,
                    payload=job.payload,
                    priority=job.priority,
                    idempotency_key=job.idempotency_key,
                    retry_count=job.retry_count,
                    max_retries=job.max_retries,
                    status=job.status,
                    error_message=job.error_message,
                )
            except SQLAlchemyError as e:
                session.rollback()
                raise ValueError(f"Failed to dequeue job: {e}")
            finally:
                session.close()

        return await self._run_in_thread(_fetch_and_update_job)

    async def complete(self, job_id: str) -> None:
        """
        Mark a job as successfully completed.

        Args:
            job_id: Unique identifier of the job to complete

        Raises:
            ValueError: If job_id not found or not in 'processing' state
        """
        def _update_job():
            session = SessionLocal()
            try:
                job = session.query(JobQueue).filter(JobQueue.id == int(job_id)).first()
                if not job:
                    raise ValueError(f"Job {job_id} not found")
                if job.status != "processing":
                    raise ValueError(f"Job {job_id} is not in processing state (current: {job.status})")

                job.status = "completed"
                job.completed_at = _now()
                session.commit()
            except SQLAlchemyError as e:
                session.rollback()
                raise ValueError(f"Failed to complete job: {e}")
            finally:
                session.close()

        await self._run_in_thread(_update_job)

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
        def _update_job():
            session = SessionLocal()
            try:
                job = session.query(JobQueue).filter(JobQueue.id == int(job_id)).first()
                if not job:
                    raise ValueError(f"Job {job_id} not found")
                if job.status != "processing":
                    raise ValueError(f"Job {job_id} is not in processing state (current: {job.status})")

                job.retry_count += 1
                job.error_message = error_message

                # Requeue if retries remain
                if job.retry_count < job.max_retries:
                    job.status = "pending"
                    job.started_at = None  # Reset started_at for retry
                else:
                    job.status = "failed"

                session.commit()
            except SQLAlchemyError as e:
                session.rollback()
                raise ValueError(f"Failed to fail job: {e}")
            finally:
                session.close()

        await self._run_in_thread(_update_job)

    async def get_pending_count(self) -> int:
        """
        Get the number of jobs currently pending (not processing or completed).

        Returns:
            Count of pending jobs
        """
        def _count_jobs():
            session = SessionLocal()
            try:
                count = session.query(func.count(JobQueue.id)).filter(
                    JobQueue.status == "pending"
                ).scalar()
                return count or 0
            except SQLAlchemyError as e:
                raise ValueError(f"Failed to get pending count: {e}")
            finally:
                session.close()

        return await self._run_in_thread(_count_jobs)

    def shutdown(self) -> None:
        """
        Shutdown the thread pool executor.

        Call this when shutting down the application to clean up resources.
        """
        self._db_executor.shutdown(wait=True)
