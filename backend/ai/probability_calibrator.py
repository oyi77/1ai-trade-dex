"""Probability calibrator — Platt scaling + Brier score tracking for debate engine.

Transforms raw LLM debate probabilities into calibrated estimates using
historical outcome data. Tracks per-agent Brier scores for adaptive weighting.

Architecture:
  1. DebateOutcome records: (question, agent, raw_prob, actual_outcome, timestamp)
  2. Platt scaling: logistic regression on raw_prob → calibrated_prob
  3. Brier score: per-agent rolling window for ensemble weight adaptation
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from loguru import logger
from sqlalchemy.orm import Session

from backend.ai.probability_utils import clamp_probability
from backend.db.utils import utcnow


# ── Data types ──────────────────────────────────────────────────────────────

@dataclass
class DebateOutcome:
    """Record of a single debate prediction vs actual outcome."""
    question: str
    agent: str  # "bull", "bear", "judge", "mirofish", "ensemble"
    raw_probability: float
    calibrated_probability: float
    actual_outcome: str  # "win" | "loss" | None (pending)
    market_price: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    brier_score: float = 0.0


@dataclass
class AgentCalibration:
    """Per-agent calibration stats."""
    agent: str
    total_predictions: int
    brier_score: float  # lower = better calibrated
    reliability: float  # correlation between predicted and actual
    platt_a: float = 1.0  # Platt scaling slope
    platt_b: float = 0.0  # Platt scaling intercept
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Platt scaling ───────────────────────────────────────────────────────────

def fit_platt(predictions: list[float], outcomes: list[int]) -> tuple[float, float]:
    """Fit Platt scaling parameters (a, b) using logistic regression.

    Platt scaling maps raw probability p → 1/(1 + exp(-(a*p + b))).

    Args:
        predictions: Raw predicted probabilities [0, 1]
        outcomes: Actual binary outcomes (1 = win, 0 = loss)

    Returns:
        (a, b) tuple — Platt scaling parameters
    """
    if len(predictions) < 10:
        return 1.0, 0.0  # Not enough data — identity transform

    # Avoid log(0) / log(1) by clipping
    eps = 1e-6
    p = np.clip(np.array(predictions, dtype=np.float64), eps, 1 - eps)
    y = np.array(outcomes, dtype=np.float64)

    # Platt: fit logistic regression on log-odds of raw predictions
    # target = a * log(p/(1-p)) + b
    log_odds = np.log(p / (1 - p))

    # Simple linear regression: target = a * log_odds + b
    # where target = 1 for win, 0 for loss (but we use log-odds of outcome)
    # Actually Platt uses: P(y=1|x) = 1/(1+exp(-(A*f(x)+B)))
    # where f(x) is the raw model output (log-odds or probability)
    # We fit: A * raw_prob + B = log(P/(1-P)) of actual outcomes

    # Use scipy-style least squares
    X = np.column_stack([p, np.ones_like(p)])
    # Target: log-odds of actual outcome rate in probability bins
    # Simpler approach: fit directly on (raw_prob, outcome) pairs
    try:
        # Ridge-regularized least squares for stability
        XtX = X.T @ X
        ridge = np.eye(2) * 0.01
        Xty = X.T @ y
        params = np.linalg.solve(XtX + ridge, Xty)
        a, b = float(params[0]), float(params[1])
    except np.linalg.LinAlgError:
        return 1.0, 0.0

    # Clamp to reasonable range
    a = max(-10.0, min(10.0, a))
    b = max(-5.0, min(5.0, b))
    return a, b


def apply_platt(raw_prob: float, a: float, b: float) -> float:
    """Apply Platt scaling to a raw probability."""
    return clamp_probability(1.0 / (1.0 + math.exp(-(a * raw_prob + b))))


def compute_brier(predictions: list[float], outcomes: list[int]) -> float:
    """Compute Brier score: mean squared error between prediction and outcome.

    Brier = (1/N) * Σ(p_i - o_i)²
    Lower is better. 0 = perfect, 0.25 = always predicting 0.5.
    """
    if not predictions:
        return 0.0
    return float(np.mean((np.array(predictions) - np.array(outcomes)) ** 2))


# ── Calibrator ──────────────────────────────────────────────────────────────

class ProbabilityCalibrator:
    """Calibrates raw debate probabilities using historical outcome data.

    Usage:
        calibrator = ProbabilityCalibrator()
        calibrated = calibrator.calibrate("judge", raw_prob=0.72, db=session)
        # Also records outcome after settlement:
        calibrator.record_outcome(question, "judge", 0.72, "win", db)
    """

    MIN_SAMPLES_FOR_CALIBRATION = 20

    def calibrate(
        self,
        agent: str,
        raw_prob: float,
        db: Session,
    ) -> tuple[float, float]:
        """Calibrate a raw probability from an agent.

        Args:
            agent: Agent name ("bull", "bear", "judge", "mirofish", "ensemble")
            raw_prob: Raw probability from the agent [0, 1]
            db: Database session

        Returns:
            (calibrated_prob, brier_score) tuple
        """
        calibration = self._get_agent_calibration(agent, db)
        if calibration.total_predictions < self.MIN_SAMPLES_FOR_CALIBRATION:
            # Not enough data — return raw with identity transform
            return raw_prob, 0.0

        calibrated = apply_platt(raw_prob, calibration.platt_a, calibration.platt_b)
        logger.debug(
            f"[Calibrator] {agent}: raw={raw_prob:.3f} → calibrated={calibrated:.3f} "
            f"(a={calibration.platt_a:.2f}, b={calibration.platt_b:.2f}, "
            f"n={calibration.total_predictions}, brier={calibration.brier_score:.3f})"
        )
        return calibrated, calibration.brier_score

    def record_outcome(
        self,
        question: str,
        agent: str,
        raw_prob: float,
        actual_outcome: str,
        market_price: float,
        db: Session,
    ) -> None:
        """Record a debate outcome for future calibration.

        Persists to calibration_records table and updates agent calibration.
        """
        from backend.models.database import CalibrationRecord

        calibrated, _ = self.calibrate(agent, raw_prob, db)

        record = CalibrationRecord(
            strategy=f"debate_{agent}",
            market_ticker=question[:80],
            predicted_prob=raw_prob,
            direction="YES" if raw_prob > 0.5 else "NO",
            actual_outcome=actual_outcome,
            price_bucket=self._price_bucket(market_price),
            timestamp=utcnow(),
        )
        db.add(record)
        db.commit()

        # Update agent calibration stats
        self._update_agent_calibration(agent, db)

        logger.info(
            f"[Calibrator] Recorded {agent} outcome: raw={raw_prob:.3f} "
            f"actual={actual_outcome} market={market_price:.3f}"
        )

    def get_agent_brier(self, agent: str, db: Session) -> float:
        """Get current Brier score for an agent."""
        cal = self._get_agent_calibration(agent, db)
        return cal.brier_score

    def get_all_brier_scores(self, db: Session) -> dict[str, float]:
        """Get Brier scores for all tracked agents."""
        agents = ["bull", "bear", "judge", "mirofish", "ensemble"]
        return {a: self.get_agent_brier(a, db) for a in agents}

    # ── private ──────────────────────────────────────────────────────────────

    def _get_agent_calibration(self, agent: str, db: Session) -> AgentCalibration:
        """Get or create calibration stats for an agent."""
        from backend.models.database import CalibrationRecord

        records = (
            db.query(CalibrationRecord)
            .filter(
                CalibrationRecord.strategy == f"debate_{agent}",
                CalibrationRecord.actual_outcome.isnot(None),
            )
            .order_by(CalibrationRecord.timestamp.desc())
            .limit(200)
            .all()
        )

        if not records:
            return AgentCalibration(agent=agent, total_predictions=0, brier_score=0.0, reliability=0.0)

        predictions = [r.predicted_prob for r in records]
        outcomes = [1 if r.actual_outcome == "win" else 0 for r in records]
        brier = compute_brier(predictions, outcomes)

        # Fit Platt scaling
        a, b = fit_platt(predictions, outcomes)

        # Reliability: correlation between predicted and actual
        reliability = 0.0
        if len(predictions) >= 10:
            try:
                corr = np.corrcoef(predictions, outcomes)[0, 1]
                reliability = float(0.0 if np.isnan(corr) else corr)
            except Exception:
                pass

        return AgentCalibration(
            agent=agent,
            total_predictions=len(records),
            brier_score=brier,
            reliability=reliability,
            platt_a=a,
            platt_b=b,
        )

    def _update_agent_calibration(self, agent: str, db: Session) -> None:
        """Force recalculation of agent calibration stats (called after recording)."""
        # Stats are computed lazily on next calibrate() call — no persistent cache needed
        pass

    @staticmethod
    def _price_bucket(price: float) -> str:
        """Map price to a bucket label for calibration grouping."""
        if price < 0.05:
            return "0-5c"
        elif price < 0.10:
            return "5-10c"
        elif price < 0.20:
            return "10-20c"
        elif price < 0.40:
            return "20-40c"
        elif price < 0.60:
            return "40-60c"
        elif price < 0.80:
            return "60-80c"
        elif price < 0.90:
            return "80-90c"
        elif price < 0.95:
            return "90-95c"
        else:
            return "95c-1"


# ── Adaptive Ensemble ────────────────────────────────────────────────────────

class AdaptiveEnsemble:
    """Ensemble with dynamic weights based on component Brier scores.

    Extends the static EnsembleSignalGenerator with periodic weight recalibration.
    """

    def __init__(self, calibrator: ProbabilityCalibrator | None = None):
        self.calibrator = calibrator or ProbabilityCalibrator()
        self._weights: dict[str, float] = {
            "technical": 0.40,
            "ai": 0.30,
            "orderbook": 0.15,
            "data_quality": 0.15,
        }
        self._last_update: datetime | None = None
        self._update_interval_hours: float = 24.0

    @property
    def weights(self) -> dict[str, float]:
        return dict(self._weights)

    def update_weights(self, db: Session) -> dict[str, float]:
        """Recalculate ensemble weights based on component Brier scores.

        Components with lower Brier scores (better calibrated) get higher weight.
        Components with no track record keep their default weight.

        Returns updated weights dict.
        """
        brier_scores = self.calibrator.get_all_brier_scores(db)

        # Map ensemble components to debate agents
        component_to_agent = {
            "ai": "judge",       # AI component = debate judge consensus
            "technical": None,   # Technical has no debate agent — keep default
            "orderbook": None,   # Orderbook has no debate agent — keep default
            "data_quality": None, # Data quality is a multiplier, not a predictor
        }

        new_weights: dict[str, float] = {}
        tracked_briers: dict[str, float] = {}

        for component, agent in component_to_agent.items():
            if agent and agent in brier_scores and brier_scores[agent] > 0:
                # Inverse Brier: lower Brier → higher weight
                # Add small epsilon to avoid division by zero
                weight = 1.0 / (brier_scores[agent] + 0.05)
                tracked_briers[component] = weight
            else:
                # Keep default weight for untracked components
                new_weights[component] = self._weights.get(component, 0.15)

        # Normalize tracked components
        if tracked_briers:
            total = sum(tracked_briers.values())
            for component, w in tracked_briers.items():
                new_weights[component] = w / total * 0.60  # AI gets up to 60% of total

            # Redistribute remaining 40% to untracked components
            untracked_total = sum(
                w for c, w in new_weights.items() if c not in tracked_briers
            )
            if untracked_total > 0:
                remaining = 1.0 - sum(tracked_briers.values()) / total * 0.60
                for component in new_weights:
                    if component not in tracked_briers:
                        new_weights[component] = (
                            new_weights[component] / untracked_total * remaining
                        )

        # Ensure all default components exist
        for component in self._weights:
            if component not in new_weights:
                new_weights[component] = self._weights[component]

        # Normalize to 1.0
        total = sum(new_weights.values())
        if total > 0:
            new_weights = {k: v / total for k, v in new_weights.items()}

        self._weights = new_weights
        self._last_update = datetime.now(timezone.utc)

        logger.info(
            f"[AdaptiveEnsemble] Weights updated: { {k: f'{v:.3f}' for k, v in new_weights.items()} } "
            f"(brier_scores={ {k: f'{v:.3f}' for k, v in brier_scores.items() if v > 0} })"
        )
        return dict(new_weights)

    def should_update(self) -> bool:
        """Check if enough time has passed to update weights."""
        if self._last_update is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_update).total_seconds()
        return elapsed >= self._update_interval_hours * 3600


# ── Module-level singleton ───────────────────────────────────────────────────

_calibrator: ProbabilityCalibrator | None = None
_adaptive_ensemble: AdaptiveEnsemble | None = None


def get_calibrator() -> ProbabilityCalibrator:
    global _calibrator
    if _calibrator is None:
        _calibrator = ProbabilityCalibrator()
    return _calibrator


def get_adaptive_ensemble() -> AdaptiveEnsemble:
    global _adaptive_ensemble
    if _adaptive_ensemble is None:
        _adaptive_ensemble = AdaptiveEnsemble(get_calibrator())
    return _adaptive_ensemble


def reset_calibrator() -> None:
    """Reset singletons (useful for testing)."""
    global _calibrator, _adaptive_ensemble
    _calibrator = None
    _adaptive_ensemble = None
