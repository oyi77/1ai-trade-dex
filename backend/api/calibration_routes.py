"""Calibration breakdown endpoint.

Exposes per-bucket calibration statistics derived from settled `Trade`
rows. Buckets are 10 percentage-point bands on `entry_price` (treated as
implied probability in [0, 1]).

For each bucket we compute:
  - win_rate: fraction of settled trades with settlement_value == 1.0
  - implied: average market_price_at_entry (fallback to entry_price)
  - edge_pp: (win_rate - implied) * 100, expressed in percentage points
  - brier:   mean squared error between settlement_value and implied
  - n:       sample count

Buckets with fewer than `MIN_BUCKET_SAMPLES` settled trades return null
for the statistics — we never fabricate calibration on thin data.
"""

from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.models.database import Trade, get_db

router = APIRouter(prefix="/api/v1", tags=["calibration"])

# Bucket edges in implied-probability space (entry_price ∈ [0, 1]).
_BUCKET_EDGES = [
    (0.0, 0.1, "0-10"),
    (0.1, 0.2, "10-20"),
    (0.2, 0.3, "20-30"),
    (0.3, 0.4, "30-40"),
    (0.4, 0.5, "40-50"),
    (0.5, 0.6, "50-60"),
    (0.6, 0.7, "60-70"),
    (0.7, 0.8, "70-80"),
    (0.8, 0.9, "80-90"),
    (0.9, 1.0 + 1e-9, "90-100"),  # include 1.0 in last bucket
]

MIN_BUCKET_SAMPLES = 10


class BucketData(BaseModel):
    brier: Optional[float] = None
    win_rate: Optional[float] = None
    implied: Optional[float] = None
    edge_pp: Optional[float] = None
    n: int = 0
    negative_edge: Optional[bool] = False


class CalibrationResponse(BaseModel):
    overall_brier: Optional[float] = None
    buckets: Dict[str, Optional[BucketData]]


def _bucket_for_price(price: float) -> Optional[str]:
    for lo, hi, name in _BUCKET_EDGES:
        if lo <= price < hi:
            return name
    return None


@router.get("/calibration", response_model=CalibrationResponse)
def get_calibration(db: Session = Depends(get_db)) -> CalibrationResponse:
    """Return per-bucket calibration breakdown from settled Trade rows."""

    # Pull only the columns we need; settled trades with a known outcome.
    rows = (
        db.query(
            Trade.entry_price,
            Trade.market_price_at_entry,
            Trade.settlement_value,
        )
        .filter(Trade.settled.is_(True))
        .filter(Trade.settlement_value.isnot(None))
        .filter(Trade.entry_price.isnot(None))
        .all()
    )

    # Init every bucket so the response shape is stable even on empty DB.
    bucket_stats: Dict[str, Dict[str, float]] = {
        name: {"n": 0, "wins": 0.0, "implied_sum": 0.0, "brier_sum": 0.0}
        for _, _, name in _BUCKET_EDGES
    }

    overall_n = 0
    overall_brier_sum = 0.0

    for entry_price, market_price_at_entry, settlement_value in rows:
        if entry_price is None or settlement_value is None:
            continue
        try:
            price = float(entry_price)
            outcome = float(settlement_value)
        except (TypeError, ValueError):
            continue

        bucket = _bucket_for_price(price)
        if bucket is None:
            continue

        implied = (
            float(market_price_at_entry)
            if market_price_at_entry is not None
            else price
        )

        stats = bucket_stats[bucket]
        stats["n"] += 1
        if outcome >= 0.5:
            stats["wins"] += 1.0
        stats["implied_sum"] += implied
        stats["brier_sum"] += (outcome - implied) ** 2

        overall_n += 1
        overall_brier_sum += (outcome - implied) ** 2

    buckets_out: Dict[str, Optional[BucketData]] = {}
    for _, _, name in _BUCKET_EDGES:
        stats = bucket_stats[name]
        n = int(stats["n"])
        if n < MIN_BUCKET_SAMPLES:
            buckets_out[name] = None
            continue

        win_rate = stats["wins"] / n
        implied = stats["implied_sum"] / n
        brier = stats["brier_sum"] / n
        edge_pp = (win_rate - implied) * 100.0

        buckets_out[name] = BucketData(
            brier=brier,
            win_rate=win_rate,
            implied=implied,
            edge_pp=edge_pp,
            n=n,
            negative_edge=edge_pp < 0,
        )

    overall_brier = (overall_brier_sum / overall_n) if overall_n > 0 else None

    return CalibrationResponse(overall_brier=overall_brier, buckets=buckets_out)
