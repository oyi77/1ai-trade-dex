"""Calibration tracker — validates that model predicted probabilities match actual outcomes."""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("trading_bot.calibration")


def get_price_bucket(probability: float, num_bins: int = 10) -> int:
    """Return bucket index (0-indexed) for a probability value."""
    return min(int(probability * num_bins), num_bins - 1)


class CalibrationTracker:
    """Track and analyze prediction calibration across strategies."""

    def record_prediction(
        self,
        db: Session,
        strategy: str,
        market_ticker: str,
        predicted_prob: float,
        direction: str,
    ) -> None:
        """Record a prediction for later calibration analysis."""
        from backend.models.database import CalibrationRecord

        record = CalibrationRecord(
            strategy=strategy,
            market_ticker=market_ticker,
            predicted_prob=predicted_prob,
            price_bucket=get_price_bucket(predicted_prob),
            direction=direction,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(record)
        try:
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to record calibration prediction: {e}")
            db.rollback()

    def record_outcome(
        self,
        db: Session,
        market_ticker: str,
        settlement_value: float,
    ) -> int:
        """Update all pending predictions for a market with the actual outcome.
        Returns count of records updated."""
        from backend.models.database import CalibrationRecord

        pending = (
            db.query(CalibrationRecord)
            .filter(
                CalibrationRecord.market_ticker == market_ticker,
                CalibrationRecord.actual_outcome == None,
            )
            .all()
        )

        updated = 0
        for record in pending:
            # Determine if the prediction was correct
            if record.direction in ("yes", "up"):
                record.actual_outcome = "win" if settlement_value == 1.0 else "loss"
            else:
                record.actual_outcome = "win" if settlement_value == 0.0 else "loss"
            record.settlement_value = settlement_value
            updated += 1

        if updated:
            try:
                db.commit()
            except Exception as e:
                logger.warning(f"Failed to record calibration outcomes: {e}")
                db.rollback()
                return 0

        return updated

    def get_calibration_curve(
        self,
        db: Session,
        strategy: Optional[str] = None,
        num_bins: int = 10,
    ) -> list[dict]:
        """Compute calibration curve: binned predicted probability vs actual win rate.

        Returns list of {bin_low, bin_high, predicted_avg, actual_win_rate, count}.
        """
        from backend.models.database import CalibrationRecord

        query = db.query(CalibrationRecord).filter(
            CalibrationRecord.actual_outcome != None,
        )
        if strategy:
            query = query.filter(CalibrationRecord.strategy == strategy)

        records = query.all()
        if not records:
            return []

        bin_width = 1.0 / num_bins
        bins = []

        for i in range(num_bins):
            bin_low = i * bin_width
            bin_high = (i + 1) * bin_width

            in_bin = [
                r for r in records
                if bin_low <= r.predicted_prob < bin_high
                or (i == num_bins - 1 and r.predicted_prob == 1.0)
            ]

            if not in_bin:
                continue

            predicted_avg = sum(r.predicted_prob for r in in_bin) / len(in_bin)
            wins = sum(1 for r in in_bin if r.actual_outcome == "win")
            actual_win_rate = wins / len(in_bin)

            bins.append({
                "bin_low": round(bin_low, 2),
                "bin_high": round(bin_high, 2),
                "predicted_avg": round(predicted_avg, 4),
                "actual_win_rate": round(actual_win_rate, 4),
                "count": len(in_bin),
            })

        return bins

    def get_brier_score(
        self,
        db: Session,
        strategy: Optional[str] = None,
    ) -> Optional[float]:
        """Compute Brier score (lower is better, 0 = perfect calibration).

        Brier = mean((predicted_prob - actual_outcome)^2)
        where actual_outcome is 1.0 for win, 0.0 for loss.
        """
        from backend.models.database import CalibrationRecord

        query = db.query(CalibrationRecord).filter(
            CalibrationRecord.actual_outcome != None,
        )
        if strategy:
            query = query.filter(CalibrationRecord.strategy == strategy)

        records = query.all()
        if not records:
            return None

        squared_errors = []
        for r in records:
            actual = 1.0 if r.actual_outcome == "win" else 0.0
            squared_errors.append((r.predicted_prob - actual) ** 2)

        return round(sum(squared_errors) / len(squared_errors), 6)

    def get_strategy_summary(
        self,
        db: Session,
        strategy: Optional[str] = None,
    ) -> dict:
        """Get summary calibration stats for a strategy."""
        from backend.models.database import CalibrationRecord

        query = db.query(CalibrationRecord).filter(
            CalibrationRecord.actual_outcome != None,
        )
        if strategy:
            query = query.filter(CalibrationRecord.strategy == strategy)

        records = query.all()
        if not records:
            return {"total": 0, "brier_score": None, "bins": []}

        brier = self.get_brier_score(db, strategy)
        bins = self.get_calibration_curve(db, strategy)
        wins = sum(1 for r in records if r.actual_outcome == "win")

        return {
            "total": len(records),
            "wins": wins,
            "win_rate": round(wins / len(records), 4) if records else 0,
            "brier_score": brier,
            "bins": bins,
        }


# Module-level singleton
calibration_tracker = CalibrationTracker()


def compute_price_bucket_calibration(
    db: Session,
    bucket_width: int = 5,
    window_days: int = 30,
) -> dict:
    """Compute realized win rate by price bucket from settled trades.

    Returns dict: {bucket_start: {predicted, actual, error, trades, confidence}}
    """
    from backend.models.database import Trade
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    trades = db.query(Trade).filter(
        Trade.settled == True,
        Trade.timestamp >= cutoff,
    ).all()

    buckets: dict = {}
    for bucket_start in range(0, 100, bucket_width):
        bucket_trades = [
            t for t in trades
            if bucket_start <= (getattr(t, "entry_price", 0.5) or 0.5) * 100 < bucket_start + bucket_width
        ]
        if not bucket_trades:
            continue

        wins = sum(1 for t in bucket_trades if getattr(t, "result", None) == "win")
        win_rate = wins / len(bucket_trades)
        predicted = (bucket_start + bucket_width / 2) / 100
        error = win_rate - predicted

        buckets[bucket_start] = {
            "predicted": predicted,
            "actual": win_rate,
            "error": error,
            "trades": len(bucket_trades),
            "confidence": min(len(bucket_trades) / 50, 1.0),
        }

    return buckets


def compute_calibration_adjustment(
    bucket_calibration: dict,
    entry_price: float,
) -> float:
    """Return adjustment to predicted probability based on calibration error.

    Capped at ±5% to prevent over-correction.
    Returns 0.0 if insufficient data for the bucket.
    """
    bucket_start = int(entry_price * 100) - (int(entry_price * 100) % 5)
    if bucket_start not in bucket_calibration:
        return 0.0

    bucket = bucket_calibration[bucket_start]
    if bucket["confidence"] < 0.3:
        return 0.0

    adjustment = bucket["error"] * bucket["confidence"] * -1
    return max(-0.05, min(0.05, adjustment))


def get_bucket_calibration(
    strategy: Optional[str] = None,
    days: int = 60,
    min_samples: int = 5,
) -> list[dict]:
    """Standalone helper: per-bucket calibration stats with time-range and sample filters.

    Opens its own DB session and delegates to CalibrationTracker.get_calibration_curve(),
    filtering to the last *days* days and excluding buckets with fewer than *min_samples*
    resolved predictions.

    Returns a list of bucket dicts: {bin_low, bin_high, predicted_avg, actual_win_rate, count}.
    """
    from datetime import timedelta
    from backend.db.utils import get_db_session
    from backend.models.database import CalibrationRecord

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        with get_db_session() as db:
            query = db.query(CalibrationRecord).filter(
                CalibrationRecord.actual_outcome.is_not(None),
                CalibrationRecord.timestamp >= cutoff,
            )
            if strategy:
                query = query.filter(CalibrationRecord.strategy == strategy)

            records = query.all()
            if not records:
                return []

            # Bin into 10 probability buckets [0.0, 0.1), ..., [0.9, 1.0]
            num_bins = 10
            bin_width = 1.0 / num_bins
            result = []

            for i in range(num_bins):
                bin_low = i * bin_width
                bin_high = (i + 1) * bin_width

                in_bin = [
                    r for r in records
                    if bin_low <= r.predicted_prob < bin_high
                    or (i == num_bins - 1 and r.predicted_prob == 1.0)
                ]

                if len(in_bin) < min_samples:
                    continue

                predicted_avg = sum(r.predicted_prob for r in in_bin) / len(in_bin)
                wins = sum(1 for r in in_bin if r.actual_outcome == "win")
                actual_win_rate = wins / len(in_bin)

                result.append({
                    "bin_low": round(bin_low, 2),
                    "bin_high": round(bin_high, 2),
                    "predicted_avg": round(predicted_avg, 4),
                    "actual_win_rate": round(actual_win_rate, 4),
                    "count": len(in_bin),
                })

            return result
    except Exception as exc:
        logger.warning("get_bucket_calibration failed: %s", exc)
        return []
