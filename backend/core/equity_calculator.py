"""Equity curve calculation from AppState snapshots."""

from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy.orm import Session

from backend.models.app_state import AppState
from backend.models.database import Trade, BotState


class EquityPoint:
    __slots__ = ("timestamp", "total_equity", "total_pnl", "closed_pnl", "open_pnl")

    def __init__(self, timestamp: datetime, total_equity: float, total_pnl: float, closed_pnl: float, open_pnl: float):
        self.timestamp = timestamp
        self.total_equity = total_equity
        self.total_pnl = total_pnl
        self.closed_pnl = closed_pnl
        self.open_pnl = open_pnl


def get_historical_equity(db: Session, limit: int = 90) -> List[EquityPoint]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=limit)
    states = (
        db.query(AppState)
        .filter(AppState.timestamp >= cutoff)
        .order_by(AppState.timestamp.asc())
        .all()
    )
    return [
        EquityPoint(
            timestamp=s.timestamp,
            total_equity=s.total_equity,
            total_pnl=s.total_pnl,
            closed_pnl=s.closed_pnl,
            open_pnl=s.open_pnl,
        )
        for s in states
    ]
