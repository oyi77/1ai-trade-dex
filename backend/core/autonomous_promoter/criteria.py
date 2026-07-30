"""CriteriaMixin — property-based thresholds and criteria methods for AutonomousPromoter."""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.database import Trade
from backend.models.kg_models import ExperimentRecord

from loguru import logger


class CriteriaMixin:
    """Mixin providing all promotion/demotion criteria and threshold properties."""

    @property
    def _s(self):
        from backend.config import settings as _s

        return _s

    @property
    def MIN_TRADES_SHADOW(self):
        return self._s.AGI_PROMOTER_SHADOW_MIN_TRADES

    @property
    def MIN_DAYS_SHADOW(self):
        return self._s.AGI_PROMOTER_SHADOW_MIN_DAYS

    @property
    def MIN_WIN_RATE_SHADOW(self):
        return self._s.AGI_PROMOTER_SHADOW_MIN_WIN_RATE

    @property
    def MAX_DRAWDOWN_SHADOW(self):
        return self._s.AGI_PROMOTER_SHADOW_MAX_DRAWDOWN

    @property
    def MIN_TRADES_PAPER(self):
        return self._s.AGI_PROMOTER_PAPER_MIN_TRADES

    @property
    def MIN_DAYS_PAPER(self):
        return self._s.AGI_PROMOTER_PAPER_MIN_DAYS

    @property
    def MIN_WIN_RATE_PAPER(self):
        return self._s.AGI_PROMOTER_PAPER_MIN_WIN_RATE

    @property
    def MIN_SHARPE_PAPER(self):
        return self._s.AGI_PROMOTER_PAPER_MIN_SHARPE

    @property
    def MAX_DRAWDOWN_PAPER(self):
        return self._s.AGI_PROMOTER_PAPER_MAX_DRAWDOWN

    # Kill thresholds (applied to any mode)
    KILL_WIN_RATE = settings.KILL_WIN_RATE
    KILL_SHARPE = settings.KILL_SHARPE
    KILL_DRAWDOWN = settings.KILL_DRAWDOWN
    MIN_WARMUP_TRADES = settings.MIN_WARMUP_TRADES
    DEGRADATION_WR_THRESHOLD = settings.DEGRADATION_WR_THRESHOLD
    DEGRADATION_SHARPE_THRESHOLD = settings.DEGRADATION_SHARPE_THRESHOLD
    MAX_DEGRADATIONS_BEFORE_REVIEW = settings.MAX_DEGRADATIONS_BEFORE_REVIEW

    def _check_paper_criteria_from_health(
        self, exp: ExperimentRecord, health: dict, db=None
    ) -> tuple[bool, list[str]]:
        """Evaluate paper→live promotion using current health metrics.

        Includes walk-forward validation: checks last 20 trades separately
        to ensure the edge hasn't decayed (strategy not coasting on old wins).
        """
        reasons = []
        trades = health.get("total_trades", 0)
        win_rate = health.get("win_rate", 0.0)
        sharpe = health.get("sharpe", 0.0)
        max_dd = health.get("max_drawdown", 0.0)

        if trades < self.MIN_TRADES_PAPER:
            reasons.append(f"trades {trades} < {self.MIN_TRADES_PAPER}")
        if win_rate < self.MIN_WIN_RATE_PAPER:
            reasons.append(f"win_rate {win_rate:.1%} < {self.MIN_WIN_RATE_PAPER:.1%}")
        if sharpe < self.MIN_SHARPE_PAPER:
            reasons.append(f"sharpe {sharpe:.2f} < {self.MIN_SHARPE_PAPER:.2f}")
        if max_dd > self.MAX_DRAWDOWN_PAPER:
            reasons.append(f"dd {max_dd:.1%} > {self.MAX_DRAWDOWN_PAPER:.1%}")

        # Age check (paper running time)
        ref_time = exp.promoted_at or exp.created_at
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - ref_time).days
        if age_days < self.MIN_DAYS_PAPER:
            reasons.append(f"paper age {age_days}d < {self.MIN_DAYS_PAPER}d")

        # Walk-forward validation: check last 20 trades separately
        if db is not None and trades >= 10:
            try:
                strategy_name = exp.strategy_name or exp.name
                from sqlalchemy import text as _sql_text

                recent = db.execute(
                    _sql_text(
                        "SELECT result FROM trades "
                        "WHERE strategy = :strat AND trading_mode = 'paper' "
                        "AND settled = 1 "
                        "ORDER BY id DESC LIMIT 20"
                    ),
                    {"strat": strategy_name},
                ).fetchall()

                if len(recent) >= 10:
                    recent_wins = sum(
                        1 for r in recent
                        if (r[0] or "").lower() in ("win", "won", "1", "true")
                    )
                    recent_wr = recent_wins / len(recent)
                    if recent_wr < self.MIN_WIN_RATE_PAPER:
                        reasons.append(
                            f"walk-forward: recent WR {recent_wr:.1%} < "
                            f"{self.MIN_WIN_RATE_PAPER:.1%} (last {len(recent)} trades)"
                        )
            except Exception as exc:
                logger.debug(f"[AutonomousPromoter] Walk-forward check failed: {exc}")

        return (len(reasons) == 0, reasons)

    def _check_shadow_criteria(
        self, exp: ExperimentRecord, db: Session
    ) -> tuple[bool, list[str]]:
        """Check if experiment meets shadow→paper criteria."""
        reasons = []
        trades = exp.shadow_trades or 0
        win_rate = exp.shadow_win_rate or 0.0

        if trades < self.MIN_TRADES_SHADOW:
            reasons.append(f"trades {trades} < {self.MIN_TRADES_SHADOW}")
        if exp.shadow_win_rate < self.MIN_WIN_RATE_SHADOW:
            reasons.append(f"win_rate {win_rate:.1%} < {self.MIN_WIN_RATE_SHADOW:.1%}")

        # Age check (handle naive/aware)
        created_at = exp.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created_at).days
        if age_days < self.MIN_DAYS_SHADOW:
            reasons.append(f"age {age_days}d < {self.MIN_DAYS_SHADOW}d")

        drawdown = self._compute_shadow_drawdown(exp, db)
        if drawdown > self.MAX_DRAWDOWN_SHADOW:
            reasons.append(f"drawdown {drawdown:.1%} > {self.MAX_DRAWDOWN_SHADOW:.1%}")

        return (len(reasons) == 0, reasons)

    def _compute_shadow_drawdown(self, exp: ExperimentRecord, db: Session) -> float:
        try:
            trades = (
                db.query(Trade)
                .filter(
                    Trade.strategy == exp.strategy_name,
                    Trade.trading_mode == "paper",
                    Trade.settled.is_(True),
                    Trade.result.in_(["win", "loss"]),
                )
                .order_by(Trade.timestamp.asc())
                .all()
            )
            if not trades:
                return 0.0
            peak = 0.0
            cumulative = 0.0
            max_dd = 0.0
            for t in trades:
                cumulative += t.pnl or 0.0
                if cumulative > peak:
                    peak = cumulative
                dd = (peak - cumulative) / peak if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd
            return max_dd
        except Exception:
            logger.exception(
                f"[AutonomousPromoter] Failed to compute shadow drawdown for '{exp.strategy_name}'"
            )
            return 0.0

    def _check_paper_criteria(self, exp: ExperimentRecord) -> tuple[bool, list[str]]:
        reasons = []
        trades = exp.shadow_trades or 0
        win_rate = exp.shadow_win_rate or 0.0

        if trades < self.MIN_TRADES_PAPER:
            reasons.append(f"trades {trades} < {self.MIN_TRADES_PAPER}")
        if win_rate < self.MIN_WIN_RATE_PAPER:
            reasons.append(f"win_rate {win_rate:.1%} < {self.MIN_WIN_RATE_PAPER:.1%}")

        ref_time = exp.promoted_at or exp.created_at
        if ref_time is None:
            reasons.append("no reference time for paper age check")
        else:
            if ref_time.tzinfo is None:
                ref_time = ref_time.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - ref_time).days
            if age_days < self.MIN_DAYS_PAPER:
                reasons.append(f"paper age {age_days}d < {self.MIN_DAYS_PAPER}d")

        return (len(reasons) == 0, reasons)

    def _get_paper_trades(self, exp: ExperimentRecord) -> int:
        return exp.shadow_trades or 0  # Stub

    def _get_paper_win_rate(self, exp: ExperimentRecord) -> float:
        return exp.shadow_win_rate or 0.0  # Stub

    def _should_kill(self, exp: ExperimentRecord) -> bool:
        """Return True if experiment is catastrophically bad and should be retired."""
        trades = exp.shadow_trades or 0
        if trades < self.MIN_WARMUP_TRADES:
            return False
        win_rate = exp.shadow_win_rate or 0.0
        if win_rate < self.KILL_WIN_RATE:
            return True
        # Additional kill checks would require outcome metrics (sharpe, drawdown)
        return False
