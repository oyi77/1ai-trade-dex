"""Carved verbatim out of ``backend/api/system.py`` — statements moved, no logic changed."""

from ._system_iso import (
    EventResponse,
)

from .system import (
    BaseModel,
    Depends,
    List,
    Session,
    get_db,
    require_admin,
    router,
)

from . import system as _facade

@router.get("/stats/strategies")
async def get_strategy_stats(
    db: Session = Depends(get_db),
):
    """Return P&L breakdown per strategy."""
    from sqlalchemy import case

    results = (
        db.query(
            _facade.Trade.strategy,
            _facade.func.count(_facade.Trade.id).label("total_trades"),
            _facade.func.sum(
                case(
                    (_facade.Trade.settled.is_(True), case((_facade.Trade.pnl > 0, 1), else_=0)),
                    else_=0,
                )
            ).label("wins"),
            _facade.func.sum(
                case(
                    (_facade.Trade.settled.is_(True), case((_facade.Trade.pnl <= 0, 1), else_=0)),
                    else_=0,
                )
            ).label("losses"),
            _facade.func.sum(case((_facade.Trade.settled, _facade.Trade.pnl), else_=0)).label("total_pnl"),
            _facade.func.avg(_facade.Trade.edge_at_entry).label("avg_edge"),
            _facade.func.avg(_facade.Trade.size).label("avg_size"),
        )
        .filter(_facade.Trade.strategy.isnot(None), _facade.Trade.source == "bot")
        .group_by(_facade.Trade.strategy)
        .all()
    )

    strategies = []
    for r in results:
        total = r.wins + r.losses
        strategies.append(
            {
                "strategy": r.strategy or "unknown",
                "total_trades": r.total_trades,
                "wins": r.wins,
                "losses": r.losses,
                "pending": r.total_trades - r.wins - r.losses,
                "win_rate": r.wins / total if total > 0 else 0,
                "total_pnl": round(r.total_pnl or 0, 2),
                "avg_edge": round(r.avg_edge or 0, 4),
                "avg_size": round(r.avg_size or 0, 2),
            }
        )

    return {
        "strategies": sorted(strategies, key=lambda s: s["total_pnl"], reverse=True)
    }
