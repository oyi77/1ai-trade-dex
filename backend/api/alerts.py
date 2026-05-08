"""API endpoints for system alerts."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any

from backend.models.database import get_db
from backend.api.auth import require_admin
from backend.core.alert_manager import AlertManager, get_system_metrics

router = APIRouter()


@router.get("/alerts")
async def get_alerts(
    limit: int = Query(100, ge=1, le=1000),
    alert_type: Optional[str] = None,
    severity: Optional[str] = None,
    resolved: Optional[bool] = None,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get recent system alerts with optional filtering.

    Query Parameters:
    - limit: Maximum number of alerts to return (1-1000, default 100)
    - alert_type: Filter by alert type (CIRCUIT_BREAKER, ERROR_RATE, MEMORY_USAGE, DISK_SPACE, CONNECTION_POOL)
    - severity: Filter by severity (CRITICAL, HIGH, MEDIUM, LOW, INFO)
    - resolved: Filter by resolved status (true/false)
    """
    manager = AlertManager(db)
    alerts = manager.get_recent_alerts(
        limit=limit,
        alert_type=alert_type,
        severity=severity,
        resolved=resolved
    )

    stats = manager.get_alert_stats()
    metrics = get_system_metrics()

    return {
        "alerts": alerts,
        "stats": stats,
        "system_metrics": metrics,
        "total": len(alerts)
    }


@router.get("/alerts/stats")
async def get_alert_statistics(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get alert statistics grouped by type and severity."""
    manager = AlertManager(db)
    return manager.get_alert_stats()


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
) -> Dict[str, Any]:
    """Mark an alert as resolved."""
    manager = AlertManager(db)
    success = manager.resolve_alert(alert_id)

    if success:
        return {"success": True, "message": f"Alert {alert_id} resolved"}
    else:
        return {"success": False, "message": f"Alert {alert_id} not found"}


@router.get("/metrics")
async def get_metrics() -> Dict[str, Any]:
    """Get current system metrics (memory, disk, connection pool)."""
    return get_system_metrics()
