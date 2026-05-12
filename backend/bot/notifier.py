"""
Global notification dispatch.
Call set_bot() once from orchestrator on startup.
All other modules call notify_*() without holding a bot reference.
"""

import asyncio
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.bot.telegram_bot import PolyEdgeBot

from loguru import logger
_bot: Optional["PolyEdgeBot"] = None


def set_bot(bot: "PolyEdgeBot") -> None:
    global _bot
    _bot = bot


def get_bot() -> Optional["PolyEdgeBot"]:
    return _bot


def _fire(coro) -> None:
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        task.add_done_callback(_log_task_exception)
    except RuntimeError:
        pass
    except Exception as e:
        logger.debug(f"notify fire error: {e}")


def _log_task_exception(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        logger.debug(f"Notification task failed: {task.exception()}")


def notify_btc_signal(signal, trade=None) -> None:
    if _bot:
        _fire(_bot.send_btc_signal(signal, trade))


def notify_trade_opened(trade) -> None:
    if _bot:
        _fire(_bot.send_trade_opened(trade))


def notify_trade_settled(trade) -> None:
    if _bot:
        _fire(_bot.send_trade_settled(trade))


def notify_scan_summary(total: int, actionable: int, placed: int) -> None:
    if _bot and (actionable > 0 or placed > 0):
        _fire(_bot.send_scan_summary(total, actionable, placed))


def notify_error(error: str, context: str = "") -> None:
    if _bot:
        _fire(_bot.send_error_alert(error, context))


def notify_high_confidence_signal(
    strategy: str,
    market_title: str,
    direction: str,
    confidence: float,
    edge: float,
    reasoning: str,
    market_url: str = "",
) -> None:
    """
    Send alert for high-confidence trading signals (confidence >= 0.75).
    Called by strategies when they generate strong signals.
    """
    if _bot:
        _fire(
            _bot.send_high_confidence_signal(
                strategy=strategy,
                market_title=market_title,
                direction=direction,
                confidence=confidence,
                edge=edge,
                reasoning=reasoning,
                market_url=market_url,
            )
        )
