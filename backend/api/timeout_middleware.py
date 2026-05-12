"""Request timeout middleware for FastAPI."""

import asyncio
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.config import settings

from loguru import logger
class TimeoutMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce request timeouts on all API endpoints."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        try:
            response = await asyncio.wait_for(
                call_next(request),
                timeout=settings.API_REQUEST_TIMEOUT
            )
            return response

        except asyncio.TimeoutError:
            elapsed = time.time() - start_time

            logger.warning(
                f"Request timeout: {request.method} {request.url.path} "
                f"exceeded {settings.API_REQUEST_TIMEOUT}s (elapsed: {elapsed:.2f}s)"
            )

            from backend.monitoring.metrics import increment_timeouts
            increment_timeouts(timeout_type="api")

            return JSONResponse(
                status_code=504,
                content={
                    "error": "Gateway Timeout",
                    "message": f"Request exceeded timeout of {settings.API_REQUEST_TIMEOUT} seconds",
                    "timeout_seconds": settings.API_REQUEST_TIMEOUT,
                    "elapsed_seconds": round(elapsed, 2)
                }
            )
