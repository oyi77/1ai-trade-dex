"""Strategy Performance Decay Detector.

Monitors rolling win rate over time to detect statistical degradation.
Uses CUSUM (Cumulative Sum) control chart for early decay detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from loguru import logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class DecayReport:
    """Report on performance decay for a strategy."""
    strategy: str
    is_decaying: bool = False
    decay_severity: str = "none"  # none, mild, moderate, severe
    current_wr: float = 0.0
    baseline_wr: float = 0.0
    wr_delta: float = 0.0
    cusum_score: float = 0.0
    rolling_wr_trend: float = 0.0  # slope of win rate over time
    trades_analyzed: int = 0
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "is_decaying": self.is_decaying,
            "decay_severity": self.decay_severity,
            "current_wr": round(self.current_wr, 4),
            "baseline_wr": round(self.baseline_wr, 4),
            "wr_delta": round(self.wr_delta, 4),
            "cusum_score": round(self.cusum_score, 4),
            "rolling_wr_trend": round(self.rolling_wr_trend, 6),
            "trades_analyzed": self.trades_analyzed,
            "recommendation": self.recommendation,
        }


class PerformanceDecayDetector:
    """Detects strategy performance degradation using statistical methods.

    Uses:
    - Rolling win rate comparison (recent vs historical)
    - CUSUM control chart for shift detection
    - Linear regression slope of win rate over time
    """

    def __init__(
        self,
        min_trades: int = 30,
        window_size: int = 20,
        cusum_threshold: float = 2.0,
        mild_decay_delta: float = -0.05,
        moderate_decay_delta: float = -0.10,
        severe_decay_delta: float = -0.20,
    ):
        self.min_trades = min_trades
        self.window_size = window_size
        self.cusum_threshold = cusum_threshold
        self.mild_decay_delta = mild_decay_delta
        self.moderate_decay_delta = moderate_decay_delta
        self.severe_decay_delta = severe_decay_delta

    def detect(
        self,
        strategy: str,
        db: Optional[Session] = None,
        lookback_days: int = 90,
        trading_mode: str = "live",
    ) -> DecayReport:
        """Detect performance decay for a strategy.

        Args:
            strategy: Strategy name.
            db: Database session.
            lookback_days: How far back to analyze.
            trading_mode: Filter by mode ("live", "paper").

        Returns DecayReport with decay analysis.
        """
        _owned = db is None
        db = db or _get_session()
        report = DecayReport(strategy=strategy)

        try:
            from backend.models.outcome_tables import StrategyOutcome

            cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            outcomes = (
                db.query(StrategyOutcome)
                .filter(
                    StrategyOutcome.strategy == strategy,
                    StrategyOutcome.trading_mode == trading_mode,
                    StrategyOutcome.settled_at >= cutoff,
                    StrategyOutcome.result.in_(["win", "loss"]),
                )
                .order_by(StrategyOutcome.settled_at.asc())
                .all()
            )

            report.trades_analyzed = len(outcomes)

            if len(outcomes) < self.min_trades:
                report.recommendation = f"Insufficient data ({len(outcomes)}/{self.min_trades} trades)"
                return report

            # Baseline: first half win rate
            half = len(outcomes) // 2
            baseline_outcomes = outcomes[:half]
            recent_outcomes = outcomes[half:]

            baseline_wins = sum(1 for o in baseline_outcomes if o.result == "win")
            recent_wins = sum(1 for o in recent_outcomes if o.result == "win")

            report.baseline_wr = baseline_wins / len(baseline_outcomes) if baseline_outcomes else 0.0
            report.current_wr = recent_wins / len(recent_outcomes) if recent_outcomes else 0.0
            report.wr_delta = report.current_wr - report.baseline_wr

            # CUSUM detection
            report.cusum_score = self._cusum_detect(outcomes)

            # Rolling trend (linear regression slope)
            report.rolling_wr_trend = self._rolling_trend(outcomes)

            # Classify severity
            if report.wr_delta <= self.severe_decay_delta:
                report.decay_severity = "severe"
                report.is_decaying = True
                report.recommendation = "URGENT: Strategy severely degraded. Consider disabling immediately."
            elif report.wr_delta <= self.moderate_decay_delta:
                report.decay_severity = "moderate"
                report.is_decaying = True
                report.recommendation = "WARNING: Significant performance drop. Review strategy parameters."
            elif report.wr_delta <= self.mild_decay_delta or report.cusum_score > self.cusum_threshold:
                report.decay_severity = "mild"
                report.is_decaying = True
                report.recommendation = "NOTICE: Mild decay detected. Monitor closely."
            else:
                report.decay_severity = "none"
                report.is_decaying = False
                report.recommendation = "Strategy performing within normal parameters."

            logger.info(
                "[DecayDetector] '%s': baseline_wr=%.3f current_wr=%.3f "
                "delta=%.3f cusum=%.3f severity=%s",
                strategy, report.baseline_wr, report.current_wr,
                report.wr_delta, report.cusum_score, report.decay_severity,
            )

        except Exception as e:
            logger.error("[DecayDetector] Failed for '%s': %s", strategy, e, exc_info=True)
            report.recommendation = f"Error: {e}"
        finally:
            if _owned:
                db.close()

        return report

    def detect_all(
        self,
        db: Optional[Session] = None,
        lookback_days: int = 90,
        trading_mode: str = "live",
    ) -> list[DecayReport]:
        """Run decay detection on all active strategies."""
        _owned = db is None
        db = db or _get_session()
        reports = []

        try:
            from backend.models.database import StrategyConfig
            active = (
                db.query(StrategyConfig)
                .filter(StrategyConfig.enabled.is_(True))
                .all()
            )
            for cfg in active:
                report = self.detect(
                    cfg.strategy_name, db=db,
                    lookback_days=lookback_days,
                    trading_mode=trading_mode,
                )
                reports.append(report)
        except Exception as e:
            logger.error("[DecayDetector] detect_all failed: %s", e, exc_info=True)
        finally:
            if _owned:
                db.close()

        return reports

    def _cusum_detect(self, outcomes) -> float:
        """CUSUM control chart for detecting win rate shifts.

        Returns the maximum CUSUM score. Values above cusum_threshold
        indicate a significant downward shift in performance.
        """
        # Target: overall win rate
        wins = sum(1 for o in outcomes if o.result == "win")
        target_wr = wins / len(outcomes) if outcomes else 0.5

        # Individual outcomes as 1/0
        binary = [1.0 if o.result == "win" else 0.0 for o in outcomes]

        # CUSUM for downward shift
        cusum = 0.0
        max_cusum = 0.0
        allowance = 0.05  # Allow 5% deviation before triggering

        for val in binary:
            deviation = target_wr - val - allowance
            cusum = max(0.0, cusum + deviation)
            max_cusum = max(max_cusum, cusum)

        return max_cusum

    def _rolling_trend(self, outcomes) -> float:
        """Compute linear regression slope of rolling win rate over time.

        Negative slope indicates declining performance.
        """
        if len(outcomes) < self.window_size * 2:
            return 0.0

        # Compute rolling win rate
        rolling_wr = []
        for i in range(self.window_size, len(outcomes) + 1):
            window = outcomes[i - self.window_size:i]
            wins = sum(1 for o in window if o.result == "win")
            rolling_wr.append(wins / len(window))

        if len(rolling_wr) < 2:
            return 0.0

        # Simple linear regression
        n = len(rolling_wr)
        x_mean = (n - 1) / 2.0
        y_mean = sum(rolling_wr) / n
        numerator = sum((i - x_mean) * (rolling_wr[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator < 1e-9:
            return 0.0

        return numerator / denominator


def _get_session():
    from backend.models.database import SessionLocal
    return SessionLocal()
