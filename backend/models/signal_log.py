"""SignalLog: alpha source instrumentation table for btc_oracle and other strategies.

Design notes (performance-focused):
- Composite indexes are tuned to the dominant query patterns:
  1. Calibration buckets: WHERE strategy=? AND market_mid BETWEEN ? AND ?
  2. Per-market time-series: WHERE market_id=? ORDER BY timestamp DESC
  3. Recent-strategy scans:  WHERE strategy=? ORDER BY timestamp DESC
  4. Settlement updates:     WHERE filled IS TRUE AND pnl IS NULL
- Indexes are intentionally narrow (single + composite) — adding more without
  measured query volume only slows inserts and bloats storage.
- All numeric edge / probability fields are Float (double precision in PG) so
  aggregations (AVG, SUM, percentile_cont) can run server-side without casting.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
)

from backend.models.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SignalLog(Base):
    """Per-signal instrumentation row.

    One row is written per signal produced (filled or not). Used for:
    - Edge-vs-realized-pnl calibration (price-bucket breakdown)
    - Alpha decay analysis over time
    - Strategy-level hit-rate aggregation

    Query patterns are documented above; do not add indexes without first
    profiling with EXPLAIN ANALYZE and confirming the column is highly
    selective on production data.
    """

    __tablename__ = "signal_log"

    id = Column(Integer, primary_key=True)

    # Per-row indexed timestamp powers `ORDER BY timestamp DESC` over the whole
    # table. The composite indexes below cover the common filtered variants.
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        index=True,
    )

    market_id = Column(String, nullable=False)
    market_mid = Column(Float, nullable=False)
    btc_spot = Column(Float, nullable=True)

    # Signal features (used for calibration breakdown)
    rsi = Column(Float, nullable=True)
    momentum_5m = Column(Float, nullable=True)
    vwap_deviation = Column(Float, nullable=True)
    sma_crossover = Column(Float, nullable=True)

    # Decision + outcome
    proposed_side = Column(String, nullable=True)  # "up" | "down" | None
    edge_pp = Column(Float, nullable=True)
    oracle_implied = Column(Float, nullable=True)
    filled = Column(Boolean, nullable=True)
    pnl = Column(Float, nullable=True)

    strategy = Column(
        String,
        nullable=False,
        default="btc_oracle",
    )

    __table_args__ = (
        # 1. Calibration / capacity analysis: per-strategy filter + range scan
        #    on market_mid (e.g. WHERE strategy='btc_oracle' AND market_mid BETWEEN 0.45 AND 0.55).
        Index(
            "ix_signal_log_strategy_market_mid",
            "strategy",
            "market_mid",
        ),
        # 2. Per-market time series: dashboard chart + alpha decay queries.
        Index(
            "ix_signal_log_market_id_timestamp",
            "market_id",
            "timestamp",
        ),
        # 3. Recent strategy activity: WHERE strategy=? ORDER BY timestamp DESC LIMIT N.
        Index(
            "ix_signal_log_strategy_timestamp",
            "strategy",
            "timestamp",
        ),
        # 4. Settlement worker: pulls filled signals still missing pnl.
        Index(
            "ix_signal_log_filled_pnl",
            "filled",
            "pnl",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"<SignalLog id={self.id} strategy={self.strategy} "
            f"market_id={self.market_id} edge_pp={self.edge_pp} pnl={self.pnl}>"
        )
