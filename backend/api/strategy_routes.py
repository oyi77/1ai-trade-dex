"""Strategy management endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from sqlalchemy import func, case
from sqlalchemy.orm import Session
import json as _json

from backend.config import settings
from backend.models.database import (
    get_db,
    StrategyConfig,
    Trade,
    BotState,
    Signal,
    TradeAttempt,
)
from backend.api.auth import require_admin
from backend.api.validation import (
    StrategyConfigRequest as ValidatedStrategyConfigRequest,
)
from loguru import logger

router = APIRouter(tags=["system"])


def _iso(dt) -> str | None:
    """Safely convert a datetime or string to ISO format."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    if isinstance(dt, str):
        return dt
    return str(dt)


@router.get("/strategies")
async def list_strategies(
    db: Session = Depends(get_db),
):
    """List all registered strategies with their DB config."""
    from backend.strategies.registry import STRATEGY_REGISTRY

    db_configs = {c.strategy_name: c for c in db.query(StrategyConfig).all()}

    # Map of strategy -> required credential keys
    STRATEGY_CREDENTIALS = {
        "kalshi_arb": ["KALSHI_API_KEY"],
        "copy_trader": ["POLYMARKET_PRIVATE_KEY"],
        "crypto_oracle": [],
        "weather_emos": [],
        "general_market_scanner": [],
        "whale_pnl_tracker": [],
        "bond_scanner": [],
        "market_maker": ["POLYMARKET_PRIVATE_KEY"],
    }

    result = []
    for name, cls in STRATEGY_REGISTRY.items():
        cfg = db_configs.get(name)
        required_creds = STRATEGY_CREDENTIALS.get(name, [])
        result.append(
            {
                "name": name,
                "description": getattr(cls, "description", ""),
                "category": getattr(cls, "category", "general"),
                "enabled": cfg.enabled if cfg else False,
                "interval_seconds": cfg.interval_seconds if cfg else 60,
                "params": _json.loads(cfg.params) if cfg and cfg.params else {},
                "default_params": dict(getattr(cls, "default_params", {})),
                "updated_at": _iso(cfg.updated_at) if cfg and cfg.updated_at else None,
                "required_credentials": required_creds,
                "trading_mode": cfg.trading_mode if cfg else None,
            }
        )
    return result


@router.get("/strategies/health")
async def get_strategies_health(db: Session = Depends(get_db)):
    """Return health metrics, heartbeat, last signal, and rejections per strategy."""
    from backend.strategies.registry import STRATEGY_REGISTRY
    from backend.strategies.loader import load_all_strategies
    from backend.models.database import StrategyConfig, BotState, Signal, TradeAttempt
    from backend.config import settings

    if not STRATEGY_REGISTRY:
        load_all_strategies()

    db_configs = {c.strategy_name: c for c in db.query(StrategyConfig).all()}
    bot_states = {state.mode: state for state in db.query(BotState).all()}

    result = []
    for name, cls in STRATEGY_REGISTRY.items():
        cfg = db_configs.get(name)
        enabled = cfg.enabled if cfg else False
        effective_mode = (
            cfg.trading_mode or settings.TRADING_MODE if cfg else settings.TRADING_MODE
        )

        bot_state = bot_states.get(effective_mode)
        last_heartbeat = None
        scan_stats = {}
        if bot_state and bot_state.misc_data:
            try:
                misc = (
                    _json.loads(bot_state.misc_data)
                    if isinstance(bot_state.misc_data, str)
                    else bot_state.misc_data
                )
                last_heartbeat = misc.get(f"heartbeat:{name}")
                scan_stats = misc.get(f"scan_stats:{name}", {})
            except Exception:
                logger.warning(f"Failed to parse misc_data for mode {effective_mode}")

        last_signal = (
            db.query(Signal)
            .filter(
                Signal.track_name == name,
                Signal.execution_mode == effective_mode,
            )
            .order_by(Signal.timestamp.desc())
            .first()
        )
        last_signal_details = None
        if last_signal:
            last_signal_details = {
                "timestamp": _iso(last_signal.timestamp),
                "market_ticker": last_signal.market_ticker,
                "direction": last_signal.direction,
                "model_probability": last_signal.model_probability,
                "market_price": last_signal.market_price,
                "edge": last_signal.edge,
                "confidence": last_signal.confidence,
                "reasoning": last_signal.reasoning,
            }

        recent_rejections = (
            db.query(TradeAttempt)
            .filter(
                TradeAttempt.strategy == name,
                TradeAttempt.mode == effective_mode,
                TradeAttempt.status.in_(("REJECTED", "BLOCKED", "FAILED")),
            )
            .order_by(TradeAttempt.created_at.desc())
            .limit(10)
            .all()
        )
        rejections_details = [
            {
                "timestamp": _iso(rej.created_at),
                "market_ticker": rej.market_ticker,
                "status": rej.status,
                "phase": rej.phase,
                "reason_code": rej.reason_code,
                "reason": rej.reason,
                "requested_size": rej.requested_size,
                "adjusted_size": rej.adjusted_size,
            }
            for rej in recent_rejections
        ]

        result.append(
            {
                "strategy": name,
                "enabled": enabled,
                "trading_mode": effective_mode,
                "last_heartbeat": last_heartbeat,
                "last_scan_time": scan_stats.get("last_scan_time"),
                "markets_scanned": scan_stats.get("markets_scanned", 0),
                "signals_had_edge": scan_stats.get("signals_had_edge", 0),
                "signals_rejected": scan_stats.get("signals_rejected", 0),
                "trades_executed": scan_stats.get("trades_executed", 0),
                "last_signal": last_signal_details,
                "rejections": rejections_details,
            }
        )

    return result


