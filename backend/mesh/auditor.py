"""Source Performance Auditor — tracks PnL per source, adjusts weights."""
from __future__ import annotations
import logging
from typing import Dict, List
from sqlalchemy.sql import func

from backend.models.database import SessionLocal, Trade

logger = logging.getLogger("trading_bot.mesh.auditor")


def audit_source_performance(min_trades: int = 20) -> Dict[str, dict]:
    """Query trades grouped by source_id, return per-source PnL and win_rate.

    Sources with avg_pnl < 0 and count > min_trades get weight reduced 50%.
    Sources with avg_pnl > 0 and win_rate > 60% get weight increased.
    """
    db = SessionLocal()
    try:
        rows = db.query(
            Trade.settlement_source,
            func.count(Trade.id).label("cnt"),
            func.avg(Trade.pnl).label("avg_pnl"),
            func.sum(Trade.pnl).label("total_pnl"),
            func.count(Trade.id).filter(Trade.result == "win").label("wins"),
        ).filter(
            Trade.settled == True,
            Trade.settlement_source.isnot(None),
        ).group_by(Trade.settlement_source).having(
            func.count(Trade.id) >= min_trades
        ).all()

        results = {}
        for row in rows:
            source = row.settlement_source or "unknown"
            cnt = row.cnt
            avg_pnl = float(row.avg_pnl or 0)
            total_pnl = float(row.total_pnl or 0)
            wins = row.wins or 0
            win_rate = wins / cnt if cnt > 0 else 0.0
            weight = 1.0
            if avg_pnl < 0 and cnt >= min_trades:
                weight = 0.5
            elif avg_pnl > 0 and win_rate > 0.60:
                weight = 1.25
            results[source] = {
                "trades": cnt, "avg_pnl": round(avg_pnl, 4),
                "total_pnl": round(total_pnl, 2), "win_rate": round(win_rate, 4),
                "weight": weight,
            }

        if results:
            logger.info(f"Source auditor: evaluated {len(results)} sources with >= {min_trades} trades")
        return results
    except Exception as e:
        logger.warning(f"Source auditor failed: {e}")
        return {}
    finally:
        db.close()


def detect_coverage_gaps(required_tags: List[str] = None, min_sources: int = 2) -> List[str]:
    """Find market tags with insufficient active DataSource coverage."""
    from backend.mesh.registry import list_active
    if required_tags is None:
        required_tags = ["crypto", "weather", "politics", "sports", "finance", "commodities"]
    active = list_active()
    covered = set()
    for sid in active:
        covered.add(sid)
    gaps = []
    tag_source_map = {
        "crypto": ["polymarket_book", "binance_book"],
        "weather": ["polymarket_book", "open_meteo"],
        "politics": ["polymarket_book"],
        "sports": ["polymarket_book"],
        "finance": ["polymarket_book", "reuters_rss"],
        "commodities": ["polymarket_book"],
    }
    for tag in required_tags:
        needed = tag_source_map.get(tag, ["polymarket_book"])
        active_for_tag = [s for s in needed if s in covered]
        if len(active_for_tag) < min_sources:
            gaps.append(tag)
    return gaps
