"""Health check endpoints."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from sqlalchemy.orm import Session
import psutil
import os

from backend.config import settings
from backend.models.database import get_db, Signal, Trade
from loguru import logger

router = APIRouter(tags=["system"])


class HealthStatus(BaseModel):
    """Basic health status response."""
    status: str
    agi_events: dict = {}


class ReadinessStatus(BaseModel):
    """Readiness check with dependency status."""
    status: str  # "ready" or "not_ready"
    database: str  # "connected" or "disconnected"
    redis: Optional[str] = None


class DetailedHealthStatus(BaseModel):
    status: str
    timestamp: str
    database: dict
    redis: Optional[dict] = None
    disk_space: dict
    memory: dict
    uptime_seconds: Optional[float] = None
    circuit_breakers: Optional[dict] = None
    avg_signal_time_ms: Optional[float] = None
    signals_24h: Optional[int] = None
    trades_24h: Optional[int] = None


@router.get("/health", response_model=HealthStatus)
async def health_check():
    """
    Basic liveness check. Returns 200 OK if service is running.
    No dependencies checked - purely for load balancer/orchestrator.
    """
    agi_health = {}
    try:
        from backend.core.agi_event_handlers import check_agi_health
        agi_health = check_agi_health()
    except Exception:
        logger.exception("Failed to check AGI health in liveness endpoint")
    return {"status": "healthy", "agi_events": agi_health}


@router.get("/health/live", response_model=HealthStatus, include_in_schema=False)
async def health_live_check():
    """Backward-compatible liveness alias for common /health/live probes."""
    return await health_check()


@router.get("/health/agi")
async def agi_health_check():
    """Return AGI event handler health status."""
    from backend.core.agi_event_handlers import check_agi_health
    return check_agi_health()


@router.get("/health/ready", response_model=ReadinessStatus, status_code=200)
async def readiness_check(db: Session = Depends(get_db)):
    """
    Readiness check with critical dependency verification.
    Returns 200 if ready, 503 if not ready.
    Checks: database connectivity, Redis (if configured).
    """
    database_status = "disconnected"
    redis_status = None

    try:
        db.execute(text("SELECT 1"))
        database_status = "connected"
    except Exception as e:
        logger.warning(f"Database readiness check failed: {e}")
        return ReadinessStatus(
            status="not_ready", database=database_status, redis=redis_status
        )

    if settings.REDIS_URL:
        try:
            import redis
            r = redis.from_url(
                settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2
            )
            r.ping()
            redis_status = "connected"
        except Exception as e:
            logger.warning(f"Redis readiness check failed: {e}")
            redis_status = "disconnected"
            return ReadinessStatus(
                status="not_ready", database=database_status, redis=redis_status
            )

    return ReadinessStatus(status="ready", database=database_status, redis=redis_status)


@router.get("/health/detailed", response_model=DetailedHealthStatus, status_code=200)
async def detailed_health_check(db: Session = Depends(get_db)):
    """
    Comprehensive system health status with full metrics.
    Returns 200 if healthy, 503 if unhealthy.
    Checks: database, Redis, disk space, memory usage, circuit breakers.
    """
    from backend.core.risk.circuit_breaker_pybreaker import get_breaker_status

    timestamp = datetime.now(timezone.utc).isoformat()
    is_healthy = True

    database_info = {"status": "disconnected", "latency_ms": None, "error": None}
    try:
        import time
        start = time.time()
        db.execute(text("SELECT 1"))
        latency_ms = (time.time() - start) * 1000
        database_info["status"] = "connected"
        database_info["latency_ms"] = round(latency_ms, 2)
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        database_info["status"] = "disconnected"
        database_info["error"] = str(e)
        is_healthy = False

    redis_info = None
    if settings.REDIS_URL:
        redis_info = {"status": "disconnected", "latency_ms": None, "error": None}
        try:
            import redis
            import time
            r = redis.from_url(
                settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2
            )
            start = time.time()
            r.ping()
            latency_ms = (time.time() - start) * 1000
            redis_info["status"] = "connected"
            redis_info["latency_ms"] = round(latency_ms, 2)
        except Exception as e:
            logger.warning(f"Redis health check failed: {e}")
            redis_info["status"] = "disconnected"
            redis_info["error"] = str(e)

    circuit_breakers = get_breaker_status()

    disk_info = {
        "status": "ok",
        "total_gb": 0,
        "used_gb": 0,
        "free_gb": 0,
        "percent_used": 0,
        "warning": None,
    }
    try:
        disk_usage = psutil.disk_usage("/")
        disk_info["total_gb"] = round(disk_usage.total / (1024**3), 2)
        disk_info["used_gb"] = round(disk_usage.used / (1024**3), 2)
        disk_info["free_gb"] = round(disk_usage.free / (1024**3), 2)
        disk_info["percent_used"] = disk_usage.percent

        if disk_usage.percent > 90:
            disk_info["status"] = "critical"
            disk_info["warning"] = "Disk usage above 90%"
            is_healthy = False
        elif disk_usage.percent > 80:
            disk_info["status"] = "warning"
            disk_info["warning"] = "Disk usage above 80%"
    except Exception as e:
        logger.warning(f"Disk space check failed: {e}")
        disk_info["status"] = "unknown"
        disk_info["error"] = str(e)

    memory_info = {
        "status": "ok",
        "total_gb": 0,
        "used_gb": 0,
        "available_gb": 0,
        "percent_used": 0,
        "warning": None,
    }
    try:
        mem = psutil.virtual_memory()
        memory_info["total_gb"] = round(mem.total / (1024**3), 2)
        memory_info["used_gb"] = round(mem.used / (1024**3), 2)
        memory_info["available_gb"] = round(mem.available / (1024**3), 2)
        memory_info["percent_used"] = mem.percent

        if mem.percent > 90:
            memory_info["status"] = "critical"
            memory_info["warning"] = "Memory usage above 90%"
            is_healthy = False
        elif mem.percent > 80:
            memory_info["status"] = "warning"
            memory_info["warning"] = "Memory usage above 80%"
    except Exception as e:
        logger.warning(f"Memory check failed: {e}")
        memory_info["status"] = "unknown"
        memory_info["error"] = str(e)

    uptime_seconds = None
    try:
        process = psutil.Process(os.getpid())
        uptime_seconds = time.time() - process.create_time()
    except Exception:
        logger.exception("Failed to read process uptime in health check")

    status = "healthy" if is_healthy else "unhealthy"
    _status_code = 200 if is_healthy else 503

    avg_signal_time_ms = None
    signals_24h = None
    trades_24h = None
    try:
        from backend.monitoring.metrics import get_metrics_snapshot
        metrics = get_metrics_snapshot()
        avg_signal_time_ms = metrics.get("avg_api_latency_ms")
        signals_24h = (
            db.query(Signal)
            .filter(
                Signal.created_at >= datetime.now(timezone.utc) - timedelta(hours=24)
            )
            .count()
            if db
            else 0
        )
        trades_24h = (
            db.query(Trade)
            .filter(
                Trade.created_at >= datetime.now(timezone.utc) - timedelta(hours=24)
            )
            .count()
            if db
            else 0
        )
    except Exception:
        logger.exception("Failed to collect metrics in health check")

    return DetailedHealthStatus(
        status=status,
        timestamp=timestamp,
        database=database_info,
        redis=redis_info,
        disk_space=disk_info,
        memory=memory_info,
        uptime_seconds=uptime_seconds,
        circuit_breakers=circuit_breakers,
        avg_signal_time_ms=avg_signal_time_ms,
        signals_24h=signals_24h,
        trades_24h=trades_24h,
    )


@router.get("/health/mirofish")
async def get_mirofish_health():
    """Get MiroFish service health status with circuit breaker state."""
    try:
        from backend.services.mirofish_monitor import get_monitor
        monitor = get_monitor()
        metrics = monitor.get_health_metrics()
        state_info = monitor.get_state_info()

        return {
            "status": metrics.status,
            "latency_ms": round(metrics.latency_ms, 2),
            "error_rate": round(metrics.error_rate, 2),
            "circuit_breaker_state": metrics.circuit_breaker_state,
            "total_requests": metrics.total_requests,
            "failed_requests": metrics.failed_requests,
            "consecutive_failures": metrics.consecutive_failures,
            "last_success_time": metrics.last_success_time,
            "last_failure_time": metrics.last_failure_time,
            "state_info": state_info,
        }
    except Exception as e:
        logger.error(f"Failed to get MiroFish health: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "circuit_breaker_state": "UNKNOWN"}
