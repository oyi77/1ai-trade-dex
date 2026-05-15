"""Worker for processing jobs from the queue.

This module provides a Worker class that continuously polls the queue for jobs,
executes them using registered handlers, and manages job lifecycle (start, complete,
fail, timeout).

RQ-006: Worker implementation for job queue processing
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Set

from backend.config import settings
from backend.job_queue.abstract import AbstractQueue, Job
from backend.monitoring.queue_metrics import get_queue_metrics, JobTimer
from backend.core.task_manager import TaskManager


from loguru import logger


class Worker:
    """
    Worker that processes jobs from the queue.

    The worker runs a continuous loop that:
    1. Dequeues jobs from the queue
    2. Enforces max_concurrent limit
    3. Dispatches jobs to appropriate handlers
    4. Handles timeouts and failures
    5. Marks jobs as complete or failed

    Attributes:
        _queue: Queue instance for job management
        _max_concurrent: Maximum number of jobs to process simultaneously
        _in_flight_jobs: Set of job IDs currently being processed
        _running: Control flag for main loop
        _db_executor: Thread pool for cleanup operations
    """

    def __init__(self, queue: AbstractQueue, max_concurrent: Optional[int] = None, task_manager: Optional[TaskManager] = None):
        """
        Initialize the worker.

        Args:
            queue: Queue instance for job management
            max_concurrent: Maximum concurrent jobs (defaults to settings.MAX_CONCURRENT_JOBS)
            task_manager: Optional TaskManager for tracking background tasks
        """
        self._queue = queue
        self._max_concurrent = max_concurrent or settings.MAX_CONCURRENT_JOBS
        self._in_flight_jobs: Set[int] = set()
        self._running = False
        self._db_executor = ThreadPoolExecutor(max_workers=1)
        self._active_tasks: Set[asyncio.Task] = set()
        self._task_manager = task_manager

        logger.info(
            f"Worker initialized with max_concurrent={self._max_concurrent}, "
            f"timeout={settings.JOB_TIMEOUT_SECONDS}s"
        )

    async def start(self) -> None:
        """
        Start the worker's main processing loop.

        This method runs continuously until stop() is called. It polls the queue
        for jobs, enforces concurrency limits, and dispatches jobs to handlers.

        For each job:
        - Add to in-flight tracking
        - Execute with timeout enforcement
        - Handle success/failure/timeout
        - Remove from in-flight tracking (always, via try/finally)

        SCHED-6: Periodic cleanup of completed/cancelled tasks from _active_tasks
        to prevent unbounded growth.
        """
        self._running = True
        logger.info("Worker started")
        _iter_count = 0
        _last_snapshot_time = time.monotonic()

        try:
            while self._running:
                _iter_count += 1

                # SCHED-6: Cleanup completed/cancelled tasks every 100 iterations
                if _iter_count % 100 == 0:
                    completed_tasks = {
                        task for task in self._active_tasks
                        if task.done()
                    }
                    if completed_tasks:
                        self._active_tasks -= completed_tasks
                        logger.debug(
                            f"SCHED-6: Cleaned up {len(completed_tasks)} completed tasks, "
                            f"{len(self._active_tasks)} remaining"
                        )

                # Check concurrency limit
                if len(self._in_flight_jobs) >= self._max_concurrent:
                    await asyncio.sleep(0.1)
                    continue

                # Try to dequeue a job
                job = await self._queue.dequeue()
                if job is None:
                    # No jobs available — update depth and sleep briefly
                    get_queue_metrics().update_depth(
                        await self._queue.get_pending_count()
                    )
                    await asyncio.sleep(0.5)
                    continue

                # Periodically update depth (every 10 iterations)
                if _iter_count % 10 == 0:
                    get_queue_metrics().update_depth(
                        await self._queue.get_pending_count()
                    )

                # Log snapshot once per minute
                _now = time.monotonic()
                if _now - _last_snapshot_time >= 60:
                    get_queue_metrics().log_snapshot()
                    _last_snapshot_time = _now

                # Track job as in-flight
                job_id = int(job.job_id)
                self._in_flight_jobs.add(job_id)

                logger.info(
                    f"Job {job_id} started: type={job.job_type}, "
                    f"priority={job.priority}, payload={job.payload}"
                )

                task = asyncio.create_task(self._process_job(job))
                self._active_tasks.add(task)
                task.add_done_callback(lambda t: self._active_tasks.discard(t))

        except Exception as e:
            logger.error(f"Worker loop error: {e}", exc_info=True)
            raise
        finally:
            logger.info("Worker stopped")

    async def _process_job(self, job: Job) -> None:
        """
        Process a single job with timeout and error handling.

        Args:
            job: Job to process
        """
        job_id = int(job.job_id)

        with JobTimer(job.job_type) as timer:
            try:
                if not job.payload or not isinstance(job.payload, dict):
                    raise ValueError(f"Invalid payload: {job.payload}")

                result = await asyncio.wait_for(
                    self.dispatch_job(job), timeout=settings.JOB_TIMEOUT_SECONDS
                )

                # Check if handler reported success
                if result.get("success", False):
                    timer.status = "success"
                    await self._queue.complete(job_id)
                    logger.info(
                        f"Job {job_id} completed: {result.get('message', 'No message')}"
                    )
                else:
                    timer.status = "error"
                    error_msg = result.get("error", "Unknown error")
                    error_class = result.get("error_class", "unknown")

                    # SCHED-7: Check error classification from handler
                    if error_class == "permanent":
                        # Permanent errors (bad data) → dead_letter, no retry
                        try:
                            from backend.models.database import JobQueue, SessionLocal
                            _session = SessionLocal()
                            try:
                                _job = _session.query(JobQueue).filter(JobQueue.id == job_id).first()
                                if _job:
                                    _job.status = "dead_letter"
                                    _job.error_message = error_msg
                                    _session.commit()
                            finally:
                                _session.close()
                        except Exception:
                            logger.exception("Failed to mark job as dead_letter")
                        logger.error(
                            f"Job {job_id} permanent error (dead_letter): {error_msg}"
                        )
                    else:
                        # Transient or unknown errors → retry via queue.fail()
                        await self._queue.fail(job_id, error_msg)
                        logger.error(f"Job {job_id} failed (will retry): {error_msg}")

            except ValueError as e:
                timer.status = "error"
                error_msg = f"Permanent error: {str(e)}"
                try:
                    from backend.models.database import SessionLocal as _SL, JobQueue as _JQ
                    _session = _SL()
                    try:
                        _job = _session.query(_JQ).filter(_JQ.id == job_id).first()
                        if _job:
                            _job.retry_count = _job.max_retries
                            _job.status = "failed"
                            _job.error_message = error_msg
                            _session.commit()
                    finally:
                        _session.close()
                except Exception:
                    logger.exception("Failed to update job error in database")
                    pass
                    pass
                # SCHED-4: Mark permanent errors as dead_letter
                await self._queue.complete(job_id, status="dead_letter")

            except asyncio.TimeoutError:
                timer.status = "timeout"
                error_msg = (
                    f"Job timed out after {settings.JOB_TIMEOUT_SECONDS} seconds"
                )
                await self._queue.fail(job_id, error_msg)
                logger.error(f"Job {job_id} timeout: {error_msg}")

            except Exception as e:
                # SCHED-4: Distinguish transient (network) vs permanent errors
                timer.status = "error"
                error_msg = f"Job execution error: {str(e)}"

                # Check if it's a transient error (network, timeout)
                is_transient = isinstance(e, (TimeoutError, ConnectionError, OSError))
                if is_transient:
                    # Transient errors are retried normally via queue.fail()
                    await self._queue.fail(job_id, error_msg)
                    logger.warning(f"Job {job_id} transient error (will retry): {error_msg}")
                else:
                    # Other exceptions are treated as permanent
                    try:
                        from backend.models.database import JobQueue, SessionLocal
                        _JQ = JobQueue
                        _session = SessionLocal()
                        try:
                            _job = _session.query(_JQ).filter(_JQ.id == job_id).first()
                            if _job:
                                _job.status = "dead_letter"  # SCHED-4: Permanent failure
                                _job.error_message = error_msg
                                _session.commit()
                        finally:
                            _session.close()
                    except Exception:
                        logger.exception("Failed to mark job as dead_letter")
                    logger.error(f"Job {job_id} error (dead_letter): {error_msg}", exc_info=True)

            finally:
                # Always remove from in-flight tracking
                self._in_flight_jobs.discard(job_id)

    async def dispatch_job(self, job: Job) -> dict:
        """
        Dispatch a job to the appropriate handler.

        Args:
            job: Job to dispatch

        Returns:
            Dict with handler result (must include 'success' key)

        Raises:
            ValueError: If job_type is not recognized or payload is invalid
            Exception: If handler execution fails
        """
        # Import handlers to avoid circular dependencies
        from backend.job_queue import handlers

        # SCHED-4: Validate job_type and required payload fields
        VALID_JOB_TYPES = {
            "market_scan": ["mode"],
            "weather_scan": ["mode"],
            "settlement_check": [],
            "signal_generation": [],
        }

        if job.job_type not in VALID_JOB_TYPES:
            raise ValueError(f"Unknown job type: {job.job_type}")

        # Validate required payload fields
        required_fields = VALID_JOB_TYPES[job.job_type]
        for field in required_fields:
            if field not in job.payload:
                raise ValueError(f"Missing required field '{field}' in payload for {job.job_type}")

        # Dispatch based on job type
        if job.job_type == "market_scan":
            result = await handlers.market_scan(job.payload)
        elif job.job_type == "weather_scan":
            result = await handlers.weather_scan(job.payload)
        elif job.job_type == "settlement_check":
            result = await handlers.settlement_check(job.payload)
        elif job.job_type == "signal_generation":
            result = await handlers.signal_generation(job.payload)
        else:
            # This should never happen due to validation above, but kept for safety
            raise ValueError(f"Unknown job type: {job.job_type}")

        # Validate result format
        if not isinstance(result, dict):
            raise ValueError(f"Handler returned invalid result type: {type(result)}")
        if "success" not in result:
            raise ValueError("Handler result missing 'success' key")

        return result

    async def stop(self) -> None:
        self._running = False

        if self._in_flight_jobs:
            logger.info(
                f"Waiting for {len(self._in_flight_jobs)} in-flight jobs to complete..."
            )
            for _ in range(300):
                if not self._in_flight_jobs:
                    break
                await asyncio.sleep(0.1)

            if self._in_flight_jobs:
                logger.warning(
                    f"Shutdown with {len(self._in_flight_jobs)} jobs still in-flight"
                )
            else:
                logger.info("All in-flight jobs completed")

        if self._active_tasks:
            for task in self._active_tasks:
                task.cancel()
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
            self._active_tasks.clear()

        self._db_executor.shutdown(wait=True)
        logger.info("Worker stopped and cleaned up")
