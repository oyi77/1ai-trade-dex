"""Analytics API endpoints — strategy metrics, equity curve, calibration, experiments."""

import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.models.database import SessionLocal

logger = logging.getLogger("trading_bot.analytics")

router = APIRouter(prefix="/analytics", tags=["analytics"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/strategies")
def get_strategy_metrics(
    lookback_days: int = Query(30, ge=1, le=365),
    min_trades: int = Query(5, ge=1),
    db: Session = Depends(get_db),
):
    """Get per-strategy performance metrics ranked by risk-adjusted return."""
    from backend.core.strategy_ranker import strategy_ranker

    ranked = strategy_ranker.rank_all(
        db, lookback_days=lookback_days, min_trades=min_trades
    )

    return {
        "lookback_days": lookback_days,
        "strategies": [
            {
                "name": r.name,
                "rank_score": r.rank_score,
                "total_trades": r.total_trades,
                "winning_trades": r.winning_trades,
                "win_rate": r.win_rate,
                "total_pnl": r.total_pnl,
                "sharpe_ratio": r.sharpe_ratio,
                "sortino_ratio": r.sortino_ratio,
                "profit_factor": r.profit_factor,
                "max_drawdown": r.max_drawdown,
                "avg_return": r.avg_return,
            }
            for r in ranked
        ],
    }


@router.get("/equity-curve")
def get_equity_curve(
    limit: int = Query(90, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Get historical equity curve snapshots."""
    from backend.models.database import EquitySnapshot

    snapshots = (
        db.query(EquitySnapshot)
        .order_by(EquitySnapshot.timestamp.desc())
        .limit(limit)
        .all()
    )

    return {
        "snapshots": [
            {
                "timestamp": s.timestamp.isoformat() if s.timestamp else None,
                "bankroll": s.bankroll,
                "total_pnl": s.total_pnl,
                "open_exposure": s.open_exposure,
                "trade_count": s.trade_count,
                "win_count": s.win_count,
            }
            for s in reversed(snapshots)
        ]
    }


@router.get("/calibration/{strategy}")
def get_calibration(
    strategy: str,
    num_bins: int = Query(10, ge=3, le=20),
    db: Session = Depends(get_db),
):
    """Get model calibration curve for a strategy."""
    from backend.core.calibration_tracker import calibration_tracker

    summary = calibration_tracker.get_strategy_summary(db, strategy=strategy)
    return summary


@router.get("/calibration")
def get_calibration_all(
    num_bins: int = Query(10, ge=3, le=20),
    db: Session = Depends(get_db),
):
    """Get model calibration curve across all strategies."""
    from backend.core.calibration_tracker import calibration_tracker

    summary = calibration_tracker.get_strategy_summary(db, strategy=None)
    return summary


@router.get("/experiments")
def get_experiments(
    strategy: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Get experiment history for a strategy or all strategies."""
    from backend.core.experiment_tracker import experiment_tracker

    history = experiment_tracker.get_history(db, strategy_name=strategy, limit=limit)
    return {"experiments": history}


@router.get("/experiments/{experiment_id}/compare/{other_id}")
def compare_experiments(
    experiment_id: int,
    other_id: int,
    db: Session = Depends(get_db),
):
    """Compare two experiments."""
    from backend.core.experiment_tracker import experiment_tracker

    result = experiment_tracker.compare(db, experiment_id, other_id)
    return result


@router.get("/allocations")
def get_allocations(
    lookback_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Get recommended bankroll allocations across strategies."""
    from backend.core.strategy_ranker import strategy_ranker
    from backend.models.database import BotState
    from backend.config import settings

    state = db.query(BotState).first()
    bankroll = settings.INITIAL_BANKROLL
    if state:
        primary_mode = settings.TRADING_MODE
        if primary_mode == "paper":
            bankroll = float(
                state.paper_bankroll
                if state.paper_bankroll is not None
                else settings.INITIAL_BANKROLL
            )
        elif primary_mode == "testnet":
            bankroll = float(
                state.testnet_bankroll
                if state.testnet_bankroll is not None
                else settings.INITIAL_BANKROLL
            )
        else:
            bankroll = float(
                state.bankroll
                if state.bankroll is not None
                else settings.INITIAL_BANKROLL
            )

    allocations = strategy_ranker.auto_allocate(db, bankroll, lookback_days)
    return {
        "bankroll": bankroll,
        "lookback_days": lookback_days,
        "allocations": allocations,
    }


@router.get("/stats/impact-by-feature")
def get_impact_by_feature(
    feature_id: Optional[str] = Query(None, pattern="^(feature_2|feature_3|feature_4)$"),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    metric_type: Optional[str] = Query(None, pattern="^(win_rate|sharpe_ratio|pnl)$"),
    db: Session = Depends(get_db),
):
    """
    Get impact of Feature 2/3/4 changes on strategy performance stats.
    
    Shows how Activity Timeline events correlate with win rate, Sharpe ratio, and PnL.
    
    Query parameters:
    - feature_id: Filter by feature ('feature_2', 'feature_3', 'feature_4')
    - start_date: Start of date range (ISO 8601 format)
    - end_date: End of date range (ISO 8601 format)
    - metric_type: Filter by metric ('win_rate', 'sharpe_ratio', 'pnl')
    
    Returns:
    - List of feature impacts with before/after performance deltas
    """
    from backend.core.stats_correlator import stats_correlator
    
    date_range = None
    if start_date and end_date:
        date_range = (start_date, end_date)
    
    impacts = stats_correlator.get_feature_impact(
        db=db,
        feature_id=feature_id,
        date_range=date_range,
        metric_type=metric_type
    )
    
    return {
        "feature_id": feature_id,
        "date_range": {
            "start": start_date.isoformat() if start_date else None,
            "end": end_date.isoformat() if end_date else None
        },
        "metric_type": metric_type,
        "impacts": [
            {
                "feature_id": impact.feature_id,
                "feature_name": impact.feature_name,
                "event_count": impact.event_count,
                "win_rate": {
                    "before": impact.win_rate_before,
                    "after": impact.win_rate_after,
                    "delta": impact.win_rate_delta,
                    "delta_pct": (impact.win_rate_delta / impact.win_rate_before * 100) if impact.win_rate_before > 0 else 0
                },
                "sharpe_ratio": {
                    "before": impact.sharpe_ratio_before,
                    "after": impact.sharpe_ratio_after,
                    "delta": impact.sharpe_ratio_delta
                } if impact.sharpe_ratio_before is not None else None,
                "pnl": {
                    "before": impact.pnl_before,
                    "after": impact.pnl_after,
                    "delta": impact.pnl_delta,
                    "delta_pct": (impact.pnl_delta / abs(impact.pnl_before) * 100) if impact.pnl_before != 0 else 0
                },
                "sample_size": {
                    "before": impact.sample_size_before,
                    "after": impact.sample_size_after,
                    "total": impact.sample_size_before + impact.sample_size_after
                },
                "confidence_level": impact.confidence_level
            }
            for impact in impacts
        ]
    }


@router.get("/stats/activity-correlations")
def get_activity_correlations(
    strategy_name: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """
    Get correlations between Activity Timeline events and subsequent performance.
    
    Shows how individual activity events (task execution, signal approval, etc.)
    correlate with trading performance in the following 24 hours.
    
    Query parameters:
    - strategy_name: Filter by strategy name
    - limit: Maximum correlations to return (1-500, default 100)
    
    Returns:
    - List of activity-performance correlations with correlation scores
    """
    from backend.core.stats_correlator import stats_correlator
    
    correlations = stats_correlator.get_activity_correlations(
        db=db,
        strategy_name=strategy_name,
        limit=limit
    )
    
    return {
        "strategy_name": strategy_name,
        "limit": limit,
        "count": len(correlations),
        "correlations": [
            {
                "activity_id": corr.activity_id,
                "activity_timestamp": corr.activity_timestamp.isoformat(),
                "activity_type": corr.activity_type,
                "strategy_name": corr.strategy_name,
                "subsequent_performance": {
                    "trades": corr.trades_after,
                    "wins": corr.wins_after,
                    "win_rate": corr.win_rate_after,
                    "pnl": corr.pnl_after
                },
                "correlation_score": corr.correlation_score
            }
            for corr in correlations
        ]
    }
