import asyncio
import logging
from typing import Any, Coroutine, Set

logger = logging.getLogger(__name__)


class TaskManager:
    """Centralized async task lifecycle management.

    Tracks all created tasks, enables graceful shutdown with cancellation,
    and automatically cleans up completed tasks via callbacks.
    """

    def __init__(self):
        self.tasks: Set[asyncio.Task[Any]] = set()
        self._lock = asyncio.Lock()

    async def create_task(
        self, coro: Coroutine[Any, Any, Any], name: str | None = None
    ) -> asyncio.Task[Any]:
        """Create and track an async task.

        Args:
            coro: Coroutine to execute
            name: Optional task name for logging

        Returns:
            The created asyncio.Task
        """
        task = asyncio.create_task(coro, name=name)

        async with self._lock:
            self.tasks.add(task)

        # Add callback to auto-remove task when done
        task.add_done_callback(self._on_task_done)

        logger.debug(f"TaskManager: created task '{name or task.get_name()}' (total: {len(self.tasks)})")

        return task

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        """Callback when a task completes (success, exception, or cancellation)."""
        task_name = task.get_name()

        # Log completion status
        if task.cancelled():
            logger.debug(f"TaskManager: task '{task_name}' cancelled")
        elif task.exception():
            logger.debug(
                f"TaskManager: task '{task_name}' failed with {type(task.exception()).__name__}: {task.exception()}"
            )
        else:
            logger.debug(f"TaskManager: task '{task_name}' completed successfully")

        # Remove from tracking set (safe to call outside lock since set operations are atomic)
        self.tasks.discard(task)

    async def shutdown(self) -> None:
        """Gracefully shutdown all tracked tasks.

        Cancels all pending tasks and waits for them to complete.
        Exceptions from cancelled tasks are suppressed.
        """
        if not self.tasks:
            logger.debug("TaskManager: no tasks to shutdown")
            return

        logger.warning(f"TaskManager: shutting down {len(self.tasks)} task(s)")

        async with self._lock:
            # Cancel all pending tasks
            for task in self.tasks:
                if not task.done():
                    task.cancel()
                    logger.debug(f"TaskManager: cancelled task '{task.get_name()}'")

            # Wait for all tasks to complete (with exceptions suppressed)
            if self.tasks:
                await asyncio.gather(*self.tasks, return_exceptions=True)

        logger.warning(f"TaskManager: shutdown complete, {len(self.tasks)} task(s) remaining")
