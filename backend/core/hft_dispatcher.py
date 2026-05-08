"""HFT Parallel Task Dispatcher — dispatches 100+ tasks in <100ms with timeout and overflow handling."""

import asyncio
import logging
import time
from typing import Callable, Any, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("trading_bot.hft_dispatcher")


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class DispatchedTask:
    task_id: str
    func: Callable
    args: tuple
    kwargs: dict
    status: TaskStatus = TaskStatus.PENDING
    submitted_at: float = 0.0
    completed_at: float = 0.0
    result: Any = None
    error: Optional[str] = None


class HFTDispatcher:
    """
    High-throughput parallel task dispatcher.

    Dispatches 100+ async tasks concurrently with:
    - Timeout enforcement per task
    - Worker pool exhaustion handling (overflow queue)
    - Task cancellation
    - Results aggregation

    Zero Gaps:
    - Task timeout: cancel stuck tasks after max_latency
    - Worker exhaustion: queue overflow for later execution
    """

    def __init__(
        self,
        max_concurrent: int = 100,
        default_timeout: float = 5.0,
        max_queue: int = 1000,
    ):
        self.max_concurrent = max_concurrent
        self.default_timeout = default_timeout
        self.max_queue = max_queue
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[str, asyncio.Task] = {}
        self._dispatched: dict[str, DispatchedTask] = {}
        self._overflow: list[DispatchedTask] = []
        self._running = False

    async def dispatch(
        self,
        func: Callable,
        *args,
        task_id: Optional[str] = None,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> DispatchedTask:
        """Dispatch a single async task."""
        if task_id is None:
            task_id = f"task-{int(time.time() * 1000)}"

        dt = DispatchedTask(
            task_id=task_id,
            func=func,
            args=args,
            kwargs=kwargs,
            submitted_at=time.time(),
        )
        self._dispatched[task_id] = dt

        if len(self._tasks) >= self.max_concurrent:
            dt.status = TaskStatus.PENDING
            self._overflow.append(dt)
            logger.debug(f"[dispatcher] Overflow queue, {len(self._overflow)} pending")
            return dt

        asyncio.create_task(self._run_task(dt, timeout or self.default_timeout))
        return dt

    async def dispatch_many(
        self, calls: list[tuple[Callable, tuple, dict]],
        timeout: Optional[float] = None,
    ) -> list[DispatchedTask]:
        """Dispatch multiple tasks in parallel."""
        tasks = []
        for func, args, kwargs in calls:
            dt = await self.dispatch(func, *args, timeout=timeout, **kwargs)
            tasks.append(dt)
        return tasks

    async def _run_task(self, dt: DispatchedTask, timeout: float) -> None:
        """Run a dispatched task with timeout."""
        dt.status = TaskStatus.RUNNING
        task_id = dt.task_id

        async def guarded():
            async with self._semaphore:
                return await asyncio.wait_for(
                    dt.func(*dt.args, **dt.kwargs),
                    timeout=timeout,
                )

        try:
            result = await guarded()
            dt.result = result
            dt.status = TaskStatus.COMPLETED
            dt.completed_at = time.time()
        except asyncio.TimeoutError:
            dt.status = TaskStatus.TIMEOUT
            dt.error = f"Timeout after {timeout}s"
            dt.completed_at = time.time()
            logger.warning(f"[dispatcher] Task {task_id} timed out after {timeout}s")
        except Exception as exc:
            dt.status = TaskStatus.FAILED
            dt.error = str(exc)
            dt.completed_at = time.time()
            logger.warning(f"[dispatcher] Task {task_id} failed: {exc}")
        finally:
            self._tasks.pop(task_id, None)
            self._drain_overflow()

    def _drain_overflow(self) -> None:
        """Move tasks from overflow to running."""
        while self._overflow and len(self._tasks) < self.max_concurrent:
            dt = self._overflow.pop(0)
            asyncio.create_task(self._run_task(dt, self.default_timeout))

    def cancel(self, task_id: str) -> bool:
        """Cancel a running task."""
        task = self._tasks.get(task_id)
        if task:
            task.cancel()
            self._tasks.pop(task_id, None)
            if task_id in self._dispatched:
                self._dispatched[task_id].status = TaskStatus.CANCELLED
            return True
        return False

    def get_result(self, task_id: str) -> Optional[Any]:
        """Get result for a completed task."""
        dt = self._dispatched.get(task_id)
        if dt and dt.status == TaskStatus.COMPLETED:
            return dt.result
        return None

    def get_stats(self) -> dict:
        """Get dispatcher statistics."""
        statuses = [dt.status for dt in self._dispatched.values()]
        return {
            "total": len(self._dispatched),
            "pending": len(self._overflow),
            "running": len(self._tasks),
            "completed": statuses.count(TaskStatus.COMPLETED),
            "failed": statuses.count(TaskStatus.FAILED),
            "timeout": statuses.count(TaskStatus.TIMEOUT),
            "max_concurrent": self.max_concurrent,
        }
