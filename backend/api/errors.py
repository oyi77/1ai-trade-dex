"""Frontend error reporting endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timezone
from backend.models.database import get_db
from backend.api.auth import require_admin
from backend.core.error_logger import get_error_logger

from loguru import logger
router = APIRouter(prefix="/errors", tags=["errors"])


class FrontendErrorReport(BaseModel):
    message: str
    stack: str | None = None
    componentStack: str | None = None
    timestamp: str
    userAgent: str


@router.post("/frontend")
async def report_frontend_error(
    error_report: FrontendErrorReport,
    db: Session = Depends(get_db),
):
    """Receive and log frontend errors from ErrorBoundary."""
    try:
        logger.error(
            f"Frontend Error: {error_report.message}",
            extra={
                "stack": error_report.stack,
                "componentStack": error_report.componentStack,
                "userAgent": error_report.userAgent,
                "timestamp": error_report.timestamp,
            },
        )

        return {
            "status": "received",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.exception(f"Failed to process frontend error report: {e}")
        return {
            "status": "error",
            "message": "Failed to process error report",
        }


@router.get("/system/errors")
async def get_system_errors(
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Get last N system errors with full context."""
    error_logger = get_error_logger(db)
    errors = await error_logger.get_recent_errors(limit=limit)
    return {
        "count": len(errors),
        "errors": errors,
    }


@router.get("/system/aggregation")
async def get_error_aggregation(
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Get error aggregation by type and endpoint."""
    error_logger = get_error_logger(db)
    aggregation = await error_logger.get_error_aggregation(limit=limit)
    return aggregation


@router.get("/system/rate")
async def get_error_rate(
    db: Session = Depends(get_db),
):
    """Get current error rate (errors per minute)."""
    error_logger = get_error_logger(db)
    rate = await error_logger.get_error_rate()
    return {
        "errors_per_minute": rate,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/system/cleanup")
async def cleanup_old_errors(
    days: int = 30,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Delete errors older than specified days."""
    error_logger = get_error_logger(db)
    deleted = await error_logger.cleanup_old_errors(days=days)
    return {
        "deleted": deleted,
        "days_retained": days,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
