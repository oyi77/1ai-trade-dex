"""Calibration tracker — predicted vs. realized outcome feedback.

Tracks how well probability models predicted outcomes, adjusts future
confidence and probability estimates based on historical accuracy.
Uses the same 5-cent bucket approach as the existing risk_manager
calibration system for consistency.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from backend.core.edge.edge_types import clamp
from backend.models.database import Trade

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


BUCKET_SIZE = 0.05  # 5-cent probability buckets
MIN_SAMPLES_FOR_ADJUSTMENT = 20  # minimum trades before adjusting
MAX_ADJUSTMENT_PP = 5.0  # cap adjustment at 5 percentage points
CALIB_REFRESH_HOURS = 1.0  # refresh from DB every hour


@dataclass
class CalibrationBucket:
    """Tracks calibration for a probability bucket (e.g., 0.80-0.85)."""

    predicted_sum: float = 0.0
    realized_count: int = 0
    total_count: int = 0

    @property
    def average_predicted(self) -> float:
        return self.predicted_sum / self.total_count if self.total_count > 0 else 0.5

    @property
    def realized_rate(self) -> float:
        return self.realized_count / self.total_count if self.total_count > 0 else 0.5

    @property
    def adjustment(self) -> float:
        """How much to adjust predictions in this bucket (realized - predicted)."""
        if self.total_count < MIN_SAMPLES_FOR_ADJUSTMENT:
            return 0.0
        return (self.realized_rate - self.average_predicted) * 100  # in pp


def _bucket_key(probability: float) -> str:
    """Assign a probability to a 5-cent bucket."""
    bucket = int(probability / BUCKET_SIZE) * BUCKET_SIZE
    return f"{bucket:.2f}-{bucket + BUCKET_SIZE:.2f}"


class CalibrationTracker:
    """Tracks predicted vs. realized outcomes per category and price bucket.

    Reuses existing Trade table rows where model_probability is set.
    Refreshes from DB on a configurable cadence.

    Adjustment logic: if the model predicted 80% YES for a category but
    only 70% of those trades won, we add -10pp adjustment for that
    category/bucket. This is capped at ±5pp to prevent overcorrection.
    """

    def __init__(self):
        # category -> bucket_key -> CalibrationBucket
        self._by_category: dict[str, dict[str, CalibrationBucket]] = defaultdict(
            lambda: defaultdict(CalibrationBucket)
        )
        self._last_refresh: datetime = datetime.min.replace(tzinfo=timezone.utc)
        self._total_trades: int = 0

    async def refresh_from_db(self, db: Session) -> None:
        """Load calibration data from settled trades with model_probability."""
        now = datetime.now(timezone.utc)
        if (now - self._last_refresh).total_seconds() < CALIB_REFRESH_HOURS * 3600:
            return  # recently refreshed

        cutoff = now - timedelta(days=30)
        trades: list[Trade] = (
            db.query(Trade)
            .filter(
                Trade.settled == True,  # noqa: E712
                Trade.timestamp > cutoff,
                Trade.model_probability.isnot(None),
            )
            .all()
        )

        self._by_category.clear()
        self._total_trades = 0

        for t in trades:
            if t.model_probability is None:
                continue
            bucket = _bucket_key(t.model_probability)
            cat = t.strategy or "unknown"  # Trade model has no `category` column; group by strategy instead
            b = self._by_category[cat][bucket]
            b.predicted_sum += t.model_probability
            b.realized_count += 1 if t.result == "win" else 0
            b.total_count += 1
            self._total_trades += 1

        self._last_refresh = now

    def get_adjustment(self, category: str, predicted_prob: float) -> float:
        """Returns adjustment in pp to add to predicted probability.

        Positive = model underestimates (realized > predicted).
        Negative = model overestimates (realized < predicted).
        """
        bucket = _bucket_key(predicted_prob)
        b = self._by_category.get(category, {}).get(bucket)
        if b is None or b.total_count < MIN_SAMPLES_FOR_ADJUSTMENT:
            return 0.0
        return clamp(b.adjustment, -MAX_ADJUSTMENT_PP, MAX_ADJUSTMENT_PP)

    def get_reliability(self, category: str) -> float:
        """Returns confidence multiplier for a category based on sample size."""
        buckets = self._by_category.get(category, {})
        total = sum(b.total_count for b in buckets.values())
        if total < 50:
            return 0.5
        elif total < 200:
            return 0.75
        return 1.0

    def record_observation(
        self, category: str, predicted_prob: float, realized: bool
    ) -> None:
        """Record a single observation for real-time calibration updates."""
        bucket = _bucket_key(predicted_prob)
        b = self._by_category[category][bucket]
        b.predicted_sum += predicted_prob
        b.realized_count += 1 if realized else 0
        b.total_count += 1
        self._total_trades += 1

    @property
    def total_trades(self) -> int:
        return self._total_trades

    @property
    def last_refresh(self) -> datetime:
        return self._last_refresh