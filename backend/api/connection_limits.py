"""Connection limits tracking for WebSocket and HTTP requests.

Tracks active connections per IP and globally to prevent resource exhaustion.
Supports Redis-backed tracking (multi-instance) with in-memory fallback.

Limits:
- WebSocket connections per IP: 10
- HTTP requests per IP: 50 (per minute)
- Global WebSocket connections: 1000
"""

import time
import logging
from collections import defaultdict
from typing import Optional, Dict, Tuple
from fastapi import WebSocket

logger = logging.getLogger("trading_bot.connection_limits")


class ConnectionLimiter:
    """Tracks and enforces connection limits per IP and globally."""

    # Configuration
    WS_LIMIT_PER_IP = 10
    HTTP_LIMIT_PER_IP = 50  # per minute
    GLOBAL_WS_LIMIT = 1000

    def __init__(self):
        """Initialize in-memory connection tracking."""
        # WebSocket connections: {ip: count}
        self._ws_connections: Dict[str, int] = defaultdict(int)

        # HTTP requests: {ip: [(timestamp, endpoint), ...]}
        self._http_requests: Dict[str, list] = defaultdict(list)

        # Global WebSocket count
        self._global_ws_count = 0

        # Redis support (optional)
        self._redis_enabled = False
        self._redis_client = None

    async def initialize_redis(self, redis_url: Optional[str] = None):
        """Initialize Redis for multi-instance tracking."""
        if not redis_url:
            logger.info("Redis not configured, using in-memory connection tracking")
            return

        try:
            import redis.asyncio as redis
            self._redis_client = await redis.from_url(redis_url, decode_responses=True)
            await self._redis_client.ping()
            self._redis_enabled = True
            logger.info("Redis connection tracking initialized")
        except Exception as e:
            logger.warning(f"Redis initialization failed: {e}. Using in-memory fallback")
            self._redis_enabled = False

    def _get_client_ip(self, websocket: WebSocket) -> str:
        """Extract client IP from WebSocket connection."""
        if websocket.client:
            return websocket.client.host
        return "unknown"

    async def check_ws_limit(self, websocket: WebSocket) -> Tuple[bool, Optional[str]]:
        """Check if WebSocket connection is allowed.

        Returns:
            (allowed, error_message)
        """
        client_ip = self._get_client_ip(websocket)

        # Check per-IP limit
        if self._redis_enabled:
            count = await self._redis_client.incr(f"ws:ip:{client_ip}")
            if count == 1:
                await self._redis_client.expire(f"ws:ip:{client_ip}", 3600)
        else:
            self._ws_connections[client_ip] += 1
            count = self._ws_connections[client_ip]

        if count > self.WS_LIMIT_PER_IP:
            logger.warning(
                f"WebSocket limit exceeded for {client_ip}: "
                f"{count}/{self.WS_LIMIT_PER_IP} connections"
            )
            # Decrement since we're rejecting
            if self._redis_enabled:
                await self._redis_client.decr(f"ws:ip:{client_ip}")
            else:
                self._ws_connections[client_ip] -= 1
            return False, f"Too many connections from this IP ({count}/{self.WS_LIMIT_PER_IP})"

        # Check global limit
        if self._redis_enabled:
            global_count = await self._redis_client.incr("ws:global")
            if global_count == 1:
                await self._redis_client.expire("ws:global", 3600)
        else:
            self._global_ws_count += 1
            global_count = self._global_ws_count

        if global_count > self.GLOBAL_WS_LIMIT:
            logger.warning(
                f"Global WebSocket limit exceeded: "
                f"{global_count}/{self.GLOBAL_WS_LIMIT} connections"
            )
            # Decrement both counters since we're rejecting
            if self._redis_enabled:
                await self._redis_client.decr(f"ws:ip:{client_ip}")
                await self._redis_client.decr("ws:global")
            else:
                self._ws_connections[client_ip] -= 1
                self._global_ws_count -= 1
            return False, f"Server at capacity ({global_count}/{self.GLOBAL_WS_LIMIT})"

        logger.debug(
            f"WebSocket connection allowed for {client_ip}: "
            f"{count}/{self.WS_LIMIT_PER_IP} per-IP, "
            f"{global_count}/{self.GLOBAL_WS_LIMIT} global"
        )
        return True, None

    async def release_ws_connection(self, websocket: WebSocket):
        """Release a WebSocket connection when client disconnects."""
        client_ip = self._get_client_ip(websocket)

        if self._redis_enabled:
            await self._redis_client.decr(f"ws:ip:{client_ip}")
            await self._redis_client.decr("ws:global")
        else:
            self._ws_connections[client_ip] = max(0, self._ws_connections[client_ip] - 1)
            self._global_ws_count = max(0, self._global_ws_count - 1)

        logger.debug(f"WebSocket connection released for {client_ip}")

    def check_http_limit(self, client_ip: str, endpoint: str) -> Tuple[bool, Optional[str]]:
        """Check if HTTP request is allowed (50 per minute per IP).

        Returns:
            (allowed, error_message)
        """
        now = time.time()
        window_start = now - 60

        # Clean old requests outside the 60-second window
        self._http_requests[client_ip] = [
            (ts, ep) for ts, ep in self._http_requests[client_ip] if ts > window_start
        ]

        request_count = len(self._http_requests[client_ip])

        if request_count >= self.HTTP_LIMIT_PER_IP:
            logger.warning(
                f"HTTP rate limit exceeded for {client_ip} on {endpoint}: "
                f"{request_count}/{self.HTTP_LIMIT_PER_IP} requests"
            )
            return False, f"Rate limit exceeded ({request_count}/{self.HTTP_LIMIT_PER_IP})"

        # Record this request
        self._http_requests[client_ip].append((now, endpoint))

        logger.debug(
            f"HTTP request allowed for {client_ip} on {endpoint}: "
            f"{request_count + 1}/{self.HTTP_LIMIT_PER_IP}"
        )
        return True, None

    async def get_metrics(self) -> Dict:
        """Get current connection metrics."""
        if self._redis_enabled:
            ws_per_ip = {}
            global_ws = int(await self._redis_client.get("ws:global") or 0)

            # Get all per-IP counts
            keys = await self._redis_client.keys("ws:ip:*")
            for key in keys:
                ip = key.replace("ws:ip:", "")
                count = int(await self._redis_client.get(key) or 0)
                if count > 0:
                    ws_per_ip[ip] = count
        else:
            ws_per_ip = {ip: count for ip, count in self._ws_connections.items() if count > 0}
            global_ws = self._global_ws_count

        http_per_ip = {}
        now = time.time()
        window_start = now - 60
        for ip, requests in self._http_requests.items():
            # Count requests in current window
            count = len([ts for ts, _ in requests if ts > window_start])
            if count > 0:
                http_per_ip[ip] = count

        return {
            "websocket": {
                "per_ip": ws_per_ip,
                "global": global_ws,
                "global_limit": self.GLOBAL_WS_LIMIT,
                "per_ip_limit": self.WS_LIMIT_PER_IP,
            },
            "http": {
                "per_ip": http_per_ip,
                "per_ip_limit": self.HTTP_LIMIT_PER_IP,
                "window_seconds": 60,
            },
        }

    async def shutdown(self):
        """Shutdown Redis connection if enabled."""
        if self._redis_enabled and self._redis_client:
            await self._redis_client.close()
            self._redis_enabled = False
            logger.info("Connection limiter shutdown complete")


# Global instance
connection_limiter = ConnectionLimiter()
