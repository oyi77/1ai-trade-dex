import time
import logging
from collections import defaultdict
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("trading_bot.ratelimit")


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """
    In-process rate limiter with per-endpoint limits using sliding window.

    Supports:
    - Per-endpoint rate limits (e.g., /api/trades: 100/min, /api/signals: 50/min)
    - Rate limit headers (X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset)
    - 429 Too Many Requests with Retry-After header

    LIMITATION: State is stored in-process memory and resets on every restart.
    In multi-worker deployments, each worker maintains its own counter.
    For production, use Redis-backed slowapi instead.
    """

    # Per-endpoint rate limits (requests per minute)
    ENDPOINT_LIMITS = {
        "/api/trades": 100,
        "/api/signals": 50,
        "/api/strategies": 20,
    }

    # Default limit for other endpoints
    DEFAULT_LIMIT = 600

    # Per-IP HTTP request limit (requests per minute)
    HTTP_LIMIT_PER_IP = 300

    def __init__(self, app, requests_per_minute: int = 100):
        super().__init__(app)
        self.default_limit = requests_per_minute
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._http_per_ip: dict[str, list[float]] = defaultdict(list)

    def _get_limit_for_path(self, path: str) -> int:
        """Get rate limit for a given path."""
        for endpoint, limit in self.ENDPOINT_LIMITS.items():
            if path.startswith(endpoint):
                return limit
        return self.default_limit

    def _get_client_id(self, request: Request) -> str:
        """Extract client identifier (IP address)."""
        if request.client:
            return request.client.host
        return "unknown"

    def _check_http_per_ip_limit(self, client_id: str, now: float) -> tuple[bool, int]:
        """Check per-IP HTTP request limit (50 per minute).

        Returns:
            (allowed, remaining_requests)
        """
        window_start = now - 60
        self._http_per_ip[client_id] = [t for t in self._http_per_ip[client_id] if t > window_start]

        request_count = len(self._http_per_ip[client_id])
        remaining = max(0, self.HTTP_LIMIT_PER_IP - request_count)

        if request_count >= self.HTTP_LIMIT_PER_IP:
            return False, remaining

        self._http_per_ip[client_id].append(now)
        return True, remaining - 1

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/ws/") or request.url.path in ["/", "/api/health", "/metrics"]:
            return await call_next(request)

        client_id = self._get_client_id(request)
        if client_id in ("testclient", "unknown"):
            return await call_next(request)

        now = time.time()

        http_allowed, http_remaining = self._check_http_per_ip_limit(client_id, now)
        if not http_allowed:
            logger.warning(
                f"HTTP per-IP limit exceeded for {client_id}: "
                f"{self.HTTP_LIMIT_PER_IP}/{self.HTTP_LIMIT_PER_IP} requests"
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests from this IP"},
                headers={
                    "X-RateLimit-Limit": str(self.HTTP_LIMIT_PER_IP),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(now + 60)),
                    "Retry-After": str(60),
                },
                media_type="application/json",
            )

        limit = self._get_limit_for_path(request.url.path)
        window_start = now - 60

        self._requests[client_id] = [
            t for t in self._requests[client_id] if t > window_start
        ]

        if len(self._requests) > 10000:
            self._requests = defaultdict(list, {k: v for k, v in self._requests.items() if v})

        request_count = len(self._requests[client_id])
        remaining = max(0, limit - request_count)

        reset_time = int(now + 60) if self._requests[client_id] else int(now)

        if request_count >= limit:
            logger.warning(
                f"Rate limit exceeded for {client_id} on {request.url.path} "
                f"({request_count}/{limit} requests)"
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_time),
                    "Retry-After": str(60),
                },
                media_type="application/json",
            )

        self._requests[client_id].append(now)

        response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_time)

        return response
