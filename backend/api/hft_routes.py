"""HFT routes - metrics, strategies, toggle."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime

from backend.config import settings
from backend.models.database import get_db, StrategyConfig
from backend.api.auth import require_admin
from loguru import logger


router = APIRouter(tags=["hft"])

_hft_enabled_cache: set = {"universal_scanner", "probability_arb", "whale_frontrun"}


def _iso(dt) -> str | None:
    """Safely convert a datetime or string to ISO format.

    SQLite stores dates as strings, PostgreSQL as datetime objects.
    This handles both cases without crashing.
    """
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    if isinstance(dt, str):
        return dt  # Already a string from SQLite
    return str(dt)


@router.get("/hft/metrics")
async def hft_metrics():
    from backend.monitoring.hft_metrics import get_hft_summary

    summary = get_hft_summary()
    return {
        "signals_per_second": summary.get("signals_per_second", 0.0),
        "avg_signal_latency_ms": summary.get("avg_latency_ms", 0.0),
        "executor_latency_ms": summary.get("executor_latency_ms", 0.0),
        "dispatcher_queue_size": summary.get("queue_size", 0),
        "active_strategies": summary.get("active_strategies", 0),
        "arb_opportunities": summary.get("arb_opportunities", 0),
        "whale_activities": summary.get("whale_activities", 0),
        "orderbook_updates_per_sec": summary.get("orderbook_updates_per_sec", 0.0),
        "ws_connected": True,
    }


@router.get("/hft/strategies")
async def hft_strategies(db: Session = Depends(get_db)):
    from backend.strategies.registry import STRATEGY_REGISTRY

    hft_names = {
        "universal_scanner",
        "probability_arb",
        "unified_arb",
        "whale_frontrun",
    }
    strategies = []
    for name in STRATEGY_REGISTRY:
        if name in hft_names:
            config = (
                db.query(StrategyConfig)
                .filter(StrategyConfig.strategy_name == name)
                .first()
            )
            strategies.append(
                {
                    "name": name,
                    "enabled": config.enabled if config else True,
                    "signals_generated": 0,
                    "last_signal_at": (
                        _iso(config.updated_at)
                        if config and config.updated_at
                        else None
                    ),
                    "pnl": 0.0,
                    "mode": config.trading_mode or "paper" if config else "paper",
                }
            )
    if not strategies:
        for name in hft_names:
            config = (
                db.query(StrategyConfig)
                .filter(StrategyConfig.strategy_name == name)
                .first()
            )
            strategies.append(
                {
                    "name": name,
                    "enabled": config.enabled if config else True,
                    "signals_generated": 0,
                    "last_signal_at": None,
                    "pnl": 0.0,
                    "mode": "paper",
                }
            )
    return {"strategies": strategies}


@router.post("/hft/strategies/toggle")
async def hft_strategy_toggle(
    req: dict,
    _: None = Depends(require_admin),
):
    global _hft_enabled_cache
    name = req.get("name", "")
    enabled = bool(req.get("enabled", False))
    if enabled:
        _hft_enabled_cache.add(name)
    else:
        _hft_enabled_cache.discard(name)
    return {"name": name, "enabled": enabled, "status": "ok"}