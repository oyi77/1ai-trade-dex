"""Base class for all activity sources."""

from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Optional
from loguru import logger

from backend.constants import BALANCE_DELTA_THRESHOLD


class BaseActivitySource(ABC):
    """Abstract base for platform-specific activity sources.

    Provides:
    - Lifecycle management (start/stop with proper sub-task cancellation)
    - Event dispatch via callbacks
    - Shared balance-delta detection for deposit/withdrawal inference
    """

    def __init__(self, wallet_address: str, platform: str):
        self.wallet_address = wallet_address
        self.platform = platform
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._subtasks: list[asyncio.Task] = []
        self._callbacks: list[Callable] = []

    def on_activity(self, callback: Callable):
        """Register callback for activity events."""
        self._callbacks.append(callback)

    async def start(self):
        """Start the activity source."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info(f"[{self.platform}] Activity source started")

    async def stop(self):
        """Stop the activity source and cancel all sub-tasks."""
        self._running = False
        for t in self._subtasks:
            t.cancel()
        for t in self._subtasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._subtasks.clear()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def create_subtask(self, coro) -> asyncio.Task:
        """Create a tracked sub-task that is cancelled on stop()."""
        t = asyncio.create_task(coro)
        self._subtasks.append(t)
        def _cleanup(task):
            try:
                self._subtasks.remove(task)
            except ValueError:
                pass
        t.add_done_callback(_cleanup)
        return t

    @abstractmethod
    async def _run(self):
        """Main loop — subclasses implement connection + event emission."""
        pass

    async def _emit(self, event):
        """Dispatch event to all callbacks."""
        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(event)
                else:
                    cb(event)
            except Exception as e:
                logger.error(f"[{self.platform}] Callback error: {e}")

    def detect_balance_delta(
        self,
        current: float,
        previous: float,
        threshold: float = BALANCE_DELTA_THRESHOLD,
    ) -> Optional[tuple[str, float]]:
        """Detect deposit/withdrawal from balance change.

        Returns (event_type, amount) or None if change below threshold.
        """
        delta = current - previous
        if abs(delta) < threshold:
            return None
        event_type = "deposit" if delta > 0 else "withdrawal"
        return (event_type, abs(delta))