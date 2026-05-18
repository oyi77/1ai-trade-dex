"""Paper-Live Performance Correlation Tracker.

Tracks how paper trading performance correlates with live results
to validate that paper-mode optimization translates to real performance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from loguru import logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class PaperLiveCorrelation:
    """Correlation metrics between paper and live performance for a strategy."""
    strategy: str
    paper_trades: int = 0
    live_trades: int = 0
    paper_win_rate: float = 0.0
    live_win_rate: float = 0.0
    paper_pnl: float = 0.0
    live_pnl: float = 0.0
    paper_sharpe: float = 0.0
    live_sharpe: float = 0.0
    wr_correlation: float = 0.0  # -1 to 1
    pnl_correlation: float = 0.0
    degradation_ratio: float = 1.0  # live_wr / paper_wr (< 1 = degradation)
    is_correlated: bool = False
    warning: str = ""

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "paper_trades": self.paper_trades,
            "live_trades": self.live_trades,
            "paper_win_rate": round(self.paper_win_rate, 4),
            "live_win_rate": round(self.live_win_rate, 4),
            "paper_pnl": round(self.paper_pnl, 2),
            "live_pnl": round(self.live_pnl, 2),
            "paper_sharpe": round(self.paper_sharpe, 3),
            "live_sharpe": round(self.live_sharpe, 3),
            "wr_correlation": round(self.wr_correlation, 4),
            "pnl_correlation": round(self.pnl_correlation, 4),
            "degradation_ratio": round(self.degradation_ratio, 4),
            "is_correlated": self.is_correlated,
            "warning": self.warning,
        }


class PaperLiveCorrelator:
    """Tracks and analyzes paper vs live performance correlation.

    Compares rolling win rates, PnL trajectories, and Sharpe ratios
    between paper and live trading modes for each strategy.
    """

    def __init__(
        self,
        min_paper_trades: int = 20,
        min_live_trades: int = 10,
        lookback_days: int = 30,
        degradation_threshold: float = 0.70,
    ):
        self.min_paper_trades = min_paper_trades
        self.min_live_trades = min_live_trades
        self.lookback_days = lookback_days
        self.degradation_threshold = degradation_threshold

    def compute_correlation(
        self,
        strategy: str,
        db: Optional[Session] = None,
    ) -> PaperLiveCorrelation:
        """Compute paper-live correlation for a single strategy."""
        _owned = db is None
        db = db or _get_session()
        result = PaperLiveCorrelation(strategy=strategy)

        try:
            from backend.models.outcome_tables import StrategyOutcome

            cutoff = datetime.now(timezone.utc) - timedelta(days=self.lookback_days)

            # Get paper outcomes
            paper = (
                db.query(StrategyOutcome)
                .filter(
                    StrategyOutcome.strategy == strategy,
                    StrategyOutcome.trading_mode == "paper",
                    StrategyOutcome.settled_at >= cutoff,
                    StrategyOutcome.result.in_(["win", "loss"]),
                )
                .order_by(StrategyOutcome.settled_at.asc())
                .all()
            )

            # Get live outcomes
            live = (
                db.query(StrategyOutcome)
                .filter(
                    StrategyOutcome.strategy == strategy,
                    StrategyOutcome.trading_mode == "live",
                    StrategyOutcome.settled_at >= cutoff,
                    StrategyOutcome.result.in_(["win", "loss"]),
                )
                .order_by(StrategyOutcome.settled_at.asc())
                .all()
            )

            result.paper_trades = len(paper)
            result.live_trades = len(live)

            if len(paper) < self.min_paper_trades or len(live) < self.min_live_trades:
                result.warning = f"Insufficient data: paper={len(paper)}, live={len(live)}"
                return result

            # Compute win rates
            paper_wins = sum(1 for o in paper if o.result == "win")
            live_wins = sum(1 for o in live if o.result == "win")
            result.paper_win_rate = paper_wins / len(paper)
            result.live_win_rate = live_wins / len(live)

            # Compute PnL
            result.paper_pnl = sum(o.pnl or 0.0 for o in paper)
            result.live_pnl = sum(o.pnl or 0.0 for o in live)

            # Compute Sharpe ratios
            result.paper_sharpe = self._sharpe(paper)
            result.live_sharpe = self._sharpe(live)

            # Rolling correlation: compare win rates in aligned time windows
            result.wr_correlation = self._rolling_correlation(paper, live, metric="win")
            result.pnl_correlation = self._rolling_correlation(paper, live, metric="pnl")

            # Degradation ratio
            if result.paper_win_rate > 0:
                result.degradation_ratio = result.live_win_rate / result.paper_win_rate
            else:
                result.degradation_ratio = 1.0

            # Is correlated if degradation is acceptable
            result.is_correlated = result.degradation_ratio >= self.degradation_threshold

            if not result.is_correlated:
                result.warning = (
                    f"Performance degradation: live WR ({result.live_win_rate:.1%}) "
                    f"is {result.degradation_ratio:.0%} of paper WR ({result.paper_win_rate:.1%})"
                )

            logger.info(
                "[PaperLiveCorrelator] '%s': paper_wr=%.3f live_wr=%.3f "
                "degradation=%.3f correlated=%s",
                strategy, result.paper_win_rate, result.live_win_rate,
                result.degradation_ratio, result.is_correlated,
            )

        except Exception as e:
            logger.error(
                "[PaperLiveCorrelator] Failed for '%s': %s", strategy, e, exc_info=True,
            )
            result.warning = f"Error: {e}"
        finally:
            if _owned:
                db.close()

        return result

    def compute_all(
        self,
        db: Optional[Session] = None,
    ) -> list[PaperLiveCorrelation]:
        """Compute paper-live correlation for all active strategies."""
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
                corr = self.compute_correlation(cfg.strategy_name, db=db)
                results.append(corr)
        except Exception as e:
            logger.error("[PaperLiveCorrelator] compute_all failed: %s", e, exc_info=True)
        finally:
            if _owned:
                db.close()

        return results

    def _sharpe(self, outcomes) -> float:
        pnls = [o.pnl for o in outcomes if o.pnl is not None]
        if len(pnls) < 2:
            return 0.0
        n = len(pnls)
        mean = sum(pnls) / n
        variance = sum((p - mean) ** 2 for p in pnls) / n
        std = math.sqrt(variance) if variance > 0 else 1e-9
        return (mean / std) * math.sqrt(n)

    def _rolling_correlation(self, paper, live, metric: str = "win") -> float:
        """Compute Pearson correlation between paper and live in aligned windows.

        Splits both series into equal-sized windows and correlates
        the per-window metric (win rate or PnL).
        """
        n_windows = min(5, len(paper) // 5, len(live) // 5)
        if n_windows < 2:
            return 0.0

        paper_chunk = len(paper) // n_windows
        live_chunk = len(live) // n_windows

        paper_vals = []
        live_vals = []

        for i in range(n_windows):
            p_slice = paper[i * paper_chunk:(i + 1) * paper_chunk]
            l_slice = live[i * live_chunk:(i + 1) * live_chunk]

            if metric == "win":
                paper_vals.append(sum(1 for o in p_slice if o.result == "win") / len(p_slice) if p_slice else 0)
                live_vals.append(sum(1 for o in l_slice if o.result == "win") / len(l_slice) if l_slice else 0)
            else:
                paper_vals.append(sum(o.pnl or 0 for o in p_slice))
                live_vals.append(sum(o.pnl or 0 for o in l_slice))

        return self._pearson(paper_vals, live_vals)

    @staticmethod
    def _pearson(x: list[float], y: list[float]) -> float:
        n = len(x)
        if n < 2:
            return 0.0
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        std_x = math.sqrt(sum((v - mean_x) ** 2 for v in x))
        std_y = math.sqrt(sum((v - mean_y) ** 2 for v in y))
        if std_x < 1e-9 or std_y < 1e-9:
            return 0.0
        return cov / (std_x * std_y)


def _get_session():
    from backend.models.database import SessionLocal
    return SessionLocal()
