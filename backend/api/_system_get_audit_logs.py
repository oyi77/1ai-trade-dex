"""Carved verbatim out of ``backend/api/system.py`` — statements moved, no logic changed."""

from ._system_get_strategy_stats import (
    AuditLogResponse,
)

from .system import (
    BaseModel,
    Depends,
    List,
    Optional,
    Query,
    Session,
    get_db,
    require_admin,
    router,
)

from . import system as _facade

@router.get("/system/audit-logs", response_model=List[AuditLogResponse])
async def get_audit_logs(
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    entity_id: Optional[str] = Query(None, description="Filter by entity ID"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    since: Optional[str] = Query(
        None, description="Filter logs since timestamp (ISO format)"
    ),
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of logs to return"
    ),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """
    Retrieve audit logs for configuration changes and system events.

    Returns audit trail entries with filtering and pagination support.
    """
    try:
        query = db.query(_facade.AuditLog)

        if event_type:
            query = query.filter(_facade.AuditLog.event_type == event_type)

        if entity_type:
            query = query.filter(_facade.AuditLog.entity_type == entity_type)

        if entity_id:
            query = query.filter(_facade.AuditLog.entity_id == entity_id)

        if user_id:
            query = query.filter(_facade.AuditLog.user_id == user_id)

        if since:
            try:
                since_dt = _facade.datetime.fromisoformat(since.replace("Z", "+00:00"))
                query = query.filter(_facade.AuditLog.timestamp >= since_dt)
            except ValueError:
                raise _facade.HTTPException(status_code=400, detail="Invalid timestamp format")

        _total = query.count()

        logs = (
            query.order_by(_facade.AuditLog.timestamp.desc()).offset(offset).limit(limit).all()
        )

        return [
            _facade.AuditLogResponse(
                id=log.id,
                timestamp=log.timestamp,
                event_type=log.event_type,
                entity_type=log.entity_type,
                entity_id=log.entity_id,
                old_value=log.old_value,
                new_value=log.new_value,
                user_id=log.user_id,
            )
            for log in logs
        ]

    except _facade.HTTPException:
        raise
    except Exception as e:
        _facade.logger.error(f"Failed to retrieve audit logs: {e}", exc_info=True)
        raise _facade.HTTPException(status_code=500, detail="Failed to retrieve audit logs")
class HealthStatus(BaseModel):
    """Basic health status response."""

    status: str
    agi_events: dict = {}  # "healthy" or "unhealthy"
class ReadinessStatus(BaseModel):
    """Readiness check with dependency status."""

    status: str  # "ready" or "not_ready"
    database: str  # "connected" or "disconnected"
    redis: _facade.Optional[str] = (
        None  # "connected", "disconnected", or None if not configured
    )
class DetailedHealthStatus(BaseModel):
    status: str
    timestamp: str
    database: dict
    redis: _facade.Optional[dict] = None
    disk_space: dict
    memory: dict
    uptime_seconds: _facade.Optional[float] = None
    circuit_breakers: _facade.Optional[dict] = None
    avg_signal_time_ms: _facade.Optional[float] = None
    signals_24h: _facade.Optional[int] = None
    trades_24h: _facade.Optional[int] = None
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
        _facade.logger.exception("Failed to check AGI health in liveness endpoint")
    return {"status": "healthy", "agi_events": agi_health}
@router.get("/system/connection-limits")
async def get_connection_limits(db: Session = Depends(get_db)):
    """Get current connection limits and usage metrics."""
    from backend.api.connection_limits import connection_limiter

    metrics = await connection_limiter.get_metrics()
    return {
        "timestamp": _facade.datetime.now(_facade.timezone.utc).isoformat(),
        "connection_limits": metrics,
    }
@router.post("/redeem")
async def redeem_positions(
    _: None = Depends(require_admin),
    dry_run: bool = Query(
        True, description="If true, only report what would be redeemed"
    ),
):
    from backend.core.settlement.auto_redeem import redeem_all_redeemable

    wallet = _facade.settings.POLYMARKET_BUILDER_ADDRESS or ""
    private_key = _facade.settings.POLYMARKET_PRIVATE_KEY or ""
    if not wallet or not private_key:
        raise _facade.HTTPException(
            status_code=500,
            detail="POLYMARKET_BUILDER_ADDRESS or POLYMARKET_PRIVATE_KEY not set",
        )
    result = redeem_all_redeemable(
        wallet=wallet,
        private_key=private_key,
        builder_api_key=_facade.settings.POLYMARKET_BUILDER_API_KEY,
        builder_secret=_facade.settings.POLYMARKET_BUILDER_SECRET,
        builder_passphrase=_facade.settings.POLYMARKET_BUILDER_PASSPHRASE,
        dry_run=dry_run,
    )
    return {
        "status": "dry_run" if dry_run else "executed",
        "attempted": result.total_attempted,
        "redeemed": result.total_redeemed,
        "failed": result.total_failed,
        "usdc_recovered": result.total_usdc_recovered,
        "errors": result.errors,
        "results": [
            {
                "condition_id": r.condition_id,
                "success": r.success,
                "tx_hash": r.tx_hash,
                "error": r.error,
            }
            for r in result.results
        ],
    }
