"""Analytics API endpoints — strategy metrics, equity curve, calibration, experiments."""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.models.database import SessionLocal, Trade, EquitySnapshot
from backend.core.strategy_ranker import strategy_ranker
from backend.core.calibration_tracker import get_bucket_calibration
from backend.core.maker_taker_analytics import maker_taker_analytics
from backend.db.utils import get_db_session

router = APIRouter(prefix="/analytics", tags=["analytics"])


def get_db():
    with get_db_session() as db:
        yield db


@router.get("/strategies")
def get_strategy_metrics(
    lookback_days: int = Query(30, ge=1, le=365),
    min_trades: int = Query(5, ge=1),
    db: Session = Depends(get_db),
):
    """Get per-strategy performance metrics ranked by risk-adjusted return."""

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
    """Get historical equity curve data points from EquitySnapshot records."""
    snapshots = (
        db.query(EquitySnapshot)
        .order_by(EquitySnapshot.timestamp.asc())
        .limit(limit)
        .all()
    )
    if not snapshots:
        return {"equity_curve": []}

    return {
        "lookback_limit": limit,
        "equity_curve": [
            {
                "timestamp": snap.timestamp.isoformat() if snap.timestamp else None,
                # bankroll is the live equity (cash + open positions)
                "total_equity": round(snap.bankroll, 2),
                # total_pnl is net realised + unrealised PnL
                "total_pnl": round(snap.total_pnl or 0.0, 2),
                # closed_pnl approximated as total_pnl minus unrealised exposure
                "closed_pnl": round(
                    (snap.total_pnl or 0.0) - (snap.open_exposure or 0.0), 2
                ),
                "open_pnl": round(snap.open_exposure or 0.0, 2),
            }
            for snap in snapshots
        ],
    }


@router.get("/stats/role-breakdown")
def get_role_breakdown(
    days: int = 30,
    db: Session = Depends(get_db),
):
    """Role breakdown of trades: count, win_rate, avg_pnl by MAKER/TAKER/UNKNOWN.

    Query params:
        days: number of days to look back (default 30)
    """
    import os
    from backend.config import settings
    from backend.core.db_archiver import query_parquet_analytics

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    parquet_dir = os.path.join(settings.PARQUET_DIR, "trades")
    has_parquet = False
    if os.path.exists(parquet_dir):
        for root, dirs, files in os.walk(parquet_dir):
            if any(f.endswith(".parquet") for f in files):
                has_parquet = True
                break

    if has_parquet:
        try:
            sql = (
                "SELECT role, COUNT(*) AS count, "
                "SUM(CASE WHEN result = 'win' THEN 1.0 ELSE 0.0 END) AS wins, "
                "SUM(pnl) AS total_pnl "
                "FROM {table} "
                "WHERE timestamp >= '" + cutoff.isoformat() + "' "
                "GROUP BY role"
            )
            rows = query_parquet_analytics(parquet_dir, sql)
            
            result = {}
            for row in rows:
                role = str(row.get("role", "unknown")).lower()
                count = int(row.get("count", 0))
                wins = float(row.get("wins", 0.0) or 0.0)
                total_pnl = float(row.get("total_pnl", 0.0) or 0.0)
                
                result[role] = {
                    "count": count,
                    "win_rate": round(wins / count, 4) if count > 0 else 0,
                    "avg_pnl": round(total_pnl / count, 4) if count > 0 else 0,
                    "total_pnl": round(total_pnl, 4),
                }
            # Make sure all standard keys are initialized (maker, taker, unknown)
            for r in ["maker", "taker", "unknown"]:
                if r not in result:
                    result[r] = {
                        "count": 0,
                        "win_rate": 0,
                        "avg_pnl": 0,
                        "total_pnl": 0,
                    }
            return {"days": days, "roles": result}
        except Exception:
            # Fall back to sqlite if DuckDB query fails
            pass

    trades = (
        db.query(Trade)
        .filter(
            Trade.timestamp >= cutoff,
            Trade.role is not None,
        )
        .all()
    )

    # Group by role
    by_role: dict[str, list] = {"maker": [], "taker": [], "unknown": []}
    for t in trades:
        role = t.role or "unknown"
        if role not in by_role:
            by_role[role] = []
        by_role[role].append(t)

    result = {}
    for role_name, role_trades in by_role.items():
        if not role_trades:
            continue
        wins = sum(1 for t in role_trades if t.result == "win")
        total_pnl = sum((t.pnl or 0) for t in role_trades)
        result[role_name] = {
            "count": len(role_trades),
            "win_rate": round(wins / len(role_trades), 4) if role_trades else 0,
            "avg_pnl": round(total_pnl / len(role_trades), 4) if role_trades else 0,
            "total_pnl": round(total_pnl, 4),
        }

    return {"days": days, "roles": result}


@router.get("/calibration/buckets")
def get_calibration_buckets(
    strategy: str | None = None,
    days: int = 60,
    min_samples: int = 5,
):
    """Get price-bucket calibration statistics.

    Query params:
        strategy: optional strategy filter
        days: number of days to look back (default 60)
        min_samples: minimum samples per bucket (default 5)
    """

    results = get_bucket_calibration(
        strategy=strategy, days=days, min_samples=min_samples
    )
    return {"strategy": strategy, "days": days, "buckets": results}


@router.get("/bias/longshot")
def get_longshot_bias(
    category: str | None = None,
    days: int = 60,
):
    """Get longshot bias statistics.

    Query params:
        category: optional strategy/category filter
        days: number of days to look back (default 60)
    """
    from backend.core.longshot_bias import LongshotBiasDetector

    detector = LongshotBiasDetector()
    results = detector.compute_longshot_bias(category=category, days=days)
    return {"category": category, "days": days, "bias": results}


@router.get("/maker-taker")
def get_maker_taker_stats(
    db: Session = Depends(get_db),
):
    """Get full-history maker vs taker ROI stats with AGI recommendation.

    Returns:
        maker        – {count, pnl, size, roi} over all settled maker trades
        taker        – {count, pnl, size, roi} over all settled taker trades
        recommendation – 'prefer_maker' | 'reduce_taker' | 'neutral' | 'insufficient_data'
        cached_at    – ISO-8601 timestamp of last cache refresh (5-min TTL)
    """
    return maker_taker_analytics.get_stats(db)
