"""
DEPRECATED: Use backend.core.learning_system instead.
This module will be removed in a future release.

Learning System - Tracks model predictions and outcomes for calibration and analysis.
Supports both online (real-time) and offline (batch) learning modes.
"""



from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from enum import Enum
import numpy as np
from sqlalchemy import Column, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base

# Use a basic logger; we'll assume structlog is available for binding if used in the app
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Local Base to avoid circular imports if database.py is huge
Base = declarative_base()


class LearningMode(Enum):
    OFFLINE = "offline"
    ONLINE = "online"


@dataclass
class LearningExample:
    """Individual learning example tracking prediction and actual outcome."""

    domain: str
    strategy_key: str
    market_id: str
    prediction: float
    actual: float
    pnl: float
    timestamp: datetime
    confidence: float = 1.0


@dataclass
class CalibrationBin:
    """Calibration statistics for a confidence range."""

    lower_bound: float
    upper_bound: float
    count: int
    avg_confidence: float
    accuracy: float


@dataclass
class CalibrationReport:
    """Combined calibration metrics."""

    brier_score: float
    bins: List[CalibrationBin]
    accuracy: float


class LearningExampleModel(Base):
    """Database model for persisting learning examples."""

    __tablename__ = "learning_examples"

    id = Column(String, primary_key=True)
    domain = Column(String, index=True, nullable=False)
    strategy_key = Column(String, index=True, nullable=False)
    market_id = Column(String, index=True, nullable=False)
    prediction = Column(Float, nullable=False)
    actual = Column(Float, nullable=False)
    pnl = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    confidence = Column(Float, default=1.0)

    def to_learning_example(self) -> LearningExample:
        return LearningExample(
            domain=self.domain,
            strategy_key=self.strategy_key,
            market_id=self.market_id,
            prediction=self.prediction,
            actual=self.actual,
            pnl=self.pnl,
            timestamp=self.timestamp,
            confidence=self.confidence,
        )


class LearningSystem:
    """
    Manages learning examples and computes calibration metrics.
    """

    def __init__(
        self,
        session,
        mode: LearningMode = LearningMode.ONLINE,
        max_examples: int = 10_000,
    ):
        self.session = session
        self.mode = mode
        self.max_examples = max_examples
        # Handle structlog-style binding if possible, else fallback to standard logging
        try:
            self._log = logger.bind(task="learning")
        except AttributeError:
            self._log = logger

    def record_outcome(
        self,
        strategy_key: str,
        market_id: str,
        prediction: float,
        actual: float,
        pnl: float,
        timestamp: Optional[datetime] = None,
        confidence: float = 1.0,
        domain: str = "default",
    ) -> None:
        """Record a learning example with prediction and actual outcome."""
        if not (0 <= confidence <= 1):
            raise ValueError("Confidence must be between 0 and 1")

        if not timestamp:
            timestamp = datetime.now(timezone.utc)

        # Use a unique ID based on strategy and timestamp
        example_id = f"{strategy_key}:{market_id}:{timestamp.timestamp()}"

        example = LearningExampleModel(
            id=example_id,
            domain=domain,
            strategy_key=strategy_key,
            market_id=market_id,
            prediction=prediction,
            actual=actual,
            pnl=pnl,
            timestamp=timestamp,
            confidence=confidence,
        )

        if self.mode == LearningMode.ONLINE:
            try:
                self.session.add(example)
                self.session.commit()
            except Exception as e:
                self.session.rollback()
                self._log.error(f"Failed to save learning example: {e}")
        else:
            self._log.info(
                f"Offline learning - example not saved to DB: {strategy_key}"
            )

        self._log.debug(f"Learning example recorded for {domain}:{strategy_key}")

    def get_learning_examples(self, domain: str, n: int = 100) -> List[LearningExample]:
        """Retrieve recent learning examples for a domain."""
        try:
            query = (
                self.session.query(LearningExampleModel)
                .filter(LearningExampleModel.domain == domain)
                .order_by(LearningExampleModel.timestamp.desc())
                .limit(n)
            )
            results = [e.to_learning_example() for e in query.all()]
            return results
        except Exception as e:
            self._log.error(f"Failed to fetch learning examples: {e}")
            return []

    def compute_calibration(self, domain: str) -> CalibrationReport:
        """Compute calibration metrics for a domain."""
        examples = self.get_learning_examples(domain)
        if not examples:
            return CalibrationReport(0.0, [], 0.0)

        # Binary accuracy: prediction >= 0.5 vs actual >= 0.5
        correct = sum(1 for e in examples if (e.prediction >= 0.5) == (e.actual >= 0.5))
        accuracy = correct / len(examples)

        # Brier score: Mean Squared Error between prediction and binary outcome
        brier_score = np.mean(
            [(e.prediction - (1.0 if e.actual >= 0.5 else 0.0)) ** 2 for e in examples]
        )

        # Calibration bins (10 bins from 0.0 to 1.0)
        num_bins = 10
        bin_data = [
            [0.0, 0.0, 0] for _ in range(num_bins)
        ]  # [sum_conf, sum_acc, count]

        for e in examples:
            bin_idx = min(int(e.confidence * num_bins), num_bins - 1)
            bin_data[bin_idx][0] += e.confidence
            bin_data[bin_idx][1] += (
                1 if (e.prediction >= 0.5) == (e.actual >= 0.5) else 0
            )
            bin_data[bin_idx][2] += 1

        calibration_bins = []
        for i in range(num_bins):
            lower = i / num_bins
            upper = (i + 1) / num_bins
            count = bin_data[i][2]
            if count > 0:
                calibration_bins.append(
                    CalibrationBin(
                        lower_bound=lower,
                        upper_bound=upper,
                        count=count,
                        avg_confidence=bin_data[i][0] / count,
                        accuracy=bin_data[i][1] / count,
                    )
                )

        return CalibrationReport(
            brier_score=float(brier_score), bins=calibration_bins, accuracy=accuracy
        )

    def get_learning_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics about the learning system."""
        stats = {"total_examples": 0, "domains": {}, "mode": self.mode.value}

        try:
            # Count per domain using sqlalchemy func.count
            from sqlalchemy import func

            domain_counts = (
                self.session.query(
                    LearningExampleModel.domain, func.count(LearningExampleModel.domain)
                )
                .group_by(LearningExampleModel.domain)
                .all()
            )

            for domain, count in domain_counts:
                stats["domains"][domain] = {"example_count": count}
                stats["total_examples"] += count

                # Get deeper stats for this domain if it has examples
                examples = self.get_learning_examples(domain, n=1000)
                if examples:
                    correct = sum(
                        1
                        for e in examples
                        if (e.prediction >= 0.5) == (e.actual >= 0.5)
                    )
                    stats["domains"][domain]["accuracy"] = correct / len(examples)
                    stats["domains"][domain]["latest_example"] = examples[
                        0
                    ].timestamp.isoformat()

        except Exception as e:
            self._log.error(f"Failed to compute learning stats: {e}")

        return stats