@router.get("/strategies/compare")
async def compare_strategies(db: Session = Depends(get_db)):
    """Compare active strategies side-by-side using PnL and AGI health metrics."""
    from backend.models.database import Trade
    from backend.models.outcome_tables import StrategyHealthRecord
    from sqlalchemy import case

    all_health = (
        db.query(StrategyHealthRecord)
        .order_by(StrategyHealthRecord.last_updated.desc())
        .all()
    )
    latest_health = {}
    for h in all_health:
        if h.strategy not in latest_health:
            latest_health[h.strategy] = h

    trade_stats = (
        db.query(
            Trade.strategy,
            func.count(Trade.id).label("total_trades"),
            func.sum(
                case(
                    (Trade.settled.is_(True), case((Trade.pnl > 0, 1), else_=0)),
                    else_=0,
                )
            ).label("wins"),
            func.sum(
                case(
                    (Trade.settled.is_(True), case((Trade.pnl <= 0, 1), else_=0)),
                    else_=0,
                )
            ).label("losses"),
            func.sum(case((Trade.settled, Trade.pnl), else_=0)).label("total_pnl"),
            func.avg(Trade.edge_at_entry).label("avg_edge"),
            func.avg(Trade.size).label("avg_size"),
        )
        .filter(Trade.strategy.isnot(None), Trade.source == "bot")
        .group_by(Trade.strategy)
        .all()
    )

    comparison = {}
    for r in trade_stats:
        strat = r.strategy
        h = latest_health.get(strat)
        total_wr_trades = r.wins + r.losses
        comparison[strat] = {
            "total_trades": r.total_trades,
            "wins": r.wins,
            "losses": r.losses,
            "win_rate": (
                r.wins / total_wr_trades
                if total_wr_trades > 0
                else (h.win_rate if h else 0.0)
            ),
            "total_pnl": round(r.total_pnl or 0, 2),
            "avg_edge": round(r.avg_edge or 0, 4),
            "avg_size": round(r.avg_size or 0, 2),
            "sharpe": h.sharpe if h else 0.0,
            "max_drawdown": h.max_drawdown if h else None,
            "brier_score": h.brier_score if h else None,
            "psi_score": h.psi_score if h else None,
            "status": h.status if h else "active",
        }

    # Strategies with health records but no trades yet
    for strat, h in latest_health.items():
        if strat not in comparison:
            comparison[strat] = {
                "total_trades": h.total_trades,
                "wins": h.wins,
                "losses": h.losses,
                "win_rate": h.win_rate,
                "total_pnl": 0.0,
                "avg_edge": 0.0,
                "avg_size": 0.0,
                "sharpe": h.sharpe,
                "max_drawdown": h.max_drawdown,
                "brier_score": h.brier_score,
                "psi_score": h.psi_score,
                "status": h.status,
            }

    return comparison


class StrategyUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    interval_seconds: Optional[int] = None
    params: Optional[dict] = None
    trading_mode: Optional[str] = None


@router.get("/strategies/{name}")
async def get_strategy(
    name: str,
    db: Session = Depends(get_db),
):
    """Get a single strategy config by name."""
    from backend.strategies.registry import get_strategy_class
    from backend.strategies.loader import load_all_strategies
    from backend.strategies.registry import STRATEGY_REGISTRY

    if not STRATEGY_REGISTRY:
        load_all_strategies()
    if name not in STRATEGY_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")
    cfg = db.query(StrategyConfig).filter(StrategyConfig.strategy_name == name).first()
    try:
        cls = get_strategy_class(name)
        description = getattr(cls, "description", name)
        category = getattr(cls, "category", "general")
        default_params = getattr(cls, "default_params", {})
    except Exception:
        logger.exception(
            f"Failed to get strategy class '{name}', using fallback defaults"
        )
        description, category, default_params = name, "unknown", {}
    return {
        "name": name,
        "description": description,
        "category": category,
        "enabled": cfg.enabled if cfg else True,
        "interval_seconds": cfg.interval_seconds if cfg else 300,
        "params": _json.loads(cfg.params) if cfg and cfg.params else {},
        "default_params": default_params,
        "updated_at": _iso(cfg.updated_at) if cfg and cfg.updated_at else None,
        "trading_mode": cfg.trading_mode if cfg else None,
    }


