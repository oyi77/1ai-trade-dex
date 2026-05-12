"""Source-weight updater — adjusts weights from provenance-attributed trade outcomes."""
from __future__ import annotations
from typing import Dict

from backend.models.database import SessionLocal, Trade
from sqlalchemy.sql import func

from loguru import logger

_source_weights: Dict[str, float] = {}


def update_source_weights_from_outcomes() -> Dict[str, float]:
    """Query recent settled trades, compute per-source win rate, update weights.

    Sources with no data start at 1.0. Weight decays proportionally to loss rate.
    Return updated weights dict.
    """
    global _source_weights
    db = SessionLocal()
    try:
        rows = db.query(
            Trade.settlement_source,
            func.count(Trade.id).label("cnt"),
            func.count(Trade.id).filter(Trade.result == "win").label("wins"),
        ).filter(
            Trade.settled,
            Trade.settlement_source.isnot(None),
            Trade.settlement_source != "",
        ).group_by(Trade.settlement_source).all()

        for row in rows:
            source = row.settlement_source or "unknown"
            cnt = row.cnt or 0
            wins = row.wins or 0
            win_rate = wins / cnt if cnt > 0 else 0.5
            _source_weights[source] = max(0.1, min(2.0, win_rate * 1.5))

        for row in rows:
            source = row.settlement_source
            if source:
                logger.debug(
                    f"source_weight: {source} → {_source_weights.get(source, 1.0):.3f} "
                    f"({row.wins}/{row.cnt} wins)"
                )
        return dict(_source_weights)
    except Exception as e:
        logger.warning(f"Source weight updater failed: {e}")
        return {}
    finally:
        db.close()


def get_source_weight(source_id: str) -> float:
    return _source_weights.get(source_id, 1.0)


def get_all_weights() -> Dict[str, float]:
    return dict(_source_weights)
