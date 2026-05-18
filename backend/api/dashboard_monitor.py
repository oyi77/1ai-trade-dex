"""G-21: Monitoring dashboard endpoint — active strategies, gate status, daily PnL, risk alerts."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.database import SessionLocal, Trade, BotState, StrategyConfig

from loguru import logger

router = APIRouter(tags=["dashboard-monitor"])


def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/api/v1/dashboard/monitor")
async def get_dashboard_monitor(db: Session = Depends(_get_db)):
    """Return active strategies, gate status, daily PnL, and risk alerts."""
    try:
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Active strategies with gate status
        configs = db.query(StrategyConfig).all()
        strategies = []
        for cfg in configs:
            mode = (cfg.mode or "paper").lower()
            gate_status = "live" if mode == "live" else "shadow" if mode == "shadow" else "fronttest" if cfg.enabled else "paper"
            strategies.append({
                "name": cfg.strategy_name,
                "enabled": cfg.enabled,
                "mode": mode,
                "gate_status": gate_status,
                "interval_seconds": cfg.interval_seconds or 60,
            })

        # Daily PnL by strategy
        daily_pnl_rows = (
            db.query(
                Trade.strategy,
                func.coalesce(func.sum(func.coalesce(Trade.pnl, -Trade.size)), 0.0).label("pnl"),
                func.count(Trade.id).label("trade_count"),
            )
            .filter(
                Trade.settled.is_(True),
                Trade.settlement_time >= today_start,
            )
            .group_by(Trade.strategy)
            .all()
        )
        daily_pnl = {
            row.strategy: {"pnl": round(float(row.pnl), 2), "trades": row.trade_count}
            for row in daily_pnl_rows
        }

        # Total daily PnL
        total_daily_pnl = sum(v["pnl"] for v in daily_pnl.values())

        # Risk alerts: strategies with negative daily PnL > $20
        risk_alerts = [
            {"strategy": name, "daily_loss": abs(data["pnl"]), "trades": data["trades"]}
            for name, data in daily_pnl.items()
            if data["pnl"] < -20
        ]

        # Bot state
        state = db.query(BotState).first()
        bot_running = state.is_running if state else False
        bankroll = float(state.bankroll or 0) if state else 0.0

        return {
            "timestamp": now.isoformat(),
            "bot_running": bot_running,
            "bankroll": round(bankroll, 2),
            "strategies": strategies,
            "daily_pnl": daily_pnl,
            "total_daily_pnl": round(total_daily_pnl, 2),
            "risk_alerts": risk_alerts,
            "active_count": sum(1 for s in strategies if s["enabled"]),
            "live_count": sum(1 for s in strategies if s["gate_status"] == "live"),
        }
    except Exception as e:
        logger.opt(exception=True).error(f"[dashboard_monitor] Error: {e}")
        return {"error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}
