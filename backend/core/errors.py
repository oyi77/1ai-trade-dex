"""
PolyEdge exception hierarchy and error handling utilities.

This module provides a structured exception hierarchy and a decorator
for consistent error logging across API routes.
"""

import logging
import functools
import inspect
import traceback
from typing import Callable, Any
from fastapi import HTTPException


logger = logging.getLogger(__name__)


# =============================================================================
# Exception Hierarchy
# =============================================================================


class PolyEdgeException(Exception):
    """Base exception for all PolyEdge errors."""

    def __init__(self, message: str, details: dict | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class MarketDataError(PolyEdgeException):
    """Errors related to market data fetching or processing."""

    pass


class TradingError(PolyEdgeException):
    """Errors related to trading operations."""

    pass


class ConfigurationError(PolyEdgeException):
    """Errors related to configuration or settings."""

    pass


class SignalGenerationError(PolyEdgeException):
    """Errors related to signal generation."""

    pass


class SettlementError(PolyEdgeException):
    """Errors related to trade settlement."""

    pass


class ExternalAPIError(PolyEdgeException):
    """Errors related to external API failures."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
        source: str = "",
        status_code: int | None = None,
        retry_after: float | None = None,
        is_transient: bool = True,
    ):
        self.source = source
        self.status_code = status_code
        self.retry_after = retry_after
        self.is_transient = is_transient
        super().__init__(message, details)


class DataQualityError(PolyEdgeException):
    """Errors related to data validation failures."""

    def __init__(
        self, message: str, details: dict | None = None, field_name: str | None = None
    ):
        self.field_name = field_name
        super().__init__(message, details)


class OrderExecutionError(TradingError):
    """Errors related to order placement failures."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
        order_id: str | None = None,
        market_ticker: str | None = None,
    ):
        self.order_id = order_id
        self.market_ticker = market_ticker
        super().__init__(message, details)


class RateLimitError(ExternalAPIError):
    """Errors related to rate limit responses."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
        source: str = "",
        status_code: int | None = None,
        retry_after: float = 0.0,
    ):
        super().__init__(
            message,
            details,
            source=source,
            status_code=status_code,
            retry_after=retry_after,
            is_transient=True,
        )


class CircuitOpenError(ExternalAPIError):
    """Errors related to circuit breaker open state."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
        source: str = "",
        status_code: int | None = None,
        retry_after: float | None = None,
        breaker_name: str = "",
    ):
        self.breaker_name = breaker_name
        super().__init__(
            message,
            details,
            source=source,
            status_code=status_code,
            retry_after=retry_after,
            is_transient=True,
        )


# =============================================================================
# Error Handling Decorator
# =============================================================================


def handle_errors(
    log_level: int = logging.ERROR,
    reraise: bool = True,
    default_response: Any = None,
) -> Callable:
    """
    Decorator for consistent error handling and logging in API routes.

    Args:
        log_level: Logging level to use (default: ERROR)
        reraise: Whether to re-raise the exception (default: True)
        default_response: Optional default response to return on error

    Usage:
        @handle_errors()
        async def my_endpoint(request: Request):
            # endpoint logic
            pass
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                # FastAPI HTTPExceptions should pass through
                raise
            except Exception as e:
                # Log the error with context
                logger.log(
                    log_level,
                    f"Error in {func.__name__}: {str(e)}",
                    extra={
                        "function": func.__name__,
                        "error_type": type(e).__name__,
                        "traceback": traceback.format_exc(),
                    },
                )

                if reraise:
                    raise
                return default_response

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:
                logger.log(
                    log_level,
                    f"Error in {func.__name__}: {str(e)}",
                    extra={
                        "function": func.__name__,
                        "error_type": type(e).__name__,
                        "traceback": traceback.format_exc(),
                    },
                )

                if reraise:
                    raise
                return default_response

        # Return appropriate wrapper based on whether function is async
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
