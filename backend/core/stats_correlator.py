"""Activity Timeline to Strategy Performance Stats Correlation Engine.

Correlates Activity Timeline events (trade executed, signal approved, proposal executed, etc.)
with Strategy Performance Stats (win rate, Sharpe ratio, PnL) to measure feature impact.

Supports:
- Feature 2: Task creation/execution → trade performance
- Feature 3: Debate results → signal accuracy
- Feature 4: Proposal approval/execution → strategy P&L
"""

from datetime import datetime, timedelta
from typing import Optional, List
from dataclasses import dataclass

from loguru import logger

from sqlalchemy import and_
from sqlalchemy.orm import Session

from backend.models.database import ActivityLog, Trade, Signal, StrategyProposal


@dataclass
class FeatureImpact:
    """Impact metrics for a specific feature."""
    feature_id: str
    feature_name: str
    event_count: int

    # Performance deltas (before vs after feature events)
    win_rate_before: float
    win_rate_after: float
    win_rate_delta: float

    sharpe_ratio_before: Optional[float]
    sharpe_ratio_after: Optional[float]
    sharpe_ratio_delta: Optional[float]

    pnl_before: float
    pnl_after: float
    pnl_delta: float

    # Statistical significance
    sample_size_before: int
    sample_size_after: int
    confidence_level: float  # 0.0-1.0


@dataclass
class TimelineCorrelation:
    """Correlation between activity timeline and performance metrics."""
    activity_id: int
    activity_timestamp: datetime
    activity_type: str
    strategy_name: str

    # Subsequent performance (within correlation window)
    trades_after: int
    wins_after: int
    win_rate_after: float
    pnl_after: float

    # Correlation strength
    correlation_score: float  # 0.0-1.0


