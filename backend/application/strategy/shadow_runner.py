"""Persistent ShadowRunner — DB-backed shadow trade tracking for strategy validation.

This module provides a database-backed implementation of ShadowRunner that persists
shadow trades across process restarts, enabling long-running strategy validation
and performance tracking.

The in-memory ShadowRunner from backend.core.shadow_mode remains available for
backward compatibility and is marked as deprecated.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.database import SessionLocal, ShadowTrade
from backend.core.shadow_mode import ShadowPerformance  # Reuse existing dataclass

logger = logging.getLogger("trading_bot.shadow")


class DBSessionShadowRunner:
    """Persistent ShadowRunner using SQLAlchemy database backend."""

    def __init__(self, db: Optional[Session] = None):
        """Initialize ShadowRunner with optional database session.

        Args:
            db: SQLAlchemy session (if None, creates a new one per operation)
        """
        self.db = db
        self.owns_db = False

    def _get_db(self) -> Session:
        """Get database session, creating one if needed."""
        if self.db is None:
            self.db = SessionLocal()
            self.owns_db = True
        return self.db

    def _close_db(self):
        """Close database session if we own it."""
        if self.owns_db and self.db is not None:
            try:
                self.db.close()
            except Exception:
                pass  # Ignore errors when closing
            self.db = None
            self.owns_db = False

    def record_signal(
        self,
        market_ticker: str,
        direction: str,
        entry_price: float,
        size: float,
        model_prob: float,
        strategy: str,
        genome_id: Optional[int] = None,
        predicted_outcome: Optional[float] = None,
    ) -> ShadowTrade:
        """Record a shadow trade (no execution) — persists to database."""
        db = self._get_db()
        try:
            trade = ShadowTrade(
                market_ticker=market_ticker,
                direction=direction,
                entry_price=entry_price,
                size=size,
                model_probability=model_prob,
                timestamp=datetime.now(timezone.utc),
                strategy=strategy,
                settled=False,
                settlement_value=None,
                pnl=None,
                accuracy_score=None,
                genome_id=genome_id,
                predicted_outcome=predicted_outcome,
                actual_outcome=None,
            )
            db.add(trade)
            db.commit()
            db.refresh(trade)

            logger.info(
                "Shadow trade recorded: %s %s @ %.4f size=%.2f strategy=%s genome=%s",
                direction,
                market_ticker,
                entry_price,
                size,
                strategy,
                genome_id or "none",
            )
            return trade
        finally:
            self._close_db()

    def settle(self, market_ticker: str, settlement_value: float, actual_outcome: Optional[float] = None) -> None:
        """Settle all unsettled shadow trades for this ticker, calculating P&L and accuracy."""
        db = self._get_db()
        try:
            # Find unsettled trades for this ticker
            unsettled_trades = (
                db.query(ShadowTrade)
                .filter(
                    ShadowTrade.market_ticker == market_ticker,
                    ShadowTrade.settled == False
                )
                .all()
            )

            for trade in unsettled_trades:
                trade.settlement_value = settlement_value
                trade.settled = True

                # Calculate P&L
                direction_won = (
                    (trade.direction == "up" and settlement_value == 1.0)
                    or (trade.direction == "down" and settlement_value == 0.0)
                )
                if direction_won:
                    trade.pnl = (1.0 - trade.entry_price) * trade.size
                else:
                    trade.pnl = -trade.entry_price * trade.size

                # Calculate accuracy score if we have predicted and actual outcomes
                if trade.predicted_outcome is not None and actual_outcome is not None:
                    trade.accuracy_score = abs(trade.predicted_outcome - actual_outcome)
                    trade.actual_outcome = actual_outcome

                logger.info(
                    "Shadow trade settled: %s %s pnl=%.4f accuracy=%.4f",
                    trade.market_ticker,
                    trade.direction,
                    trade.pnl,
                    trade.accuracy_score or 0.0,
                )

            db.commit()
        finally:
            self._close_db()

    def get_performance(self, genome_id: Optional[int] = None) -> ShadowPerformance:
        """Get performance metrics for a genome or all trades."""
        db = self._get_db()
        try:
            query = db.query(ShadowTrade)
            if genome_id is not None:
                query = query.filter(ShadowTrade.genome_id == genome_id)

            trades = query.all()
            settled_trades = [t for t in trades if t.settled]

            total_pnl = sum(t.pnl or 0 for t in settled_trades)
            win_rate = len([t for t in settled_trades if t.pnl and t.pnl > 0]) / len(settled_trades) if settled_trades else 0.0

            # Calculate average edge: model_probability - entry_price
            edges = []
            for t in settled_trades:
                if t.model_probability is not None and t.entry_price is not None:
                    edge = t.model_probability - t.entry_price
                    edges.append(edge)
            avg_edge = sum(edges) / len(edges) if edges else 0.0

            # Strategy breakdown
            strategy_breakdown = {}
            for t in settled_trades:
                if t.strategy:
                    strategy_breakdown[t.strategy] = strategy_breakdown.get(t.strategy, 0.0) + (t.pnl or 0.0)

            return ShadowPerformance(
                total_trades=len(trades),
                settled_trades=len(settled_trades),
                total_pnl=total_pnl,
                win_rate=win_rate,
                avg_edge=avg_edge,
                strategy_breakdown=strategy_breakdown
            )
        finally:
            self._close_db()

    def evaluate_promotion_eligibility(self, genome_id: int) -> dict:
        """Evaluate if a genome is eligible for promotion from SHADOW to PAPER.

        Promotion criteria:
        - At least 1 day of trading activity
        - Accuracy >= 60% (predicted within 0.2 of actual outcome)
        - Only considers trades from the last 30 days

        Returns structured result with eligibility decision and metrics.
        """
        from sqlalchemy import text

        db = self._get_db()
        try:
            # Query for promotion eligibility metrics
            result = db.execute(
                text("""
                SELECT
                    COUNT(*) as total_trades,
                    MIN(timestamp) as first_trade,
                    AVG(CASE WHEN ABS(predicted_outcome - actual_outcome) < 0.2 THEN 1.0 ELSE 0.0 END) as accuracy,
                    MAX(julianday('now') - julianday(timestamp)) as days_active
                FROM shadow_trade
                WHERE genome_id = :genome_id AND timestamp >= datetime('now', '-30 days')
                """),
                {"genome_id": genome_id}
            )

            row = result.fetchone()

            if not row or row.total_trades == 0:
                return {
                    "total_trades": 0,
                    "accuracy": 0.0,
                    "days_active": 0.0,
                    "eligible": False,
                    "reason": "No trades in the last 30 days"
                }

            total_trades = row.total_trades
            accuracy = row.accuracy if row.accuracy is not None else 0.0
            days_active = row.days_active if row.days_active is not None else 0.0

            # Promotion gate: days_active >= 1 AND accuracy >= 0.60
            eligible = days_active >= 1 and accuracy >= 0.60

            reason = "Eligible for promotion"
            if days_active < 1:
                reason = "Less than 1 day of trading activity"
            elif accuracy < 0.60:
                reason = "Accuracy below 60% threshold"

            return {
                "total_trades": total_trades,
                "accuracy": accuracy,
                "days_active": days_active,
                "eligible": eligible,
                "reason": reason
            }
        finally:
            self._close_db()

    def compare_with_live(self, live_pnl: float) -> dict:
        """Compare shadow vs live performance."""
        perf = self.get_performance()
        shadow_pnl = perf.total_pnl
        return {
            "shadow_pnl": shadow_pnl,
            "live_pnl": live_pnl,
            "difference": shadow_pnl - live_pnl,
            "shadow_better": shadow_pnl > live_pnl,
        }

    def get_trades_count(self) -> int:
        """Get total number of shadow trades in database."""
        db = self._get_db()
        try:
            return db.query(ShadowTrade).count()
        finally:
            self._close_db()

    def clear_all_trades(self):
        """Clear all shadow trades — for testing only."""
        db = self._get_db()
        try:
            db.query(ShadowTrade).delete()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            self._close_db()
