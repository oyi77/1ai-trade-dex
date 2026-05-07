"""Middleware for automatic metrics collection."""

import asyncio
from time import perf_counter
from fastapi import Request
import logging

from backend.monitoring import record_api_latency, increment_api_errors
from backend.monitoring.performance_tracker import get_performance_tracker
from backend.models.database import SessionLocal

logger = logging.getLogger("trading_bot")


async def _persist_request_metrics(
    *,
    duration_ms: float,
    endpoint: str,
    method: str,
    status_code: int,
    user_agent: str | None = None,
    error_message: str | None = None,
) -> None:
    """Persist request metrics without blocking the response path.

    SQLite can hold write locks for tens of seconds under heavy concurrent writes.
    API responses must not wait on observability bookkeeping, so this helper runs the
    database work off the request path and degrades to warning-only if persistence fails.
    """

    def _write() -> None:
        tracker = get_performance_tracker()
        db = SessionLocal()
        try:
            tracker.track_request(
                duration_ms=duration_ms,
                endpoint=endpoint,
                method=method,
                status_code=status_code,
                db=db,
                user_agent=user_agent,
                error_message=error_message,
            )
            tracker.maybe_cleanup(db)
        finally:
            db.close()

    try:
        await asyncio.to_thread(_write)
    except Exception as exc:
        logger.warning(f"Failed to persist async request metric: {exc}")


def _schedule_request_metrics_persistence(**kwargs) -> None:
    """Best-effort fire-and-forget metrics persistence."""

    try:
        asyncio.create_task(_persist_request_metrics(**kwargs))
    except RuntimeError as exc:
        logger.warning(f"Failed to schedule request metric persistence: {exc}")


async def metrics_middleware(request: Request, call_next):
    """
    Middleware to track API request latency and errors.

    Automatically records:
    - Request duration (for latency monitoring)
    - Error counts (4xx and 5xx responses)
    - Detailed performance metrics with percentiles
    """
    start_time = perf_counter()
    error_message = None

    try:
        response = await call_next(request)

        # Record latency in milliseconds
        duration_ms = (perf_counter() - start_time) * 1000
        record_api_latency(duration_ms)

        _schedule_request_metrics_persistence(
            duration_ms=duration_ms,
            endpoint=request.url.path,
            method=request.method,
            status_code=response.status_code,
            user_agent=request.headers.get("user-agent"),
        )

        # Track errors
        if response.status_code >= 400:
            increment_api_errors()
            logger.warning(f"API error: {request.method} {request.url.path} -> {response.status_code}")

        return response

    except Exception as e:
        # Record failed requests
        duration_ms = (perf_counter() - start_time) * 1000
        record_api_latency(duration_ms)
        increment_api_errors()
        error_message = str(e)

        _schedule_request_metrics_persistence(
            duration_ms=duration_ms,
            endpoint=request.url.path,
            method=request.method,
            status_code=500,
            error_message=error_message,
        )

        logger.error(f"API exception: {request.method} {request.url.path} -> {error_message}")
        raise
