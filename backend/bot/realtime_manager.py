"""
Real-Time Strategy Manager — Coordinates event-driven strategies.

Manages real-time WebSocket connections for copy trading and whale tracking.
Provides unified interface for starting/stopping real-time strategies.

This is NOT a strategy itself — it's infrastructure that enables
event-driven strategies to run alongside scheduler-based strategies.
"""

import asyncio
from typing import Dict, List, Optional, Any

from backend.bot.realtime_copy_trader import RealTimeCopyTrader
from backend.bot.realtime_whale_tracker import RealTimeWhaleTracker
from backend.strategies.base import StrategyContext

from loguru import logger


class RealTimeStrategyManager:
    """Manages real-time event-driven strategies."""

    def __init__(self):
        self._strategies: Dict[str, Any] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._running = False

    def register_strategy(self, name: str, strategy: Any):
        """Register a real-time strategy."""
        self._strategies[name] = strategy
        logger.info(f"[RealTimeManager] Registered strategy: {name}")

    async def start_all(self, ctx: StrategyContext):
        """Start all registered real-time strategies."""
        self._running = True

        for name, strategy in self._strategies.items():
            if hasattr(strategy, 'start_realtime'):
                task = asyncio.create_task(
                    self._run_strategy(name, strategy, ctx)
                )
                self._tasks[name] = task
                logger.info(f"[RealTimeManager] Started strategy: {name}")

    async def stop_all(self):
        """Stop all real-time strategies."""
        self._running = False

        for name, strategy in self._strategies.items():
            if hasattr(strategy, 'stop_realtime'):
                try:
                    await strategy.stop_realtime()
                    logger.info(f"[RealTimeManager] Stopped strategy: {name}")
                except Exception as e:
                    logger.warning(f"[RealTimeManager] Error stopping {name}: {e}")

        # Cancel all tasks
        for name, task in self._tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        self._tasks.clear()

    async def _run_strategy(self, name: str, strategy: Any, ctx: StrategyContext):
        """Run a single real-time strategy."""
        try:
            await strategy.start_realtime(ctx)
        except asyncio.CancelledError:
            logger.info(f"[RealTimeManager] Strategy {name} cancelled")
        except Exception as e:
            logger.error(f"[RealTimeManager] Strategy {name} failed: {e}")


# Global instance
_manager: Optional[RealTimeStrategyManager] = None


def get_realtime_manager() -> RealTimeStrategyManager:
    """Get the global real-time strategy manager."""
    global _manager
    if _manager is None:
        _manager = RealTimeStrategyManager()
    return _manager


async def start_realtime_strategies(ctx: StrategyContext):
    """Start all real-time strategies."""
    manager = get_realtime_manager()

    # Register copy trader
    copy_trader = RealTimeCopyTrader()
    manager.register_strategy("copy_trader", copy_trader)

    # Register whale tracker
    whale_tracker = RealTimeWhaleTracker()
    manager.register_strategy("whale_tracker", whale_tracker)

    # Start all
    await manager.start_all(ctx)


async def stop_realtime_strategies():
    """Stop all real-time strategies."""
    manager = get_realtime_manager()
    await manager.stop_all()