@router.get("/ai/status")
async def get_ai_status(
    db: Session = Depends(get_db),
):
    """Return AI system status: enabled, provider, budget usage."""
    today_start = _facade.datetime.now(_facade.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    spent_today = (
        db.query(_facade.func.coalesce(_facade.func.sum(_facade.AILog.cost_usd), 0.0))
        .filter(_facade.AILog.timestamp >= today_start)
        .scalar()
        or 0.0
    )
    calls_today = (
        db.query(_facade.func.count(_facade.AILog.id)).filter(_facade.AILog.timestamp >= today_start).scalar()
        or 0
    )

    return {
        "enabled": _facade.settings.AI_ENABLED,
        "provider": _facade.settings.AI_PROVIDER,
        "model": _facade.settings.AI_MODEL or _facade.settings.GROQ_MODEL,
        "daily_budget": _facade.settings.AI_DAILY_BUDGET_USD,
        "spent_today": round(spent_today, 4),
        "remaining": round(max(0, _facade.settings.AI_DAILY_BUDGET_USD - spent_today), 4),
        "calls_today": calls_today,
        "signal_weight": _facade.settings.AI_SIGNAL_WEIGHT,
    }
@router.post("/ai/toggle")
async def toggle_ai(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    """Toggle AI-enhanced signals on/off."""
    from backend.models.audit_logger import log_audit_event

    old_value = _facade.settings.AI_ENABLED
    _facade.settings.AI_ENABLED = not _facade.settings.AI_ENABLED

    log_audit_event(
        db=db,
        event_type="AI_TOGGLE",
        entity_type="CONFIG",
        entity_id="ai_enabled",
        old_value={"enabled": old_value},
        new_value={"enabled": _facade.settings.AI_ENABLED},
        user_id="admin",
    )
    db.commit()

    _facade.logger.info("AI signals %s", "ENABLED" if _facade.settings.AI_ENABLED else "DISABLED")
    return {"enabled": _facade.settings.AI_ENABLED}
class ResetRequest(BaseModel):
    confirm: bool = False
class PaperTopupRequest(BaseModel):
    amount: float = _facade.Field(gt=0, description="USDC to add to paper bankroll")
    confirm: bool = False
class LiveAdjustRequest(BaseModel):
    amount: float = _facade.Field(
        description="USDC amount (positive=deposit, negative=withdraw)"
    )
    confirm: bool = False
class BacktestRequest(BaseModel):
    initial_bankroll: float = 1000.0
    max_trade_size: float = 100.0
    min_edge_threshold: float = 0.02
    start_date: str | None = None  # ISO format datetime
    end_date: str | None = None  # ISO format datetime
    market_types: list[str] = ["BTC", "Weather", "CopyTrader"]
    slippage_bps: int = 5  # basis points
@router.post("/backtest")
async def run_backtest(
    body: BacktestRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Run backtest against historical signals."""
    from backend.core.backtesting import BacktestEngine, BacktestConfig

    try:
        start_date = (
            _facade.datetime.fromisoformat(body.start_date) if body.start_date else None
        )
        end_date = _facade.datetime.fromisoformat(body.end_date) if body.end_date else None

        config = BacktestConfig(
            initial_bankroll=body.initial_bankroll,
            max_trade_size=body.max_trade_size,
            min_edge_threshold=body.min_edge_threshold,
            start_date=start_date,
            end_date=end_date,
            market_types=body.market_types,
            slippage_bps=body.slippage_bps,
        )

        engine = BacktestEngine(config)
        result = engine.run(db)

        return {
            "strategy_name": "signal_replay",
            "start_date": (start_date.isoformat() if start_date else body.start_date),
            "end_date": (end_date.isoformat() if end_date else body.end_date),
            "initial_bankroll": body.initial_bankroll,
            "results": {
                "summary": {
                    "total_signals": result.total_trades,
                    "total_trades": result.total_trades,
                    "winning_trades": result.winning_trades,
                    "losing_trades": result.losing_trades,
                    "win_rate": result.win_rate,
                    "initial_bankroll": body.initial_bankroll,
                    "final_equity": result.final_bankroll,
                    "total_pnl": result.total_pnl,
                    "total_return_pct": result.roi * 100,
                    "sharpe_ratio": result.sharpe_ratio,
                },
                "trade_log": [],
                "equity_curve": [],
            },
        }

    except Exception as e:
        _facade.logger.error(f"Backtest failed: {e}")
        raise _facade.HTTPException(
            status_code=500, detail="Backtest failed — check server logs"
        )
@router.get("/backtest/quick")
async def quick_backtest(
    days_back: int = 30,
    initial_bankroll: float = 1000.0,
    db: Session = Depends(get_db),
):
    """Quick backtest for recent N days."""
    from backend.core.backtesting import run_quick_backtest

    try:
        result = run_quick_backtest(
            db, days_back=days_back, initial_bankroll=initial_bankroll
        )

        return {
            "status": "success",
            "result": {
                "total_trades": result.total_trades,
                "winning_trades": result.winning_trades,
                "losing_trades": result.losing_trades,
                "total_pnl": result.total_pnl,
                "final_bankroll": result.final_bankroll,
                "win_rate": result.win_rate,
                "avg_win": result.avg_win,
                "avg_loss": result.avg_loss,
                "max_drawdown": result.max_drawdown,
                "sharpe_ratio": result.sharpe_ratio,
                "trades_per_day": result.trades_per_day,
                "roi": result.roi,
            },
        }

    except Exception as e:
        _facade.logger.error(f"Quick backtest failed: {e}")
        raise _facade.HTTPException(
            status_code=500, detail="Quick backtest failed — check server logs"
        )
@router.get("/events", response_model=List[EventResponse])
async def get_events(limit: int = 50):
    from backend.core.scheduling.scheduler import get_recent_events

    limit = min(limit, 500)
    events = get_recent_events(limit)
    return [
        _facade.EventResponse(
            timestamp=e["timestamp"],
            type=e["type"],
            message=e["message"],
            data=e.get("data", {}),
        )
        for e in events
    ]
@router.post("/run-scan")
async def run_scan(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    from backend.core.scheduling.scheduler import run_manual_scan, log_event

    for mode in _facade.settings.active_modes_set:
        state = _facade.for_update(db, db.query(_facade.BotState).filter_by(mode=mode)).first()
        if state:
            state.last_run = _facade.datetime.now(_facade.timezone.utc)
    db.commit()

    log_event("info", "Manual scan triggered (BTC + Weather)")
    await run_manual_scan()

    signals = await _facade.scan_for_signals()
    actionable = [s for s in signals if s.passes_threshold]

    result = {
        "status": "ok",
        "total_signals": len(signals),
        "actionable_signals": len(actionable),
        "timestamp": _facade.datetime.now(_facade.timezone.utc).isoformat(),
    }

    if _facade.settings.WEATHER_ENABLED:
        try:
            from backend.core.weather_signals import scan_for_weather_signals

            wx_signals = await scan_for_weather_signals()
            wx_actionable = [s for s in wx_signals if s.passes_threshold]
            result["weather_signals"] = len(wx_signals)
            result["weather_actionable"] = len(wx_actionable)
        except Exception:
            _facade.logger.exception("Failed to scan for weather signals in run_scan")
            result["weather_signals"] = 0
            result["weather_actionable"] = 0

    return result
@router.get("/signal-config")
async def get_signal_config():
    """Return current signal approval settings (no auth required, no secrets)."""
    return {
        "approval_mode": _facade.settings.SIGNAL_APPROVAL_MODE,
        "min_confidence": _facade.settings.AUTO_APPROVE_MIN_CONFIDENCE,
        "notification_duration_ms": _facade.settings.SIGNAL_NOTIFICATION_DURATION_MS,
    }
class StrategyUpdateRequest(BaseModel):
    enabled: _facade.Optional[bool] = None
    interval_seconds: _facade.Optional[int] = None
    params: _facade.Optional[dict] = None
    trading_mode: _facade.Optional[str] = None
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
        _facade.logger.error(f"Failed to get MiroFish health: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "circuit_breaker_state": "UNKNOWN"}
@router.get("/system/db-pool-stats")
async def get_db_pool_stats(_: None = Depends(require_admin)):
    """Get database connection pool statistics."""

    try:
        pool = _facade.engine.pool

        return {
            "pool_size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "queue_size": pool.size() - pool.checkedout() - pool.overflow(),
            "total_connections": pool.size() + pool.overflow(),
            "config": {
                "pool_size": 20,
                "max_overflow": 10,
                "pool_timeout": 30,
                "pool_recycle": 3600,
            },
        }
    except Exception as e:
        _facade.logger.error(f"Failed to get pool stats: {e}")
        raise _facade.HTTPException(
            status_code=500, detail="Failed to get pool stats"
        )
class AuditLogResponse(BaseModel):
    id: int
    timestamp: _facade.datetime
    event_type: str
    entity_type: str
    entity_id: str
    old_value: _facade.Optional[dict]
    new_value: _facade.Optional[dict]
    user_id: str
