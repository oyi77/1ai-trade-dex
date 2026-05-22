"""Base class for all activity sources."""

from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Optional
from loguru import logger


class BaseActivitySource(ABC):
    """Abstract base for platform-specific activity sources."""

    def __init__(self, wallet_address: str, platform: str):
        self.wallet_address = wallet_address
        self.platform = platform
        self._running = False
        self._task: Optional[asyncio.Task] = None
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
        """Stop the activity source."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

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