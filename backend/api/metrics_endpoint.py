"""Metrics endpoint for performance monitoring."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Dict
from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.database import get_db, PerformanceMetric
from backend.api.auth import require_admin
from backend.monitoring.performance_tracker import get_performance_tracker
from loguru import logger
router = APIRouter(tags=["metrics"])


class MetricsSummary(BaseModel):
    """Performance metrics summary response."""
    request_duration: Dict[str, float]
    db_query_time: Dict[str, float]
    websocket_latency: Dict[str, float]
    system: Dict[str, float]
    timestamp: str


class HistoricalMetrics(BaseModel):
    """Historical metrics response."""
    metric_type: str
    period_hours: int
    data_points: int
    metrics: Dict


@router.get("", response_model=MetricsSummary)
async def get_system_metrics(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """
    Get current system performance metrics.

    Returns:
    - Request duration: p50, p95, p99 percentiles
    - Database query time: p50, p95, p99 percentiles
    - WebSocket message latency: p50, p95, p99 percentiles
    - Memory usage: current MB and percentage
    - CPU usage: current percentage
    """
    tracker = get_performance_tracker()
    summary = tracker.get_metrics_summary()

    return MetricsSummary(
        request_duration=summary["request_duration"],
        db_query_time=summary["db_query_time"],
        websocket_latency=summary["websocket_latency"],
        system=summary["system"],
        timestamp=datetime.now(timezone.utc).isoformat()
    )


@router.get("/history", response_model=HistoricalMetrics)
async def get_historical_metrics(
    metric_type: str = Query("request", description="Metric type: request, db_query, websocket, system"),
    hours: int = Query(24, ge=1, le=168, description="Hours of history (1-168)"),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """
    Get historical performance metrics.

    Query parameters:
    - metric_type: Type of metric (request, db_query, websocket, system)
    - hours: Number of hours of history (1-168, default 24)

    Returns aggregated metrics over time.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    try:
        if metric_type == "request":
            # Aggregate request metrics
            results = db.query(
                func.avg(PerformanceMetric.duration_ms).label("avg_ms"),
                func.min(PerformanceMetric.duration_ms).label("min_ms"),
                func.max(PerformanceMetric.duration_ms).label("max_ms"),
                func.count(PerformanceMetric.id).label("count"),
                PerformanceMetric.endpoint
            ).filter(
                PerformanceMetric.metric_type == "request",
                PerformanceMetric.timestamp >= cutoff
            ).group_by(PerformanceMetric.endpoint).all()

            metrics = {
                "endpoints": [
                    {
                        "endpoint": r.endpoint,
                        "avg_ms": round(r.avg_ms, 2) if r.avg_ms else 0,
                        "min_ms": round(r.min_ms, 2) if r.min_ms else 0,
                        "max_ms": round(r.max_ms, 2) if r.max_ms else 0,
                        "count": r.count
                    }
                    for r in results
                ]
            }

        elif metric_type == "db_query":
            # Aggregate DB query metrics
            results = db.query(
                func.avg(PerformanceMetric.query_duration_ms).label("avg_ms"),
                func.min(PerformanceMetric.query_duration_ms).label("min_ms"),
                func.max(PerformanceMetric.query_duration_ms).label("max_ms"),
                func.count(PerformanceMetric.id).label("count"),
                PerformanceMetric.query_type
            ).filter(
                PerformanceMetric.metric_type == "db_query",
                PerformanceMetric.timestamp >= cutoff
            ).group_by(PerformanceMetric.query_type).all()

            metrics = {
                "query_types": [
                    {
                        "query_type": r.query_type,
                        "avg_ms": round(r.avg_ms, 2) if r.avg_ms else 0,
                        "min_ms": round(r.min_ms, 2) if r.min_ms else 0,
                        "max_ms": round(r.max_ms, 2) if r.max_ms else 0,
                        "count": r.count
                    }
                    for r in results
                ]
            }

        elif metric_type == "websocket":
            # Aggregate WebSocket metrics
            results = db.query(
                func.avg(PerformanceMetric.ws_latency_ms).label("avg_ms"),
                func.min(PerformanceMetric.ws_latency_ms).label("min_ms"),
                func.max(PerformanceMetric.ws_latency_ms).label("max_ms"),
                func.count(PerformanceMetric.id).label("count"),
                PerformanceMetric.ws_message_type
            ).filter(
                PerformanceMetric.metric_type == "websocket",
                PerformanceMetric.timestamp >= cutoff
            ).group_by(PerformanceMetric.ws_message_type).all()

            metrics = {
                "message_types": [
                    {
                        "message_type": r.ws_message_type,
                        "avg_ms": round(r.avg_ms, 2) if r.avg_ms else 0,
                        "min_ms": round(r.min_ms, 2) if r.min_ms else 0,
                        "max_ms": round(r.max_ms, 2) if r.max_ms else 0,
                        "count": r.count
                    }
                    for r in results
                ]
            }

        elif metric_type == "system":
            # Get system resource metrics over time
            results = db.query(
                PerformanceMetric.timestamp,
                PerformanceMetric.memory_usage_mb,
                PerformanceMetric.memory_percent,
                PerformanceMetric.cpu_percent
            ).filter(
                PerformanceMetric.metric_type == "system",
                PerformanceMetric.timestamp >= cutoff
            ).order_by(PerformanceMetric.timestamp.desc()).limit(100).all()

            metrics = {
                "samples": [
                    {
                        "timestamp": r.timestamp.isoformat(),
                        "memory_mb": round(r.memory_usage_mb, 2) if r.memory_usage_mb else 0,
                        "memory_percent": round(r.memory_percent, 2) if r.memory_percent else 0,
                        "cpu_percent": round(r.cpu_percent, 2) if r.cpu_percent else 0
                    }
                    for r in results
                ]
            }
        else:
            metrics = {"error": f"Unknown metric type: {metric_type}"}

        data_points = len(metrics.get("endpoints", metrics.get("query_types", metrics.get("message_types", metrics.get("samples", [])))))

        return HistoricalMetrics(
            metric_type=metric_type,
            period_hours=hours,
            data_points=data_points,
            metrics=metrics
        )

    except Exception as e:
        logger.error(f"Failed to fetch historical metrics: {e}", exc_info=True)
        return HistoricalMetrics(
            metric_type=metric_type,
            period_hours=hours,
            data_points=0,
            metrics={"error": str(e)}
        )


@router.post("/cleanup")
async def cleanup_old_metrics(
    days: int = Query(30, ge=1, le=365, description="Delete metrics older than N days"),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """
    Manually trigger cleanup of old performance metrics.

    Query parameters:
    - days: Delete metrics older than this many days (default: 30)
    """
    tracker = get_performance_tracker()
    deleted = tracker.cleanup_old_metrics(db, days=days)

    return {
        "status": "ok",
        "deleted_count": deleted,
        "days": days
    }
