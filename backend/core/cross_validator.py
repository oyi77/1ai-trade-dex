"""Time-series cross-validation for strategy validation across time windows.

Splits paper trades into temporal folds and validates that strategy performance
is consistent across different time periods (not just one lucky window).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class CrossValidationFold:
    """Result of a single time-series fold."""
    fold_num: int
    start: datetime
    end: datetime
    trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    pnl: float = 0.0


@dataclass
class CrossValidationResult:
    """Aggregated cross-validation results for a strategy."""
    strategy: str
    n_folds: int = 0
    folds: list[CrossValidationFold] = field(default_factory=list)
    mean_win_rate: float = 0.0
    std_win_rate: float = 0.0
    mean_pnl: float = 0.0
    worst_fold_wr: float = 0.0
    best_fold_wr: float = 0.0
    consistency_score: float = 0.0  # 0-1, higher = more consistent
    is_valid: bool = False

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "n_folds": self.n_folds,
            "mean_win_rate": round(self.mean_win_rate, 4),
            "std_win_rate": round(self.std_win_rate, 4),
            "mean_pnl": round(self.mean_pnl, 2),
            "worst_fold_wr": round(self.worst_fold_wr, 4),
            "best_fold_wr": round(self.best_fold_wr, 4),
            "consistency_score": round(self.consistency_score, 4),
            "is_valid": self.is_valid,
        }


class TimeSeriesCrossValidator:
    """Validates strategies across multiple time windows.

    Uses expanding window cross-validation: each fold uses all data up to
    the fold boundary for training and the next window for testing.
    """

    def __init__(
        self,
        n_folds: int = 5,
        min_trades_per_fold: int = 10,
        consistency_threshold: float = 0.6,
    ):
        self.n_folds = n_folds
        self.min_trades_per_fold = min_trades_per_fold
        self.consistency_threshold = consistency_threshold

    def validate(
        self,
        strategy: str,
        db: "Optional[Session]" = None,
        lookback_days: int = 90,
        trading_mode: str = "paper",
    ) -> CrossValidationResult:
        """Run time-series cross-validation for a strategy."""
        _owned = db is None
        db = db or _get_session()
        result = CrossValidationResult(strategy=strategy)

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

            if len(outcomes) < self.min_trades_per_fold * self.n_folds:
                logger.debug(
                    "[CrossValidator] \'%s\' has %d trades, need %d - skipping",
                    strategy, len(outcomes),
                    self.min_trades_per_fold * self.n_folds,
                )
                return result

            fold_size = len(outcomes) // self.n_folds
            wr_values = []

            for i in range(self.n_folds):
                start_idx = i * fold_size
                end_idx = start_idx + fold_size if i < self.n_folds - 1 else len(outcomes)
                fold_outcomes = outcomes[start_idx:end_idx]

                wins = sum(1 for o in fold_outcomes if o.result == "win")
                losses = sum(1 for o in fold_outcomes if o.result == "loss")
                wr = wins / len(fold_outcomes) if fold_outcomes else 0.0
                pnl = sum(o.pnl or 0.0 for o in fold_outcomes)

                fold = CrossValidationFold(
                    fold_num=i + 1,
                    start=fold_outcomes[0].settled_at if fold_outcomes else datetime.now(timezone.utc),
                    end=fold_outcomes[-1].settled_at if fold_outcomes else datetime.now(timezone.utc),
                    trades=len(fold_outcomes),
                    wins=wins,
                    losses=losses,
                    win_rate=wr,
                    pnl=pnl,
                )
                result.folds.append(fold)
                wr_values.append(wr)

            result.n_folds = len(result.folds)
            result.mean_win_rate = sum(wr_values) / len(wr_values) if wr_values else 0.0
            result.mean_pnl = sum(f.pnl for f in result.folds) / len(result.folds) if result.folds else 0.0
            result.worst_fold_wr = min(wr_values) if wr_values else 0.0
            result.best_fold_wr = max(wr_values) if wr_values else 0.0

            if len(wr_values) > 1:
                mean = result.mean_win_rate
                variance = sum((w - mean) ** 2 for w in wr_values) / (len(wr_values) - 1)
                result.std_win_rate = math.sqrt(variance)
            else:
                result.std_win_rate = 0.0

            if result.mean_win_rate > 0:
                cv = result.std_win_rate / result.mean_win_rate
                result.consistency_score = max(0.0, min(1.0, 1.0 - cv))
            else:
                result.consistency_score = 0.0

            result.is_valid = (
                result.consistency_score >= self.consistency_threshold
                and result.mean_win_rate > 0.0
            )

            logger.info(
                "[CrossValidator] \'%s\': %d folds, mean_wr=%.3f, std=%.3f, "
                "consistency=%.3f, valid=%s",
                strategy, result.n_folds, result.mean_win_rate,
                result.std_win_rate, result.consistency_score, result.is_valid,
            )

        except Exception as e:
            logger.error("[CrossValidator] Failed for \'%s\': %s", strategy, e, exc_info=True)
        finally:
            if _owned:
                db.close()

        return result

    def validate_all_active(
        self,
        db: "Optional[Session]" = None,
        lookback_days: int = 90,
        trading_mode: str = "paper",
    ) -> list[CrossValidationResult]:
        """Run cross-validation on all active strategies."""
        _owned = db is None
        db = db or _get_session()
        results = []

        try:
            from backend.models.database import StrategyConfig
            active = (
                db.query(StrategyConfig)
                .filter(StrategyConfig.enabled.is_(True))
                .all()
            )
            for cfg in active:
                cv_result = self.validate(
                    cfg.strategy_name, db=db,
                    lookback_days=lookback_days,
                    trading_mode=trading_mode,
                )
                results.append(cv_result)
        except Exception as e:
            logger.error("[CrossValidator] validate_all_active failed: %s", e, exc_info=True)
        finally:
            if _owned:
                db.close()

        return results


def _get_session():
    from backend.models.database import SessionLocal
    return SessionLocal()
