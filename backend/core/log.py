"""
Centralized logging configuration using Loguru.

Replaces stdlib `logging` across the entire codebase with:
  - Structured JSON logging (optional, on by default in production)
  - Correlation IDs via contextvars
  - InterceptHandler to capture third-party stdlib logging (uvicorn, SQLAlchemy, httpx, etc.)
  - Rotating file output with compression
  - Colored console output for development

Usage in any module:
    from loguru import logger
    logger.info("trade executed", strategy="btc_oracle", market="BTC-UP")
"""

import logging
import sys
from contextvars import ContextVar
from typing import Optional

from loguru import logger

# ── Correlation ID ───────────────────────────────────────────────────
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def new_correlation_id() -> str:
    """Generate a new UUID, set it in the context var, and return it."""
    import uuid

    cid = str(uuid.uuid4())
    correlation_id.set(cid)
    return cid


def get_correlation_id() -> str:
    """Return the current correlation ID from the context var."""
    return correlation_id.get("")


# ── InterceptHandler: routes stdlib logging → loguru ──────────────────
class InterceptHandler(logging.Handler):
    """
    Redirects stdlib `logging` records into loguru.

    This ensures that logs from third-party libraries (uvicorn, SQLAlchemy,
    httpx, apscheduler, etc.) are captured by loguru's sinks with the same
    formatting, rotation, and structured output as our own logs.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Walk up the stack to find the real caller (skip logging internals)
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


# ── Logging Setup ────────────────────────────────────────────────────
logger.remove()

# Flag to prevent double-initialization
_INITIALIZED = False


def configure_logging(
    *,
    level: str = "INFO",
    json_output: bool = False,
    log_file: Optional[str] = None,
    rotation: str = "500 MB",
    retention: str = "10 days",
    enqueue: bool = True,
) -> None:
    """
    Configure the global loguru logger.

    Call this ONCE at application startup (in lifespan.py or run.py).

    Args:
        level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_output: If True, console output is JSON-serialized (for production/ELK).
        log_file: Path to rotating log file. None = no file output.
        rotation: When to rotate the log file (size or time).
        retention: How long to keep rotated files.
        enqueue: Use background thread for non-blocking I/O (recommended for FastAPI).
    """
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    # ── Console sink ──────────────────────────────────────────────
    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
        "- <level>{message}</level>"
    )

    if json_output:
        # JSON to console — parseable by ELK/Datadog
        logger.add(
            sys.stdout,
            level=level,
            format=None,  # loguru's serialize mode handles formatting
            serialize=True,
            enqueue=enqueue,
        )
    else:
        # Colored human-readable console
        logger.add(
            sys.stdout,
            level=level,
            format=console_format,
            colorize=True,
            enqueue=enqueue,
        )

    # ── File sink (optional) ──────────────────────────────────────
    if log_file:
        # Always JSON to file for easy parsing
        logger.add(
            log_file,
            level="DEBUG",  # Capture everything to file
            format=None,
            serialize=True,
            rotation=rotation,
            retention=retention,
            compression="zip",
            enqueue=enqueue,
            diagnose=False,  # Don't leak variable values in stack traces
        )

    # ── Intercept stdlib logging ──────────────────────────────────
    # Route ALL stdlib logging through loguru (uvicorn, SQLAlchemy, httpx, etc.)
    logging.basicConfig(
        handlers=[InterceptHandler()],
        level=0,  # Capture everything; loguru filters by level
        force=True,
    )

    # Silence particularly noisy third-party loggers
    for _name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "sqlalchemy.engine",
        "httpx",
        "httpcore",
        "aiohttp.access",
        "apscheduler",
    ):
        _logging_logger = logging.getLogger(_name)
        _logging_logger.handlers = [InterceptHandler()]
        _logging_logger.propagate = False

    logger.info(
        "Logging configured",
        level=level,
        json_output=json_output,
        log_file=log_file or "none",
    )