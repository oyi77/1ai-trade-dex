"""Strategy Performance Tracker — per-strategy, per-asset performance metrics.

Tracks win rate, average PnL, Sharpe ratio, and trade count per strategy
and optionally per asset. Used by AGISelfTuner to decide when tuning is
warranted and what parameters to adjust.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger

from backend.models.outcome_tables import StrategyOutcome
from backend.models.database import StrategyConfig
from backend.db.utils import get_db_session


@dataclass
class PerformanceMetrics:
    """Aggregated performance metrics for a strategy (optionally scoped to an asset)."""

    win_count: int = 0
    loss_count: int = 0
    total_trades: int = 0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    avg_edge_at_entry: float = 0.0
    last_trade_at: Optional[str] = None

    @property
    def is_sufficient(self) -> bool:
        """True if enough data exists for meaningful analysis."""
        return self.total_trades >= 10

    def to_dict(self) -> Dict[str, Any]:
        return {
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "total_trades": self.total_trades,
            "total_pnl": round(self.total_pnl, 4),
            "avg_pnl": round(self.avg_pnl, 4),
            "win_rate": round(self.win_rate, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "avg_edge_at_entry": round(self.avg_edge_at_entry, 4),
            "last_trade_at": self.last_trade_at,
        }


def _compute_sharpe(pnls: list[float]) -> float:
    """Annualized Sharpe ratio from a list of per-trade PnLs."""
    if len(pnls) < 2:
        return 0.0
    mean = sum(pnls) / len(pnls)
    variance = sum((p - mean) ** 2 for p in pnls) / len(pnls)
    std = math.sqrt(variance) if variance > 0 else 1e-9
    return (mean / std) * math.sqrt(len(pnls))


class StrategyPerformanceTracker:
    """Tracks per-strategy and per-asset performance metrics.

    Reads from the strategy_outcomes table to compute win rate, Sharpe,
    average PnL, and trade count. Supports optional asset-level scoping
    for strategies like crypto_oracle that trade multiple assets.
    """

    def get_performance(
        self,
        strategy_name: str,
        asset: Optional[str] = None,
        limit: int = 100,
    ) -> PerformanceMetrics:
        """Get performance metrics for a strategy, optionally scoped to an asset.

        Args:
            strategy_name: Strategy to query.
            asset: Optional asset filter (matched against market_ticker).
            limit: Max recent trades to analyze.

        Returns:
            PerformanceMetrics with aggregated stats.
        """
        try:
            with get_db_session() as db:
                query = (
                    db.query(StrategyOutcome)
                    .filter(StrategyOutcome.strategy == strategy_name)
                    .filter(StrategyOutcome.result.in_(("win", "loss")))
                )
                if asset:
                    query = query.filter(
                        StrategyOutcome.market_ticker.ilike(f"%{asset}%")
                    )
                rows = (
                    query.order_by(StrategyOutcome.settled_at.desc())
                    .limit(limit)
                    .all()
                )

                if not rows:
                    return PerformanceMetrics()

                pnls = [r.pnl for r in rows if r.pnl is not None]
                wins = sum(1 for r in rows if r.result == "win")
                losses = sum(1 for r in rows if r.result == "loss")
                edges = [r.edge_at_entry for r in rows if r.edge_at_entry is not None]

                total_pnl = sum(pnls)
                last_trade = rows[0].settled_at if rows[0].settled_at else None

                return PerformanceMetrics(
                    win_count=wins,
                    loss_count=losses,
                    total_trades=len(rows),
                    total_pnl=total_pnl,
                    avg_pnl=total_pnl / len(pnls) if pnls else 0.0,
                    win_rate=wins / len(rows) if rows else 0.0,
                    sharpe_ratio=_compute_sharpe(pnls),
                    avg_edge_at_entry=sum(edges) / len(edges) if edges else 0.0,
                    last_trade_at=last_trade.isoformat() if last_trade else None,
                )
        except Exception:
            logger.exception(
                f"[PerformanceTracker] Failed to get performance for {strategy_name}"
            )
            return PerformanceMetrics()

    def get_tunable_params(self, strategy_name: str) -> Dict[str, Any]:
        """Get current tunable parameters and their values from StrategyConfig.

        Returns:
            Dict of param_name -> current_value for numeric params.
        """
        try:
            with get_db_session() as db:
                config = (
                    db.query(StrategyConfig)
                    .filter(StrategyConfig.strategy_name == strategy_name)
                    .first()
                )
                if not config or not config.params:
                    return {}

                import json

                params = (
                    json.loads(config.params)
                    if isinstance(config.params, str)
                    else config.params
                )
                if not isinstance(params, dict):
                    return {}

                # Return only numeric params that are safe to tune
                return {
                    k: v
                    for k, v in params.items()
                    if isinstance(v, (int, float)) and v != 0
                }
        except Exception:
            logger.exception(
                f"[PerformanceTracker] Failed to get tunable params for {strategy_name}"
            )
            return {}

    def should_tune(self, strategy_name: str) -> bool:
        """True if enough data exists and performance warrants tuning.

        Tuning is warranted when:
        - At least 15 settled trades exist
        - Win rate is below 55% (room for improvement) or above 65% (loosen constraints)
        """
        perf = self.get_performance(strategy_name, limit=50)
        if perf.total_trades < 15:
            return False
        # Tune if underperforming (< 55%) or overperforming (> 65%)
        return perf.win_rate < 0.55 or perf.win_rate > 0.65


# Module-level singleton
_tracker: Optional[StrategyPerformanceTracker] = None


def get_performance_tracker() -> StrategyPerformanceTracker:
    """Get or create the module-level singleton."""
    global _tracker
    if _tracker is None:
        _tracker = StrategyPerformanceTracker()
    return _tracker
