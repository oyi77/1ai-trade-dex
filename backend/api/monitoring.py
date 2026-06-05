"""Monitoring endpoints for profitability, venue parity, and paper/live checks."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from loguru import logger

from backend.db.utils import get_db_session
from backend.models.database import BotState, Trade
from backend.api.system import get_stats
from backend.core.paper_pnl_audit import audit_paper_pnl

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/summary")
async def monitoring_summary(db: Session = Depends(get_db_session)):
    """Single-shot monitoring snapshot."""
    try:
        # call get_stats to get all stats response fields
        stats = await get_stats(db=db, mode=None)
        stats_dict = stats.model_dump(mode="json")

        # 1) profitability snapshot
        summary = {
            "profitability": {
                "paper_pnl": stats_dict.get("paper", {}).get("pnl", 0.0),
                "paper_bankroll": stats_dict.get("paper", {}).get("bankroll", 0.0),
                "live_pnl": stats_dict.get("live", {}).get("pnl", 0.0),
                "testnet_pnl": stats_dict.get("testnet", {}).get("pnl", 0.0),
                "pnl_source": stats_dict.get("pnl_source", "unknown"),
            },
            "paper_live_match": {
                "pnl_delta": stats_dict.get("live", {}).get("pnl", 0.0)
                - stats_dict.get("paper", {}).get("pnl", 0.0),
                "bankroll_delta": stats_dict.get("live", {}).get("bankroll", 0.0)
                - stats_dict.get("paper", {}).get("bankroll", 0.0),
            },
            "db_platform_match": {
                "message": "Use reconcile_bot_state(apply=True) to compare DB vs venue balances.",
            },
            "platform_coverage": {
                "message": "Check PLATFORM_COVERAGE.md for per-platform implementation status.",
            },
        }

        # 2) audit recalculation report (paper)
        paper_report = audit_paper_pnl(db)
        summary["paper_pnl_audit"] = {
            "audit": paper_report,
        }

        return summary
    except Exception as e:
        logger.exception("monitoring_summary failed: {}", e)
        raise
