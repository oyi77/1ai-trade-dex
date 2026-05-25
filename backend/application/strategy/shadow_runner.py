"""Persistent ShadowRunner — DB-backed shadow trade tracking for strategy validation.

This module provides a database-backed implementation of ShadowRunner that persists
shadow trades across process restarts, enabling long-running strategy validation
and performance tracking.

The in-memory ShadowRunner from backend.core.shadow_mode remains available for
backward compatibility and is marked as deprecated.
"""

from datetime import datetime, timezone
import json
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.database import SessionLocal, ShadowTrade
from backend.core.shadow_mode import ShadowPerformance  # Reuse existing dataclass
from backend.domain.evolution.shadow_metrics import compute_shadow_metrics

from loguru import logger


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
                logger.exception("Failed to close database session")
                pass  # Ignore errors when closing
            self.db = None
            self.owns_db = False

    def record_signal(
        self,
        # New CLOB-style API (primary)
        strategy_name: Optional[str] = None,
        token_id: Optional[str] = None,
        side: Optional[str] = None,
        price: Optional[float] = None,
        size_usd: Optional[float] = None,
        mode: str = "paper",
        genome_id: Optional[str] = None,
        direction: Optional[str] = None,
        entry_price: Optional[float] = None,
        market_id: Optional[str] = None,
        # Legacy API aliases (for backward compat with existing tests/code)
        strategy: Optional[str] = None,
        market_ticker: Optional[str] = None,
        size: Optional[float] = None,
        model_prob: Optional[float] = None,
        predicted_outcome: Optional[float] = None,
        # Catch-all for any other legacy kwargs
        **kwargs,
    ) -> "ShadowTrade":
        """Record a shadow trade signal (no real execution) — persists to database.

        Args:
            strategy_name: strategy identifier (e.g. 'cex_pm_leadlag')
            token_id: CLOB token ID
            side: 'BUY' or 'SELL'
            price: entry price
            size_usd: position size in USD
            mode: 'paper' or 'testnet' (for AGI health check filtering)
            genome_id: optional AGI genome ID
            direction: override direction ('up'/'down') if known
            entry_price: override entry price if known
            market_id: override market ID if known
        """
        # Resolve legacy aliases for backward compatibility with existing tests
        resolved_strategy = strategy_name or strategy or "unknown"
        resolved_token_id = token_id or market_id or market_ticker or "unknown"
        resolved_direction = direction or (side.lower() if side else "buy")
        resolved_entry_price = entry_price or price or 0.0
        resolved_size_usd = size_usd if size_usd is not None else (size or 0.0)

        db = self._get_db()
        try:
            # Store legacy fields in metadata_json for property access
            meta = {}
            if model_prob is not None:
                meta["model_probability"] = model_prob
            if predicted_outcome is not None:
                meta["predicted_outcome"] = predicted_outcome
            metadata_json = json.dumps(meta) if meta else None

            trade = ShadowTrade(
                strategy_name=resolved_strategy,
                market_id=resolved_token_id,
                target_price=0.0,
                direction=resolved_direction,
                entry_price=resolved_entry_price,
                size_usd=resolved_size_usd,
                entry_signal="",
                exit_signal="",
                stage="ACTIVE",
                genome_id=genome_id,
                metadata_json=metadata_json,
            )
            db.add(trade)
            db.commit()
            db.refresh(trade)

            logger.info(
                "Shadow signal recorded: strategy=%s token=%s side=%s price=%.4f size_usd=%.2f mode=%s genome=%s",
                resolved_strategy,
                resolved_token_id,
                side,
                resolved_entry_price,
                resolved_size_usd,
                mode,
                genome_id or "none",
            )
            return trade
        except Exception as e:
            logger.error(f"Failed to record shadow signal: {e}")
            db.rollback()
            raise
        finally:
            self._close_db()

    def settle(
        self,
        # New API
        market_id: Optional[str] = None,
        outcome: Optional[str] = None,
        pnl_usd: Optional[float] = None,
        # Legacy API aliases
        market_ticker: Optional[str] = None,
        settlement_value: Optional[float] = None,
        actual_outcome: Optional[float] = None,
        **kwargs,
    ) -> None:
        """Settle all ACTIVE shadow trades for this market.

        Args:
            market_id: market identifier (token_id)
            outcome: 'win' or 'loss'
            pnl_usd: optional P&L override (computed from settlement helpers if not provided)
        """
        # Resolve legacy aliases
        resolved_market_id = market_id or market_ticker
        if settlement_value is not None:
            resolved_outcome = "win" if settlement_value == 1.0 else "loss"
        elif outcome is not None:
            resolved_outcome = outcome
        else:
            resolved_outcome = "win"  # default assumption when settle called without outcome
            logger.warning("[ShadowRunner.settle] No outcome specified — defaulting to 'win'")

        from backend.core.settlement.settlement_helpers import calculate_pnl

        db = self._get_db()
        try:
            unsettled_trades = (
                db.query(ShadowTrade)
                .filter(
                    ShadowTrade.market_id == resolved_market_id,
                    ShadowTrade.stage == "ACTIVE",
                )
                .all()
            )

            for trade in unsettled_trades:
                trade.stage = "SETTLED"
                trade.outcome = resolved_outcome

                # Capture legacy fields in metadata_json for property access
                try:
                    meta = json.loads(trade.metadata_json) if trade.metadata_json else {}
                    if actual_outcome is not None:
                        meta["actual_outcome"] = actual_outcome
                    predicted = meta.get("predicted_outcome")
                    if predicted is not None and actual_outcome is not None:
                        meta["accuracy_score"] = abs(predicted - actual_outcome)
                    trade.metadata_json = json.dumps(meta)
                except Exception as e:
                    logger.exception(f"Failed to update metadata_json during settle for {trade.market_id}")

                # Use real settlement helpers for PnL calculation (mirrors live trade)
                settlement_value = 1.0 if resolved_outcome == "win" else 0.0
                try:
                    trade.pnl_usd = calculate_pnl(trade, settlement_value)
                except Exception:
                    # Fallback to simplified PnL if settlement helpers fail
                    if resolved_outcome == "win":
                        trade.pnl_usd = trade.size_usd * (1.0 - trade.entry_price)
                    else:
                        trade.pnl_usd = -trade.size_usd * trade.entry_price

                logger.info(
                    "Shadow trade settled: market=%s direction=%s outcome=%s pnl_usd=%.4f",
                    trade.market_id,
                    trade.direction,
                    trade.outcome,
                    trade.pnl_usd,
                )

            db.commit()
        finally:
            self._close_db()

    @staticmethod
    def _calculate_genome_metrics(settled_trades: list[ShadowTrade]) -> dict:
        """Calculate fitness-facing metrics from settled shadow trades."""
        return compute_shadow_metrics(settled_trades)

    def get_genome_metrics(self, genome_id: str) -> dict:
        """Get per-genome metrics derived from settled shadow trades."""
        db = self._get_db()
        try:
            settled_trades = (
                db.query(ShadowTrade)
                .filter(
                    ShadowTrade.genome_id == genome_id,
                    ShadowTrade.stage == "SETTLED",
                )
                .order_by(ShadowTrade.created_at.asc())
                .all()
            )
            return self._calculate_genome_metrics(settled_trades)
        finally:
            self._close_db()

    def get_performance(self, genome_id: Optional[str] = None) -> ShadowPerformance:
        """Get performance metrics for a genome or all trades."""
        db = self._get_db()
        try:
            query = db.query(ShadowTrade)
            if genome_id is not None:
                query = query.filter(ShadowTrade.genome_id == genome_id)

            trades = query.all()
            settled_trades = [t for t in trades if t.settled]

            total_pnl = sum(t.pnl or 0 for t in settled_trades)
            win_rate = (
                len([t for t in settled_trades if t.pnl and t.pnl > 0])
                / len(settled_trades)
                if settled_trades
                else 0.0
            )

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
                if t.strategy_name:
                    strategy_breakdown[t.strategy_name] = strategy_breakdown.get(
                        t.strategy_name, 0.0
                    ) + (t.pnl_usd or 0.0)

            return ShadowPerformance(
                total_trades=len(trades),
                settled_trades=len(settled_trades),
                total_pnl=total_pnl,
                win_rate=win_rate,
                avg_edge=avg_edge,
                strategy_breakdown=strategy_breakdown,
            )
        finally:
            self._close_db()

    def evaluate_promotion_eligibility(self, genome_id: str) -> dict:
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
                text(
                    """
                SELECT
                    COUNT(*) as total_trades,
                    MIN(created_at) as first_trade,
                    MAX(julianday('now') - julianday(created_at)) as days_active
                FROM shadow_trade
                WHERE genome_id = :genome_id AND created_at >= datetime('now', '-30 days')
                """
                ),
                {"genome_id": genome_id},
            )

            row = result.fetchone()

            if not row or row.total_trades == 0:
                return {
                    "total_trades": 0,
                    "accuracy": 0.0,
                    "days_active": 0.0,
                    "eligible": False,
                    "reason": "No trades in the last 30 days",
                }

            total_trades = row.total_trades
            # Compute accuracy from settled trades with predicted/actual outcome
            settled_with_scores = db.query(ShadowTrade).filter(
                ShadowTrade.genome_id == genome_id,
                ShadowTrade.stage == "SETTLED",
            ).all()
            scored = [t for t in settled_with_scores if t.accuracy_score is not None]
            accurate = sum(1 for t in scored if t.accuracy_score < 0.2)
            accuracy = accurate / total_trades if total_trades > 0 else 0.0
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
                "reason": reason,
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
            logger.exception("Transaction failed, rolling back")
            db.rollback()
            raise
        finally:
            self._close_db()
