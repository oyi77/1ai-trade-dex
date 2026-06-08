from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from loguru import logger
from sqlalchemy.orm import Session

from backend.models.database import Trade


def reconcile_bundle_pnl(trades: List[Trade]) -> Dict[str, Any]:
    settled = sum(1 for t in trades if t.settled and t.pnl is not None)
    total_pnl = sum(float(t.pnl or 0.0) for t in trades if t.settled and t.pnl is not None)
    complete = len(trades) >= 2 and {t.direction for t in trades} >= {"YES", "NO"} and settled == len(trades)

    bundle_id = next((t.arb_bundle_id for t in trades if t.arb_bundle_id), "unknown")

    return {
        "bundle_id": bundle_id or "unknown",
        "total_legs": len(trades),
        "settled_legs": settled,
        "is_complete": complete,
        "bundle_pnl": round(total_pnl, 6),
    }


def detect_incomplete_bundles(trades: List[Trade]) -> List[Dict[str, Any]]:
    if not trades:
        return []

    grouped: Dict[str, List[Trade]] = defaultdict(list)
    for t in trades:
        if t.arb_bundle_id:
            grouped[t.arb_bundle_id].append(t)

    incomplete: List[Dict[str, Any]] = []
    for bundle_id, legs in grouped.items():
        expected = max(int(t.arb_leg_count or 2) for t in legs)
        found = len(legs)
        if found < expected:
            incomplete.append({
                "bundle_id": bundle_id,
                "legs_found": found,
                "legs_expected": expected,
            })

    return incomplete


def count_open_incomplete_bundles(db: Session, mode: str = "live") -> int:
    trades = (
        db.query(Trade)
        .filter(
            Trade.trading_mode == mode,
            Trade.arb_bundle_id.isnot(None),
            Trade.settled.is_(False),
        )
        .order_by(Trade.arb_bundle_id, Trade.arb_leg_index)
        .all()
    )

    grouped: Dict[str, List[Trade]] = defaultdict(list)
    for t in trades:
        grouped[t.arb_bundle_id].append(t)

    incomplete = 0
    for legs in grouped.values():
        expected = max(int(t.arb_leg_count or 2) for t in legs)
        if len(legs) < expected:
            incomplete += 1

    if incomplete > 0:
        logger.warning(
            "[bundle_reconciliation] {} open incomplete arb bundles detected in {} mode",
            incomplete,
            mode,
        )

    return incomplete
