"""API versioning middleware and utilities."""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import logging

logger = logging.getLogger("trading_bot")

# Supported API versions
SUPPORTED_VERSIONS = ["v1"]
DEFAULT_VERSION = "v1"


class APIVersionMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle API version negotiation.

    Supports version detection via:
    1. URL prefix: /api/v1/...
    2. Accept-Version header: Accept-Version: v1

    Routes without version prefix default to v1 for backward compatibility.
    """

    async def dispatch(self, request: Request, call_next):
        # Extract version from URL path
        path = request.url.path
        version = None

        # Check if path starts with /api/vX/
        if path.startswith("/api/v"):
            parts = path.split("/")
            if len(parts) >= 3 and parts[2].startswith("v"):
                version = parts[2]

        # Fallback to Accept-Version header
        if not version:
            version = request.headers.get("Accept-Version", DEFAULT_VERSION)

        # Validate version
        if version not in SUPPORTED_VERSIONS:
            return Response(
                content=f'{{"error": "Unsupported API version: {version}. Supported versions: {", ".join(SUPPORTED_VERSIONS)}"}}',
                status_code=400,
                media_type="application/json"
            )

        # Store version in request state for downstream use
        request.state.api_version = version

        # Add version to response headers
        response = await call_next(request)
        response.headers["X-API-Version"] = version

        return response


def get_api_version(request: Request) -> str:
    """Get the API version from request state."""
    return getattr(request.state, "api_version", DEFAULT_VERSION)
