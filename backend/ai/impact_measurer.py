"""Impact Measurer Module - Wave 4c

Measures the real-world impact of executed strategy proposals by comparing
performance metrics before and after proposal execution.

This module:
- Calculates performance deltas (Sharpe ratio, win rate, avg PnL, edge improvement)
- Stores impact measurements in the database
- Provides rollback capability to revert unsuccessful proposals
- Tracks proposal effectiveness over time

Integration points:
- ProposalGenerator (Wave 4b) - measures impact of generated proposals
- RollbackManager - triggers rollback for negative impact proposals
- Database - stores ProposalImpact and StrategyConfigSnapshot records
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass
import numpy as np

from backend.models.database import Trade, StrategyProposal

logger = logging.getLogger(__name__)


@dataclass
class ProposalImpact:
    """Impact measurement results for a proposal."""

    proposal_id: int
    sharpe_ratio_delta: float
    win_rate_delta: float
    avg_pnl_delta: float
    edge_improvement: float
    total_trades_before: int
    total_trades_after: int
    measured_at: datetime
    impact_score: float  # Composite score 0-100


class ImpactMeasurer:
    """Measures the impact of executed strategy proposals."""

    MIN_SAMPLE_SIZE = 20  # Minimum trades required for valid measurement

    def __init__(self):
        """Initialize the ImpactMeasurer."""
        self.logger = logging.getLogger(__name__)

    def measure_proposal_impact(
        self,
        proposal_id: int,
        trades_before: List[Trade],
        trades_after: List[Trade]
    ) -> Optional[ProposalImpact]:
        """Measure the impact of a proposal by comparing before/after metrics.

        Args:
            proposal_id: Database ID of the executed proposal
            trades_before: List of trades before proposal execution
            trades_after: List of trades after proposal execution

        Returns:
            ProposalImpact object with calculated metrics, or None if insufficient data
        """
        # Validate minimum sample size
        if len(trades_before) < self.MIN_SAMPLE_SIZE:
            self.logger.warning(
                f"Insufficient trades before proposal {proposal_id}: "
                f"{len(trades_before)} < {self.MIN_SAMPLE_SIZE}"
            )
            return None

        if len(trades_after) < self.MIN_SAMPLE_SIZE:
            self.logger.warning(
                f"Insufficient trades after proposal {proposal_id}: "
                f"{len(trades_after)} < {self.MIN_SAMPLE_SIZE}"
            )
            return None

        self.logger.info(
            f"Measuring impact for proposal {proposal_id}: "
            f"{len(trades_before)} trades before, {len(trades_after)} trades after"
        )

        # Calculate metrics for before period
        metrics_before = self._calculate_metrics(trades_before)

        # Calculate metrics for after period
        metrics_after = self._calculate_metrics(trades_after)

        # Calculate deltas
        sharpe_delta = metrics_after['sharpe_ratio'] - metrics_before['sharpe_ratio']
        win_rate_delta = metrics_after['win_rate'] - metrics_before['win_rate']
        avg_pnl_delta = metrics_after['avg_pnl'] - metrics_before['avg_pnl']
        edge_delta = metrics_after['avg_edge'] - metrics_before['avg_edge']

        # Calculate composite impact score (0-100)
        impact_score = self._calculate_impact_score(
            sharpe_delta=sharpe_delta,
            win_rate_delta=win_rate_delta,
            avg_pnl_delta=avg_pnl_delta,
            edge_delta=edge_delta
        )

        impact = ProposalImpact(
            proposal_id=proposal_id,
            sharpe_ratio_delta=sharpe_delta,
            win_rate_delta=win_rate_delta,
            avg_pnl_delta=avg_pnl_delta,
            edge_improvement=edge_delta,
            total_trades_before=len(trades_before),
            total_trades_after=len(trades_after),
            measured_at=datetime.now(timezone.utc),
            impact_score=impact_score
        )

        # Store impact in database
        self._store_impact(impact, metrics_before, metrics_after)

        self.logger.info(
            f"Impact measured for proposal {proposal_id}: "
            f"Sharpe Δ={sharpe_delta:.3f}, WinRate Δ={win_rate_delta:.3f}, "
            f"PnL Δ={avg_pnl_delta:.2f}, Edge Δ={edge_delta:.3f}, "
            f"Score={impact_score:.1f}"
        )

        return impact

    def _calculate_metrics(self, trades: List[Trade]) -> Dict[str, float]:
        """Calculate performance metrics for a set of trades.

        Args:
            trades: List of Trade objects

        Returns:
            Dictionary with metrics: sharpe_ratio, win_rate, avg_pnl, avg_edge, total_pnl
        """
        if not trades:
            return {
                'sharpe_ratio': 0.0,
                'win_rate': 0.0,
                'avg_pnl': 0.0,
                'avg_edge': 0.0,
                'total_pnl': 0.0
            }

        # Filter settled trades only
        settled_trades = [t for t in trades if t.settled and t.pnl is not None]

        if not settled_trades:
            self.logger.warning("No settled trades found for metrics calculation")
            return {
                'sharpe_ratio': 0.0,
                'win_rate': 0.0,
                'avg_pnl': 0.0,
                'avg_edge': 0.0,
                'total_pnl': 0.0
            }

        # Calculate PnL metrics
        pnls = [t.pnl for t in settled_trades]
        avg_pnl = np.mean(pnls)
        std_pnl = np.std(pnls) if len(pnls) > 1 else 0.0

        # Calculate Sharpe ratio (annualized, assuming 5-min trades)
        # Sharpe = (mean_return / std_return) * sqrt(periods_per_year)
        # For 5-min intervals: 12 per hour * 24 hours * 365 days = 105,120 periods/year
        if std_pnl > 0:
            sharpe_ratio = (avg_pnl / std_pnl) * np.sqrt(105120)
        else:
            sharpe_ratio = 0.0

        # Calculate win rate
        wins = sum(1 for t in settled_trades if t.result == 'win')
        win_rate = wins / len(settled_trades) if settled_trades else 0.0

        # Calculate average edge
        edges = [t.edge_at_entry for t in settled_trades if t.edge_at_entry is not None]
        avg_edge = np.mean(edges) if edges else 0.0

        # Total PnL
        total_pnl = sum(pnls)

        return {
            'sharpe_ratio': sharpe_ratio,
            'win_rate': win_rate,
            'avg_pnl': avg_pnl,
            'avg_edge': avg_edge,
            'total_pnl': total_pnl
        }

    def _calculate_impact_score(
        self,
        sharpe_delta: float,
        win_rate_delta: float,
        avg_pnl_delta: float,
        edge_delta: float
    ) -> float:
        """Calculate composite impact score (0-100).

        Weights:
        - Sharpe ratio delta: 30%
        - Win rate delta: 30%
        - Avg PnL delta: 25%
        - Edge improvement: 15%

        Args:
            sharpe_delta: Change in Sharpe ratio
            win_rate_delta: Change in win rate (0-1 scale)
            avg_pnl_delta: Change in average PnL
            edge_delta: Change in average edge

        Returns:
            Composite score from 0-100
        """
        # Normalize each metric to 0-100 scale
        # Sharpe delta: -1 to +1 → 0 to 100
        sharpe_score = max(0, min(100, 50 + sharpe_delta * 50))

        # Win rate delta: -0.5 to +0.5 → 0 to 100
        win_rate_score = max(0, min(100, 50 + win_rate_delta * 100))

        # PnL delta: -10 to +10 → 0 to 100
        pnl_score = max(0, min(100, 50 + avg_pnl_delta * 5))

        # Edge delta: -0.2 to +0.2 → 0 to 100
        edge_score = max(0, min(100, 50 + edge_delta * 250))

        # Weighted average
        impact_score = (
            sharpe_score * 0.30 +
            win_rate_score * 0.30 +
            pnl_score * 0.25 +
            edge_score * 0.15
        )

        return impact_score

    def _store_impact(
        self,
        impact: ProposalImpact,
        metrics_before: Dict[str, float],
        metrics_after: Dict[str, float]
    ) -> None:
        """Store impact measurement in database.

        Args:
            impact: ProposalImpact object
            metrics_before: Metrics before proposal execution
            metrics_after: Metrics after proposal execution
        """
        from backend.db.utils import get_db_session

        try:
            with get_db_session() as db:
                # Update the StrategyProposal record with impact data
                proposal = db.query(StrategyProposal).filter(
                    StrategyProposal.id == impact.proposal_id
                ).first()

                if not proposal:
                    self.logger.error(f"Proposal {impact.proposal_id} not found in database")
                    return

                # Store impact as JSON
                impact_data = {
                    'sharpe_ratio_delta': impact.sharpe_ratio_delta,
                    'win_rate_delta': impact.win_rate_delta,
                    'avg_pnl_delta': impact.avg_pnl_delta,
                    'edge_improvement': impact.edge_improvement,
                    'total_trades_before': impact.total_trades_before,
                    'total_trades_after': impact.total_trades_after,
                    'measured_at': impact.measured_at.isoformat(),
                    'impact_score': impact.impact_score,
                    'metrics_before': metrics_before,
                    'metrics_after': metrics_after
                }

                proposal.impact_measured = impact_data

                self.logger.info(f"Stored impact measurement for proposal {impact.proposal_id}")
        except Exception as e:
            self.logger.error(f"Failed to store impact: {e}")

    def get_proposal_impact(self, proposal_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve stored impact measurement for a proposal.

        Args:
            proposal_id: Database ID of the proposal

        Returns:
            Impact data dictionary or None if not found
        """
        from backend.db.utils import get_db_session

        try:
            with get_db_session() as db:
                proposal = db.query(StrategyProposal).filter(
                    StrategyProposal.id == proposal_id
                ).first()

                if not proposal or not proposal.impact_measured:
                    return None

                return proposal.impact_measured
        except Exception:
            return None
