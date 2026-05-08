"""AppState model — periodic app-wide state snapshots for equity curve."""

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, Float, String, DateTime

from backend.models.database import Base


class AppState(Base):
    """Periodic snapshot of app-wide state: equity, bankroll, P&L."""

    __tablename__ = "app_states"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    total_equity = Column(Float, nullable=False, default=0.0)
    total_pnl = Column(Float, nullable=False, default=0.0)
    closed_pnl = Column(Float, nullable=False, default=0.0)
    open_pnl = Column(Float, nullable=False, default=0.0)
    bankroll = Column(Float, nullable=False, default=0.0)
    mode = Column(String, nullable=False, default="paper")
