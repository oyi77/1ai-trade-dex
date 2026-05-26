"""Longshot bias detection — identifies systematic over/under-pricing of longshot outcomes."""

from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.models.database import SessionLocal, CalibrationRecord

# Constants
LONGSHOT_THRESHOLD = 0.05  # Prices below this are considered longshots
MIN_SAMPLES = 10  # Minimum calibration samples required per bucket
PRICE_CUTOFF = 0.30  # Only analyze predictions below this probability


class LongshotBiasDetector:
    """Detect systematic over/under-pricing of longshot outcomes.

    Longshots (predictions below LONGSHOT_THRESHOLD) are often mispriced
    in prediction markets. This detector identifies which categories or
    strategies consistently misprice longshots.
    """

    def compute_longshot_bias(
        self,
        category: Optional[str] = None,
        days: int = 60,
    ) -> list[dict]:
        """Compute longshot bias for all categories (or one category).

        Args:
            category: Optional category name to filter by. If None, returns all.
            days: Number of days to look back.

        Returns:
            List of dicts sorted by edge descending. Each dict has:
            - category (or 'all')
            - count (number of longshot predictions)
            - avg_predicted (average predicted probability)
            - avg_actual (average actual win rate)
            - bias (avg_actual - avg_predicted)
            - edge (positive = longshots underpriced, negative = overpriced)
        """
        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

            query = db.query(CalibrationRecord).filter(
                CalibrationRecord.timestamp >= cutoff,
                CalibrationRecord.actual_outcome is not None,
                CalibrationRecord.predicted_prob < PRICE_CUTOFF,
            )

            if category:
                query = query.filter(CalibrationRecord.strategy == category)

            records = query.all()

            if len(records) < MIN_SAMPLES:
                return []

            # Compute overall stats for longshots
            avg_predicted = sum(r.predicted_prob for r in records) / len(records)
            wins = sum(1 for r in records if r.actual_outcome == "win")
            avg_actual = wins / len(records) if records else 0.0
            bias = avg_actual - avg_predicted

            result = {
                "category": category or "all",
                "count": len(records),
                "avg_predicted": round(avg_predicted, 4),
                "avg_actual": round(avg_actual, 4),
                "bias": round(bias, 4),
                "edge": round(
                    bias, 4
                ),  # positive = longshots underpriced (good to bet)
            }

            return [result]

    def get_category_bias(self, days: int = 60) -> dict[str, float]:
        """Get average longshot bias per strategy/category.

        Args:
            days: Number of days to look back.

        Returns:
            Dict mapping strategy name to average bias (avg_actual - avg_predicted).
            Only includes strategies with MIN_SAMPLES+ longshot predictions.
        """
        db = SessionLocal()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

            records = (
                db.query(CalibrationRecord)
                .filter(
                    CalibrationRecord.timestamp >= cutoff,
                    CalibrationRecord.actual_outcome is not None,
                    CalibrationRecord.predicted_prob < PRICE_CUTOFF,
                )
                .all()
            )

            # Group by strategy
            by_strategy: dict[str, list] = {}
            for rec in records:
                if rec.strategy not in by_strategy:
                    by_strategy[rec.strategy] = []
                by_strategy[rec.strategy].append(rec)

            result = {}
            for strategy, recs in by_strategy.items():
                if len(recs) < MIN_SAMPLES:
                    continue
                avg_pred = sum(r.predicted_prob for r in recs) / len(recs)
                wins = sum(1 for r in recs if r.actual_outcome == "win")
                avg_actual = wins / len(recs)
                result[strategy] = round(avg_actual - avg_pred, 4)

            return result

        finally:
            db.close()

    def compute_longshot_bias_from_trades(
        self,
        db,
        price_threshold: float = 0.30,
        window_days: int = 60,
        strategy_name: Optional[str] = None,
    ) -> Optional[dict]:
        """Compute longshot bias ratio from actual settled trades.

        Formula:
          bias = longshot_win_rate / longshot_expected_win_rate
          where longshot_expected_win_rate is the average entry price of longshots.
          bias < 1.0 -> longshots are overpriced.
        """
        from backend.models.database import Trade
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

        query = db.query(Trade).filter(
            Trade.settled.is_(True),
            Trade.timestamp >= cutoff,
            Trade.entry_price.isnot(None),
            Trade.entry_price < price_threshold,
            Trade.result.isnot(None),
        )
        if strategy_name:
            query = query.filter(Trade.strategy == strategy_name)

        trades = query.all()
        if not trades:
            return None

        longshot_win_rate = sum(1.0 for t in trades if t.result.lower() == "win") / len(trades)
        longshot_expected = sum(t.entry_price for t in trades) / len(trades)

        bias = longshot_win_rate / longshot_expected if longshot_expected > 0 else 1.0

        return {
            "bias": round(bias, 4),
            "strength": round(1.0 - bias, 4),
            "sample_size": len(trades),
            "expected_win_rate": round(longshot_expected, 4),
            "actual_win_rate": round(longshot_win_rate, 4),
        }

