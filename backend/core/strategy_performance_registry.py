"""Strategy Performance Registry — centralized, up-to-date metrics per strategy.

Every settled trade updates the corresponding StrategyReport. The registry
maintains one report per strategy (live strategy name as key) and persists
snapshots to the database for historical analysis.

This is the source of truth for:
- Dashboard strategy performance cards
- Promotion/demotion decisions
- AGI improvement loop (trend analysis, parameter tuning)
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict

from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, Float, String, DateTime, UniqueConstraint

from backend.models.database import Base, SessionLocal

from loguru import logger

# ============================================================
# Database schema — StrategyPerformanceSnapshot
# ============================================================


class StrategyPerformanceSnapshot(Base):
    """Historical snapshot of a strategy's performance at a point in time.

    A new row is created after every settled trade (or every N trades to
    avoid write amplification). The latest row for each strategy is the
    current StrategyReport.
    """

    __tablename__ = "strategy_performance_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    strategy = Column(
        String, index=True, nullable=False
    )  # strategy name (from registry)
    recorded_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Trade count and win/loss
    total_trades = Column(Integer, default=0, nullable=False)
    wins = Column(Integer, default=0, nullable=False)
    losses = Column(Integer, default=0, nullable=False)
    win_rate = Column(Float, default=0.0, nullable=False)  # wins / total_trades

    # P&L
    total_pnl = Column(Float, default=0.0, nullable=False)
    gross_profit = Column(
        Float, default=0.0, nullable=False
    )  # sum of winning trade P&L
    gross_loss = Column(
        Float, default=0.0, nullable=False
    )  # sum of losing trade P&L (negative)
    profit_factor = Column(
        Float, default=0.0
    )  # gross_profit / abs(gross_loss), 0 if no losses

    # Risk-adjusted
    sharpe_ratio = Column(Float, default=0.0)
    max_drawdown = Column(
        Float, default=0.0
    )  # max peak-to-trough equity curve drawdown (0–1)
    consecutive_losses = Column(Integer, default=0)  # current losing streak
    max_consecutive_losses = Column(Integer, default=0)  # worst streak ever

    # Calibration
    brier_score = Column(Float, default=1.0)  # probability calibration (lower = better)
    psi_score = Column(
        Float, default=0.0
    )  # population stability index (drift detection)

    # Edge quality
    avg_edge_at_entry = Column(Float, default=0.0)  # mean(edge) over trades
    avg_edge_realized = Column(
        Float, default=0.0
    )  # mean(edge * outcome) — realized vs predicted

    # Status
    is_profitable = Column(
        Integer, default=0
    )  # 1 if meets promotion thresholds, 0 otherwise
    promotion_blocked_reason = Column(String, nullable=True)  # if not profitable, why

    __table_args__ = (
        UniqueConstraint("strategy", "recorded_at", name="uq_strategy_timestamp"),
    )

    def to_report(self) -> StrategyReport:
        """Convert DB row → domain dataclass."""
        return StrategyReport(
            strategy_name=self.strategy,
            total_trades=self.total_trades,
            wins=self.wins,
            losses=self.losses,
            win_rate=self.win_rate,
            total_pnl=self.total_pnl,
            gross_profit=self.gross_profit,
            gross_loss=self.gross_loss,
            profit_factor=self.profit_factor,
            sharpe_ratio=self.sharpe_ratio,
            max_drawdown=self.max_drawdown,
            consecutive_losses=self.consecutive_losses,
            max_consecutive_losses=self.max_consecutive_losses,
            brier_score=self.brier_score,
            psi_score=self.psi_score,
            avg_edge_at_entry=self.avg_edge_at_entry,
            avg_edge_realized=self.avg_edge_realized,
            is_profitable=bool(self.is_profitable),
            promotion_blocked_reason=self.promotion_blocked_reason,
            report_generated_at=(
                self.recorded_at.replace(tzinfo=timezone.utc)
                if self.recorded_at.tzinfo is None
                else self.recorded_at
            ),
            report_covers_days=0,  # derived — not stored
            promoted_at=None,
            demoted_at=None,
            demotion_reason=None,
        )


# ============================================================
# Domain dataclass — in-memory representation
# ============================================================


@dataclass
class StrategyReport:
    """Snapshot of a strategy's current performance.

    Updated after every settled trade by the registry. Used by promoters,
    allocators, dashboard, and AGI improvement engine.
    """

    strategy_name: str

    # Trade count and win/loss
    total_trades: int
    wins: int
    losses: int
    win_rate: float  # wins / total_trades

    # P&L
    total_pnl: float
    gross_profit: float
    gross_loss: float
    profit_factor: float  # gross_profit / abs(gross_loss)

    # Risk-adjusted
    sharpe_ratio: float
    max_drawdown: float  # 0–1
    consecutive_losses: int
    max_consecutive_losses: int

    # Calibration
    brier_score: float  # 0–1, lower is better
    psi_score: float  # distribution drift (0–1 typical)

    # Edge quality
    avg_edge_at_entry: float  # mean predicted edge
    avg_edge_realized: float  # mean outcome-weighted edge

    # Verdict
    is_profitable: bool
    promotion_blocked_reason: Optional[str] = None

    # Metadata
    report_generated_at: datetime = None
    report_covers_days: int = 0  # time window span of underlying data
    promoted_at: Optional[datetime] = None
    demoted_at: Optional[datetime] = None
    demotion_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.report_generated_at:
            d["report_generated_at"] = self.report_generated_at.isoformat()
        if self.promoted_at:
            d["promoted_at"] = self.promoted_at.isoformat()
        if self.demoted_at:
            d["demoted_at"] = self.demoted_at.isoformat()
        return d


# ============================================================
# Registry — singleton accessor to latest reports
# ============================================================


class StrategyPerformanceRegistry:
    """Global registry caching the latest StrategyReport per strategy.

    Thread-safe; updates via `update_from_settlement()` after each trade
    settlement. Persists every update to `StrategyPerformanceSnapshot` table.
    """

    def __init__(self):
        self._reports: Dict[str, StrategyReport] = {}  # strategy_name → latest report
        self._lock = None  # Optional asyncio.Lock if needed for async safety

    def get(self, strategy: str) -> Optional[StrategyReport]:
        """Return latest report for strategy, or None if no data yet."""
        return self._reports.get(strategy)

    def get_all(self) -> Dict[str, StrategyReport]:
        """Return all current reports (shallow copy)."""
        return dict(self._reports)

    def update_from_settlement(
        self,
        strategy: str,
        db: Optional[Session] = None,
    ) -> StrategyReport:
        """Recompute full report for strategy after a trade settles.

        Reads all settled trades for `strategy` from DB, recomputes all
        aggregates, updates in-memory cache, and optionally persists a
        snapshot row if `db` is provided.
        Skips wallet_import to exclude external/imported data from stats.
        """
        if strategy == "wallet_import":
            return self._reports.get(strategy, StrategyReport(strategy=strategy))

        from backend.models.database import Trade

        session = db or SessionLocal()
        try:
            # Fetch all settled trades for this strategy
            trades = (
                session.query(Trade)
                .filter_by(strategy=strategy)
                .filter(Trade.result.in_(["win", "loss"]))
                .order_by(Trade.settlement_time.asc())
                .all()
            )

            # Compute aggregates
            total = len(trades)
            wins = sum(1 for t in trades if t.result == "win")
            losses = total - wins
            win_rate = wins / total if total > 0 else 0.0

            pnls = [t.pnl for t in trades if t.pnl is not None]
            total_pnl = sum(pnls)
            gross_profit = sum(p for p in pnls if p > 0)
            gross_loss = sum(p for p in pnls if p < 0)
            profit_factor = (
                gross_profit / abs(gross_loss)
                if gross_loss < 0
                else (gross_profit if gross_profit > 0 else 0.0)
            )

            # E-123: Sharpe from outcomes — use len(pnls) not total for denominator
            if len(pnls) >= 2:
                n = len(pnls)
                mean = total_pnl / n
                variance = sum((p - mean) ** 2 for p in pnls) / (
                    n - 1
                )  # sample variance
                std = (variance**0.5) if variance > 0 else 1e-9
                sharpe = (mean / std) * (n**0.5)
            else:
                sharpe = 0.0

            # Max drawdown from equity curve
            peak = 0.0
            equity = 0.0
            max_dd = 0.0
            for p in pnls:
                equity += p
                if equity > peak:
                    peak = equity
                if peak > 0:
                    dd = (peak - equity) / peak
                    if dd > max_dd:
                        max_dd = dd

            # Consecutive losses (from most recent backwards)
            consec = 0
            max_consec = 0
            for t in reversed(trades):
                if t.result == "loss":
                    consec += 1
                    max_consec = max(max_consec, consec)
                else:
                    consec = 0

            from backend.core.strategy_health import StrategyHealthMonitor

            health_mon = StrategyHealthMonitor()
            outcomes = [
                type(
                    "Outcome",
                    (),
                    {
                        "model_probability": getattr(t, "model_probability", None),
                        "result": t.result,
                    },
                )()
                for t in trades
                if getattr(t, "model_probability", None) is not None
            ]
            brier = health_mon._brier_from_outcomes(outcomes) if outcomes else 1.0

            if len(trades) >= 60:
                import math

                recent = trades[-30:]
                previous = trades[-60:-30]
                r_wins = sum(1 for t in recent if t.result == "win")
                p_wins = sum(1 for t in previous if t.result == "win")
                r_wr = r_wins / len(recent)
                p_wr = p_wins / len(previous)
                eps = 1e-6
                r_wr = max(eps, min(1 - eps, r_wr))
                p_wr = max(eps, min(1 - eps, p_wr))
                psi = abs(
                    (r_wr - p_wr) * math.log(r_wr / p_wr)
                    + ((1 - r_wr) - (1 - p_wr)) * math.log((1 - r_wr) / (1 - p_wr))
                )
            else:
                psi = 0.0

            # Edge quality
            edges_entry = [getattr(t, "edge_at_entry", 0.0) or 0.0 for t in trades]
            avg_edge_entry = sum(edges_entry) / len(edges_entry) if edges_entry else 0.0
            edges_realized = [
                getattr(t, "edge_at_entry", 0.0) * (1.0 if t.result == "win" else -1.0)
                for t in trades
            ]
            avg_edge_realized = (
                sum(edges_realized) / len(edges_realized) if edges_realized else 0.0
            )

            # Promote verdict — use same thresholds as AutonomousPromoter
            PROMOTION_THRESHOLDS = {
                "min_paper_trades": 30,
                "min_win_rate": 0.52,
                "min_profit_factor": 1.3,
                "max_drawdown": 0.15,
                "min_brier_improvement": 0.0,
            }
            meets = (
                total >= PROMOTION_THRESHOLDS["min_paper_trades"]
                and win_rate >= PROMOTION_THRESHOLDS["min_win_rate"]
                and profit_factor >= PROMOTION_THRESHOLDS["min_profit_factor"]
                and max_dd <= PROMOTION_THRESHOLDS["max_drawdown"]
            )
            reason = None if meets else "below_promotion_thresholds"

            # Build report
            report = StrategyReport(
                strategy_name=strategy,
                total_trades=total,
                wins=wins,
                losses=losses,
                win_rate=win_rate,
                total_pnl=total_pnl,
                gross_profit=gross_profit,
                gross_loss=gross_loss,
                profit_factor=profit_factor,
                sharpe_ratio=sharpe,
                max_drawdown=max_dd,
                consecutive_losses=consec,
                max_consecutive_losses=max_consec,
                brier_score=brier,
                psi_score=psi,
                avg_edge_at_entry=avg_edge_entry,
                avg_edge_realized=avg_edge_realized,
                is_profitable=meets,
                promotion_blocked_reason=reason,
                report_generated_at=datetime.now(timezone.utc),
                report_covers_days=self._compute_coverage_days(strategy, db),
            )

            # Update cache
            self._reports[strategy] = report

            # Persist snapshot if DB session provided
            if db is not None:
                snapshot = StrategyPerformanceSnapshot(
                    strategy=strategy,
                    total_trades=total,
                    wins=wins,
                    losses=losses,
                    win_rate=win_rate,
                    total_pnl=total_pnl,
                    gross_profit=gross_profit,
                    gross_loss=gross_loss,
                    profit_factor=profit_factor,
                    sharpe_ratio=sharpe,
                    max_drawdown=max_dd,
                    consecutive_losses=consec,
                    max_consecutive_losses=max_consec,
                    brier_score=brier,
                    psi_score=psi,
                    avg_edge_at_entry=avg_edge_entry,
                    avg_edge_realized=avg_edge_realized,
                    is_profitable=int(meets),
                    promotion_blocked_reason=reason,
                )
                db.add(snapshot)
                db.commit()

            return report

        finally:
            if db is None:
                session.close()

    def _compute_coverage_days(self, strategy: str, db) -> int:
        from backend.models.database import Trade

        session = db or SessionLocal()
        try:
            first_trade = (
                session.query(Trade.timestamp)
                .filter(Trade.strategy == strategy)
                .order_by(Trade.timestamp.asc())
                .first()
            )
            last_trade = (
                session.query(Trade.timestamp)
                .filter(Trade.strategy == strategy)
                .order_by(Trade.timestamp.desc())
                .first()
            )
            if first_trade and last_trade and first_trade[0] and last_trade[0]:
                return max(1, (last_trade[0] - first_trade[0]).days)
        except Exception:
            logger.exception(
                "[StrategyPerformanceRegistry] Failed to compute coverage days for '%s'",
                strategy,
            )
            return 0
        finally:
            if db is None:
                session.close()


# Global singleton — import and use everywhere
strategy_performance_registry = StrategyPerformanceRegistry()
