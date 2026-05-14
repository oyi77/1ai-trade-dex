"""SignalLogRepository - query, aggregation & latency profiling (for edge calibration)

All aggregations use SQLAlchemy Core, tuned for index coverage.
Profiles query/aggregation time using time.monotonic.

Query patterns:
- per-strategy calibration (price-bucket): aggregate hit rate & avg pnl by market_mid bucket
- time series for decay/chronological (market_id, timestamp)
- open/filled signals with/without pnl
"""
import time
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.signal_log import SignalLog

class QueryTimer:
    @staticmethod
    def timed(query_fn, *args, **kwargs):
        t0 = time.monotonic()
        result = query_fn(*args, **kwargs)
        elapsed = time.monotonic() - t0
        return result, elapsed

class SignalLogRepository:
    def __init__(self, db: Optional[Session] = None):
        self.db = db
        self._owns_db = False

    def _get_db(self) -> Session:
        if self.db is None:
            from backend.models.database import SessionLocal
            self.db = SessionLocal()
            self._owns_db = True
        return self.db

    def close(self):
        if self._owns_db and self.db:
            self.db.close()
            self._owns_db = False
            self.db = None

    def calibration_bucket_aggregates(self, strategy: str, mid_lo: float, mid_hi: float):
        db = self._get_db()
        def query():
            return (
                db.query(
                    func.count(SignalLog.id).label("signals"),
                    func.avg(SignalLog.edge_pp).label("avg_edge_pp"),
                    func.avg(SignalLog.pnl).label("avg_pnl"),
                    func.avg(SignalLog.filled.cast(func.int_)).label("fill_rate"),
                )
                .filter(SignalLog.strategy == strategy)
                .filter(SignalLog.market_mid >= mid_lo)
                .filter(SignalLog.market_mid < mid_hi)
            ).first()
        return QueryTimer.timed(query)

    def market_time_series(self, market_id: str, limit: int = 1000):
        db = self._get_db()
        def query():
            return (
                db.query(SignalLog)
                .filter(SignalLog.market_id == market_id)
                .order_by(SignalLog.timestamp.desc())
                .limit(limit)
                .all()
            )
        return QueryTimer.timed(query)

    def open_signals_needing_settlement(self):
        db = self._get_db()
        def query():
            return (
                db.query(SignalLog)
                .filter(SignalLog.filled.is_(True), SignalLog.pnl.is_(None))
                .all()
            )
        return QueryTimer.timed(query)