@router.put("/strategies/{name}")
async def update_strategy(
    name: str,
    body: ValidatedStrategyConfigRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Update a strategy's config (enabled, interval, params)."""
    from backend.strategies.registry import STRATEGY_REGISTRY
    from backend.models.audit_logger import log_audit_event

    if name not in STRATEGY_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")

    cfg = db.query(StrategyConfig).filter(StrategyConfig.strategy_name == name).first()

    old_state = None
    if cfg:
        old_state = {
            "enabled": cfg.enabled,
            "interval_seconds": cfg.interval_seconds,
            "params": _json.loads(cfg.params) if cfg.params else {},
            "trading_mode": cfg.trading_mode,
        }
    else:
        cfg = StrategyConfig(strategy_name=name)
        db.add(cfg)

    if body.enabled is not None:
        cfg.enabled = body.enabled
    if body.interval_seconds is not None:
        cfg.interval_seconds = body.interval_seconds
    if body.params is not None:
        cfg.params = _json.dumps(body.params)
    if body.trading_mode is not None:
        valid_modes = ["paper", "testnet", "live", None]
        if body.trading_mode not in valid_modes:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid trading_mode '{body.trading_mode}'. Must be one of: paper, testnet, live",
            )
        cfg.trading_mode = body.trading_mode

    new_state = {
        "enabled": cfg.enabled,
        "interval_seconds": cfg.interval_seconds,
        "params": _json.loads(cfg.params) if cfg.params else {},
        "trading_mode": cfg.trading_mode,
    }

    log_audit_event(
        db=db,
        event_type="STRATEGY_CONFIG_UPDATED",
        entity_type="STRATEGY_CONFIG",
        entity_id=name,
        old_value=old_state,
        new_value=new_state,
        user_id="admin",
    )

    db.commit()
    db.refresh(cfg)

    if body.interval_seconds is not None or body.enabled is not None:
        from backend.core.scheduling.scheduler import schedule_strategy, unschedule_strategy

        if cfg.enabled:
            schedule_strategy(name, cfg.interval_seconds or 60, mode=cfg.trading_mode or "paper")
        else:
            unschedule_strategy(name, mode=cfg.trading_mode or "paper")

    return {
        "name": name,
        "enabled": cfg.enabled,
        "interval_seconds": cfg.interval_seconds,
        "params": _json.loads(cfg.params) if cfg.params else {},
        "updated_at": _iso(cfg.updated_at),
        "trading_mode": cfg.trading_mode,
    }


@router.post("/strategies/{name}/run-now")
async def run_strategy_now(name: str, _: None = Depends(require_admin)):
    """Trigger an immediate strategy run."""
    from backend.strategies.registry import STRATEGY_REGISTRY, create_strategy

    if name not in STRATEGY_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")

    # Build a proper StrategyContext and run the strategy
    try:
        from backend.strategies.base import StrategyContext
        from backend.models.database import BotState, StrategyConfig
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            # STRAT-13 FIX: Use create_strategy() to check if strategy is enabled
            instance = create_strategy(name, db=db)
            cfg = (
                db.query(StrategyConfig)
                .filter(StrategyConfig.strategy_name == name)
                .first()
            )
            strategy_mode = (
                cfg.trading_mode if cfg and cfg.trading_mode else None
            ) or settings.TRADING_MODE

            state = db.query(BotState).filter_by(mode=strategy_mode).first()
            if not state:
                raise HTTPException(status_code=404, detail="Bot state not initialized")
            from backend.markets.provider_registry import market_registry

            ctx = StrategyContext(
                db=db,
                clob=None,
                settings=settings,
                logger=logger,
                params=dict(getattr(instance.__class__, "default_params", {})),
                mode=strategy_mode,
                market_registry=market_registry,
            )
            result = await instance.run(ctx)

            buy_decisions = [
                d
                for d in getattr(result, "decisions", [])
                if isinstance(d, dict)
                and d.get("decision") == "BUY"
                and d.get("market_ticker")
            ]

        # Execute decisions OUTSIDE the outer session — execute_decision opens
        # its own session per trade to avoid holding the caller session during
        # async I/O (prevents event-loop blocking and stale-session bugs).
        if buy_decisions:
            from backend.core.strategy_executor import execute_decisions

            execution_modes = (
                ["paper", "live"] if strategy_mode == "live" else [strategy_mode]
            )
            for mode in execution_modes:
                decisions_copy = [d.copy() for d in buy_decisions]
                for d in decisions_copy:
                    d["trading_mode"] = mode
                await execute_decisions(decisions_copy, name, mode)

        return {
            "status": "ok",
            "name": name,
            "decisions": result.decisions_recorded,
            "trades_attempted": result.trades_attempted,
            "errors": len(result.errors),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Manual run of strategy '{name}' failed: {e}")
        raise HTTPException(
            status_code=500, detail="Strategy run failed — check server logs"
        )
