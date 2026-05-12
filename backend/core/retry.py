"""Retry decorator with exponential backoff for transient failures."""

import asyncio
import functools
import inspect
import random
import time
from typing import Callable

from loguru import logger

from backend.config import settings


def retry(
    max_attempts: int = 3,
    backoff_base: float | None = None,
    max_delay: float | None = None,
    retryable_exceptions: tuple = (Exception,),
    on_retry: Callable | None = None,
):
    _backoff_base = settings.RATE_LIMIT_BACKOFF_BASE if backoff_base is None else backoff_base
    _max_delay = settings.RATE_LIMIT_MAX_DELAY if max_delay is None else max_delay
    def decorator(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                nonlocal _backoff_base, _max_delay
                last_exc: Exception | None = None
                for attempt in range(1, max_attempts + 1):
                    try:
                        return await func(*args, **kwargs)
                    except retryable_exceptions as exc:
                        last_exc = exc
                        if attempt == max_attempts:
                            break
                        delay = min(_backoff_base**attempt, _max_delay) + random.random()
                        logger.warning(
                            "Retry %d/%d for %s after %.1fs: %s",
                            attempt,
                            max_attempts,
                            func.__name__,
                            delay,
                            exc,
                        )
                        if on_retry is not None:
                            on_retry(func.__name__, attempt, exc)
                        await asyncio.sleep(delay)
                if last_exc is not None:
                    raise last_exc

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                nonlocal _backoff_base, _max_delay
                last_exc: Exception | None = None
                for attempt in range(1, max_attempts + 1):
                    try:
                        return func(*args, **kwargs)
                    except retryable_exceptions as exc:
                        last_exc = exc
                        if attempt == max_attempts:
                            break
                        delay = min(_backoff_base**attempt, _max_delay) + random.random()
                        logger.warning(
                            "Retry %d/%d for %s after %.1fs: %s",
                            attempt,
                            max_attempts,
                            func.__name__,
                            delay,
                            exc,
                        )
                        if on_retry is not None:
                            on_retry(func.__name__, attempt, exc)
                        time.sleep(delay)
                if last_exc is not None:
                    raise last_exc

            return sync_wrapper

    return decorator
