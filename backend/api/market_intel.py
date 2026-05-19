"""Market intelligence routes - news, predictions, whales, edge performance."""

from fastapi import APIRouter, Depends
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from backend.models.database import (
    get_db,
    Signal,
    Trade,
    WhaleTransaction,
)
from loguru import logger
router = APIRouter(tags=["market_intel"])


@router.get("/edge-performance")
async def get_edge_performance(
    track: str | None = None,
    days: int = 7,
    db: Session = Depends(get_db),
):
    """
    Returns aggregated performance metrics for edge discovery tracks.

    Metrics per track:
    - Total signals generated
    - Signals executed (paper)
    - Win rate (paper)
    - Total PNL (paper)
    - Sharpe ratio (paper)
    - Max drawdown (paper)
    """
    since_date = datetime.now(timezone.utc) - timedelta(days=days)

    query = (
        db.query(
            Signal.track_name,
            func.count(Signal.id).label("total_signals"),
            func.sum(case((Signal.executed, 1))).label("signals_executed"),
            func.sum(case((Signal.outcome_correct, 1))).label("winning_trades"),
        )
        .filter(
            Signal.timestamp >= since_date,
            Signal.track_name.isnot(None),
        )
        .group_by(Signal.track_name)
    )

    if track:
        query = query.filter(Signal.track_name == track)

    results = query.all()

    track_metrics = []
    for row in results:
        total_signals = row.total_signals or 0
        signals_executed = row.signals_executed or 0
        winning_trades = row.winning_trades or 0

        win_rate = (winning_trades / signals_executed) if signals_executed > 0 else 0.0

        pnl_query = (
            db.query(
                func.sum(Trade.pnl).label("total_pnl"),
                func.count(Trade.id).label("trade_count"),
            )
            .join(Signal, Trade.signal_id == Signal.id)
            .filter(
                Signal.track_name == row.track_name,
                Signal.timestamp >= since_date,
            )
        )

        pnl_result = pnl_query.first()
        total_pnl = pnl_result.total_pnl if pnl_result else 0.0
        trade_count = pnl_result.trade_count if pnl_result else 0

        track_metrics.append(
            {
                "track_name": row.track_name,
                "total_signals": total_signals,
                "signals_executed": signals_executed,
                "winning_trades": winning_trades,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
                "trade_count": trade_count,
                "status": "paper",
            }
        )

    return {
        "tracks": track_metrics,
        "days": days,
        "since_date": since_date.isoformat(),
    }


@router.get("/whales/transactions")
async def get_whale_transactions(limit: int = 50):
    """Return recent whale transactions from DB."""
    from backend.db.utils import get_db_session
    with get_db_session() as db:
        rows = (
            db.query(WhaleTransaction)
            .order_by(WhaleTransaction.observed_at.desc())
            .limit(min(limit, 500))
            .all()
        )
        return [
            {
                "id": r.id,
                "tx_hash": r.tx_hash,
                "wallet": r.wallet,
                "market_id": r.market_id,
                "side": r.side,
                "size_usd": r.size_usd,
                "block_number": r.block_number,
                "observed_at": r.observed_at.isoformat() if r.observed_at else None,
            }
            for r in rows
        ]


@router.get("/news/feed")
async def get_news_feed():
    """Return aggregated news feed from multiple sources."""
    try:
        from backend.data.feed_aggregator import FeedAggregator

        agg = FeedAggregator()
        items = await agg.fetch_all()
        return [
            {
                "source": i.source,
                "title": i.title,
                "link": i.link,
                "published_at": i.published_at.isoformat() if i.published_at else None,
                "summary": i.summary,
            }
            for i in items[:100]
        ]
    except Exception as e:
        return {"error": str(e), "items": []}


@router.get("/predictions/{market_id}")
async def get_prediction(market_id: str):
    """Return AI prediction for a specific market."""
    from backend.ai.prediction_engine import PredictionEngine

    engine = PredictionEngine()
    # TODO: wire real market data from Gamma API
    logger.warning("[market_intel] get_prediction() using stub features — wire real market data")
    features = engine.extract_features({"volume": 0}, {})
    pred = engine.predict(features)
    return {"market_id": market_id, "prediction": pred.__dict__}