class StatsCorrelator:
    """Correlate Activity Timeline events with Strategy Performance Stats."""

    def __init__(self, correlation_window_hours: int = 24):
        """
        Initialize the stats correlator.

        Args:
            correlation_window_hours: Time window after activity to measure impact (default 24h)
        """
        self.correlation_window_hours = correlation_window_hours

    def get_feature_impact(
        self,
        db: Session,
        feature_id: Optional[str] = None,
        date_range: Optional[tuple[datetime, datetime]] = None,
        metric_type: Optional[str] = None
    ) -> List[FeatureImpact]:
        """
        Calculate impact of Feature 2/3/4 changes on strategy performance.

        Args:
            db: Database session
            feature_id: Filter by feature ID ('feature_2', 'feature_3', 'feature_4')
            date_range: Optional (start_date, end_date) tuple
            metric_type: Filter by metric ('win_rate', 'sharpe_ratio', 'pnl')

        Returns:
            List of FeatureImpact objects showing before/after performance
        """
        impacts = []

        # Feature 2: Task creation/execution → trade performance
        if feature_id is None or feature_id == "feature_2":
            impact = self._calculate_feature_2_impact(db, date_range, metric_type)
            if impact:
                impacts.append(impact)

        # Feature 3: Debate results → signal accuracy
        if feature_id is None or feature_id == "feature_3":
            impact = self._calculate_feature_3_impact(db, date_range, metric_type)
            if impact:
                impacts.append(impact)

        # Feature 4: Proposal approval/execution → strategy P&L
        if feature_id is None or feature_id == "feature_4":
            impact = self._calculate_feature_4_impact(db, date_range, metric_type)
            if impact:
                impacts.append(impact)

        return impacts

    def _calculate_feature_2_impact(
        self,
        db: Session,
        date_range: Optional[tuple[datetime, datetime]],
        metric_type: Optional[str]
    ) -> Optional[FeatureImpact]:
        """Calculate Feature 2 (Activity Timeline) impact on trade performance."""
        try:
            # Get activity events (task creation/execution)
            query = db.query(ActivityLog)

            if date_range:
                start_date, end_date = date_range
                query = query.filter(
                    and_(
                        ActivityLog.timestamp >= start_date,
                        ActivityLog.timestamp <= end_date
                    )
                )

            activities = query.all()
            event_count = len(activities)

            if event_count == 0:
                return None

            # Calculate performance before first activity
            first_activity_time = min(a.timestamp for a in activities)
            before_trades = db.query(Trade).filter(
                Trade.timestamp < first_activity_time,
                Trade.settled
            ).all()

            wins_before = sum(1 for t in before_trades if t.result == "win")
            win_rate_before = wins_before / len(before_trades) if before_trades else 0.0
            pnl_before = sum(t.pnl or 0.0 for t in before_trades)

            # Calculate performance after activities
            last_activity_time = max(a.timestamp for a in activities)
            after_trades = db.query(Trade).filter(
                Trade.timestamp > last_activity_time,
                Trade.settled
            ).all()

            wins_after = sum(1 for t in after_trades if t.result == "win")
            win_rate_after = wins_after / len(after_trades) if after_trades else 0.0
            pnl_after = sum(t.pnl or 0.0 for t in after_trades)

            # Calculate Sharpe ratio (simplified: returns / std dev)
            sharpe_before = self._calculate_sharpe(before_trades)
            sharpe_after = self._calculate_sharpe(after_trades)

            return FeatureImpact(
                feature_id="feature_2",
                feature_name="Activity Timeline",
                event_count=event_count,
                win_rate_before=win_rate_before,
                win_rate_after=win_rate_after,
                win_rate_delta=win_rate_after - win_rate_before,
                sharpe_ratio_before=sharpe_before,
                sharpe_ratio_after=sharpe_after,
                sharpe_ratio_delta=sharpe_after - sharpe_before if sharpe_before and sharpe_after else None,
                pnl_before=pnl_before,
                pnl_after=pnl_after,
                pnl_delta=pnl_after - pnl_before,
                sample_size_before=len(before_trades),
                sample_size_after=len(after_trades),
                confidence_level=self._calculate_confidence(len(before_trades), len(after_trades))
            )
        except Exception as e:
            logger.error(f"Failed to calculate Feature 2 impact: {e}", exc_info=True)
            return None

    def _calculate_feature_3_impact(
        self,
        db: Session,
        date_range: Optional[tuple[datetime, datetime]],
        metric_type: Optional[str]
    ) -> Optional[FeatureImpact]:
        """Calculate Feature 3 (Debate Engine) impact on signal accuracy."""
        try:
            # Get debate-related activities (signals with high confidence from debate)
            query = db.query(ActivityLog).filter(
                ActivityLog.decision_type == "entry",
                ActivityLog.confidence_score >= 0.7  # High confidence from debate
            )

            if date_range:
                start_date, end_date = date_range
                query = query.filter(
                    and_(
                        ActivityLog.timestamp >= start_date,
                        ActivityLog.timestamp <= end_date
                    )
                )

            debate_activities = query.all()
            event_count = len(debate_activities)

            if event_count == 0:
                return None

            # Get signals before debate feature
            first_debate_time = min(a.timestamp for a in debate_activities)
            before_signals = db.query(Signal).filter(
                Signal.timestamp < first_debate_time,
                Signal.executed,
                Signal.outcome_correct.isnot(None)
            ).all()

            correct_before = sum(1 for s in before_signals if s.outcome_correct)
            win_rate_before = correct_before / len(before_signals) if before_signals else 0.0

            # Get signals after debate feature
            last_debate_time = max(a.timestamp for a in debate_activities)
            after_signals = db.query(Signal).filter(
                Signal.timestamp > last_debate_time,
                Signal.executed,
                Signal.outcome_correct.isnot(None)
            ).all()

            correct_after = sum(1 for s in after_signals if s.outcome_correct)
            win_rate_after = correct_after / len(after_signals) if after_signals else 0.0

            # Get corresponding trades for PnL
            before_trades = db.query(Trade).filter(
                Trade.timestamp < first_debate_time,
                Trade.settled
            ).all()

            after_trades = db.query(Trade).filter(
                Trade.timestamp > last_debate_time,
                Trade.settled
            ).all()

            pnl_before = sum(t.pnl or 0.0 for t in before_trades)
            pnl_after = sum(t.pnl or 0.0 for t in after_trades)

            sharpe_before = self._calculate_sharpe(before_trades)
            sharpe_after = self._calculate_sharpe(after_trades)

            return FeatureImpact(
                feature_id="feature_3",
                feature_name="Debate Engine",
                event_count=event_count,
                win_rate_before=win_rate_before,
                win_rate_after=win_rate_after,
                win_rate_delta=win_rate_after - win_rate_before,
                sharpe_ratio_before=sharpe_before,
                sharpe_ratio_after=sharpe_after,
                sharpe_ratio_delta=sharpe_after - sharpe_before if sharpe_before and sharpe_after else None,
                pnl_before=pnl_before,
                pnl_after=pnl_after,
                pnl_delta=pnl_after - pnl_before,
                sample_size_before=len(before_signals),
                sample_size_after=len(after_signals),
                confidence_level=self._calculate_confidence(len(before_signals), len(after_signals))
            )
        except Exception as e:
            logger.error(f"Failed to calculate Feature 3 impact: {e}", exc_info=True)
            return None

    def _calculate_feature_4_impact(
        self,
        db: Session,
        date_range: Optional[tuple[datetime, datetime]],
        metric_type: Optional[str]
    ) -> Optional[FeatureImpact]:
        """Calculate Feature 4 (Proposal System) impact on strategy P&L."""
        try:
            # Get approved and executed proposals
            query = db.query(StrategyProposal).filter(
                StrategyProposal.admin_decision == "approved",
                StrategyProposal.executed_at.isnot(None)
            )

            if date_range:
                start_date, end_date = date_range
                query = query.filter(
                    and_(
                        StrategyProposal.executed_at >= start_date,
                        StrategyProposal.executed_at <= end_date
                    )
                )

            proposals = query.all()
            event_count = len(proposals)

            if event_count == 0:
                return None

            # Calculate performance before first proposal
            first_proposal_time = min(p.executed_at for p in proposals if p.executed_at)
            before_trades = db.query(Trade).filter(
                Trade.timestamp < first_proposal_time,
                Trade.settled
            ).all()

            wins_before = sum(1 for t in before_trades if t.result == "win")
            win_rate_before = wins_before / len(before_trades) if before_trades else 0.0
            pnl_before = sum(t.pnl or 0.0 for t in before_trades)

            # Calculate performance after proposals
            last_proposal_time = max(p.executed_at for p in proposals if p.executed_at)
            after_trades = db.query(Trade).filter(
                Trade.timestamp > last_proposal_time,
                Trade.settled
            ).all()

            wins_after = sum(1 for t in after_trades if t.result == "win")
            win_rate_after = wins_after / len(after_trades) if after_trades else 0.0
            pnl_after = sum(t.pnl or 0.0 for t in after_trades)

            sharpe_before = self._calculate_sharpe(before_trades)
            sharpe_after = self._calculate_sharpe(after_trades)

            return FeatureImpact(
                feature_id="feature_4",
                feature_name="Proposal System",
                event_count=event_count,
                win_rate_before=win_rate_before,
                win_rate_after=win_rate_after,
                win_rate_delta=win_rate_after - win_rate_before,
                sharpe_ratio_before=sharpe_before,
                sharpe_ratio_after=sharpe_after,
                sharpe_ratio_delta=sharpe_after - sharpe_before if sharpe_before and sharpe_after else None,
                pnl_before=pnl_before,
                pnl_after=pnl_after,
                pnl_delta=pnl_after - pnl_before,
                sample_size_before=len(before_trades),
                sample_size_after=len(after_trades),
                confidence_level=self._calculate_confidence(len(before_trades), len(after_trades))
            )
        except Exception as e:
            logger.error(f"Failed to calculate Feature 4 impact: {e}", exc_info=True)
            return None

    def get_activity_correlations(
        self,
        db: Session,
        strategy_name: Optional[str] = None,
        limit: int = 100
    ) -> List[TimelineCorrelation]:
        """
        Get correlations between activity events and subsequent performance.

        Args:
            db: Database session
            strategy_name: Filter by strategy name
            limit: Maximum correlations to return

        Returns:
            List of TimelineCorrelation objects
        """
        correlations = []

        try:
            query = db.query(ActivityLog)

            if strategy_name:
                query = query.filter(ActivityLog.strategy_name == strategy_name)

            query = query.order_by(ActivityLog.timestamp.desc()).limit(limit)
            activities = query.all()

            for activity in activities:
                # Get trades within correlation window after this activity
                window_end = activity.timestamp + timedelta(hours=self.correlation_window_hours)

                trades_after = db.query(Trade).filter(
                    and_(
                        Trade.timestamp > activity.timestamp,
                        Trade.timestamp <= window_end,
                        Trade.settled
                    )
                ).all()

                if not trades_after:
                    continue

                wins_after = sum(1 for t in trades_after if t.result == "win")
                win_rate_after = wins_after / len(trades_after)
                pnl_after = sum(t.pnl or 0.0 for t in trades_after)

                # Calculate correlation score based on confidence and performance
                correlation_score = self._calculate_correlation_score(
                    activity.confidence_score,
                    win_rate_after,
                    len(trades_after)
                )

                correlations.append(TimelineCorrelation(
                    activity_id=activity.id,
                    activity_timestamp=activity.timestamp,
                    activity_type=activity.decision_type,
                    strategy_name=activity.strategy_name,
                    trades_after=len(trades_after),
                    wins_after=wins_after,
                    win_rate_after=win_rate_after,
                    pnl_after=pnl_after,
                    correlation_score=correlation_score
                ))

            return correlations
        except Exception as e:
            logger.error(f"Failed to get activity correlations: {e}", exc_info=True)
            return []

    def _calculate_sharpe(self, trades: List[Trade]) -> Optional[float]:
        """Calculate Sharpe ratio from trade returns."""
        if not trades or len(trades) < 2:
            return None

        returns = [t.pnl or 0.0 for t in trades]
        mean_return = sum(returns) / len(returns)

        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = variance ** 0.5

        if std_dev == 0:
            return None

        # Annualized Sharpe (assuming daily trades)
        sharpe = (mean_return / std_dev) * (252 ** 0.5)
        return sharpe

    def _calculate_confidence(self, sample_before: int, sample_after: int) -> float:
        """Calculate statistical confidence level based on sample sizes."""
        total_samples = sample_before + sample_after

        if total_samples < 10:
            return 0.3
        elif total_samples < 30:
            return 0.5
        elif total_samples < 100:
            return 0.7
        else:
            return 0.9

    def _calculate_correlation_score(
        self,
        confidence: float,
        win_rate: float,
        sample_size: int
    ) -> float:
        """Calculate correlation score between activity confidence and performance."""
        # Weight by confidence, win rate, and sample size
        confidence_weight = confidence
        performance_weight = win_rate
        sample_weight = min(sample_size / 10.0, 1.0)

        score = (confidence_weight * 0.4 + performance_weight * 0.4 + sample_weight * 0.2)
        return min(max(score, 0.0), 1.0)


# Global singleton instance
stats_correlator = StatsCorrelator()
