"""Timeout helper utilities for external API calls."""

import asyncio
from typing import Callable, TypeVar, Any

from backend.config import settings

from loguru import logger

T = TypeVar("T")


async def execute_external_api_with_timeout(
    api_call: Callable[[], Any],
    timeout: float = None,
    operation_name: str = "external_api",
) -> Any:
    """
    Execute an external API call with timeout.

    Args:
        api_call: Async callable that performs the API call
        timeout: Timeout in seconds (defaults to EXTERNAL_API_TIMEOUT)
        operation_name: Name of the operation for logging

    Returns:
        Result of the API call

    Raises:
        asyncio.TimeoutError: If operation exceeds timeout
    """
    if timeout is None:
        timeout = settings.EXTERNAL_API_TIMEOUT

    try:
        result = await asyncio.wait_for(api_call(), timeout=timeout)
        return result
    except asyncio.TimeoutError:
        logger.error(f"External API timeout: {operation_name} exceeded {timeout}s")
        from backend.monitoring.metrics import increment_timeouts

        increment_timeouts(timeout_type="external_api")
        raise
