"""
Strategy Health Monitor — kill-switch, PSI drift detection, warm-up guard.

Called by online_learner after each trade settlement and by scheduler every cycle.
"""

import json
import math
from datetime import datetime, timezone
from typing import Dict, Any
from sqlalchemy.orm import Session

from loguru import logger

from backend.config import settings
from backend.models.outcome_tables import StrategyOutcome, StrategyHealthRecord


def _now_utc():
    return datetime.now(timezone.utc)


def disable_for_rehab(config) -> None:
    """Disable strategy for rehabilitation: keep enabled in paper mode.

    Instead of setting enabled=False (which prevents scheduler from running),
    keeps enabled=True but sets disabled_at for cooldown tracking and
    trading_mode="paper" so the strategy generates validation data.

    Only sets paper mode if the strategy was already paper or shadow.
    Live strategies keep their trading_mode but get disabled_at timestamp.
    """
    config.disabled_at = datetime.now(timezone.utc)
    current_mode = getattr(config, "trading_mode", "paper") or "paper"
    if current_mode in ("paper", "shadow"):
        config.trading_mode = "paper"
    # Live strategies: don't override trading_mode, just set disabled_at
    # Don't set enabled=False — scheduler needs enabled=True to run paper trades


def is_in_rehab(config) -> bool:
    """Check if strategy is in rehab (disabled_at set, still enabled in paper mode)."""
    return config.enabled is True and config.disabled_at is not None


class StrategyHealthMonitor:
    MIN_WARMUP_TRADES = settings.MIN_WARMUP_TRADES
    KILL_WIN_RATE = settings.KILL_WIN_RATE
    WARN_WIN_RATE = settings.WARN_WIN_RATE
    WARN_BRIER = 0.4  # calibration threshold, deployment-independent
    WARN_PSI = 0.25  # drift detection threshold, deployment-independent
    KILL_SHARPE = settings.KILL_SHARPE
    KILL_DRAWDOWN = settings.KILL_DRAWDOWN
    KILL_CUMULATIVE_LOSS = getattr(settings, "KILL_CUMULATIVE_LOSS", -500.0)
    KILL_AVG_LOSS_RATIO = getattr(settings, "KILL_AVG_LOSS_RATIO", 5.0)

    def assess(
        self,
        strategy: str,
        db: Session,
        readonly: bool = False,
        trading_mode: str = "live",
    ) -> Dict[str, Any]:
        """
        Compute full health metrics for a strategy.

        Args:
            strategy: Strategy name to assess.
            db: Database session.
            readonly: If True, compute metrics only — do NOT disable strategies or persist records.
            trading_mode: Filter outcomes to this mode ("live", "paper"). Defaults to "live"
                          to avoid mixing paper and live trades in health metrics.

        Returns dict: total_trades, wins, losses, win_rate, sharpe, max_drawdown,
                      brier_score, psi_score, status
        """
        if strategy == "unknown":
            return self._empty_health(strategy, "active")

        outcomes = (
            db.query(StrategyOutcome)
            .filter(
                StrategyOutcome.strategy == strategy,
                StrategyOutcome.trading_mode == trading_mode,
            )
            .order_by(StrategyOutcome.settled_at.asc())
            .all()
        )

        if not outcomes:
            outcomes = self._outcomes_from_trades(
                strategy, db, trading_mode=trading_mode
            )

        total = len(outcomes)
        wins = sum(1 for o in outcomes if o.result == "win")
        losses = sum(1 for o in outcomes if o.result == "loss")
        win_rate = wins / total if total > 0 else 0.0

        sharpe = self._sharpe_from_outcomes(outcomes)
        max_dd = self._max_drawdown_from_outcomes(outcomes)
        psi = self.compute_psi(strategy, db, trading_mode=trading_mode)
        brier = self._brier_from_outcomes(outcomes)

        # Determine status — check multiple kill conditions
        kill_reason = None
        if self._should_kill_metrics(total, win_rate, sharpe, max_dd):
            kill_reason = (
                f"win_rate={win_rate:.3f}, sharpe={sharpe:.2f}, drawdown={max_dd:.2f}"
            )
        elif self._check_consecutive_losses(outcomes):
            kill_reason = (
                f"10+ consecutive losses (last {min(total, 10)} trades all losses)"
            )
        elif self._check_daily_loss_exceeded(outcomes, max_daily_loss=100.0):
            kill_reason = "cumulative 24h loss > $100"

        if kill_reason:
            status = "killed"
            if not readonly:
                self._disable_strategy(strategy, db)
                try:
                    from backend.core.event_bus import publish_event

                    publish_event(
                        "strategy_killed",
                        {
                            "strategy_name": strategy,
                            "genome_id": getattr(self, "genome_id", None),
                            "reason": f"health_monitor: {kill_reason}",
                            "metrics": {
                                "win_rate": win_rate,
                                "sharpe": sharpe,
                                "max_drawdown": max_dd,
                                "total_trades": total,
                            },
                            "timestamp": _now_utc().isoformat(),
                        },
                    )
                except Exception as e:
                    logger.warning(
                        f"[HealthMonitor] publish_event strategy_killed failed (non-fatal): {e}"
                    )
            logger.warning(
                f"[HealthMonitor] Strategy '{strategy}' KILLED — "
                f"win_rate={win_rate:.3f}, sharpe={sharpe:.2f}, drawdown={max_dd:.2f}"
            )
        elif self._should_warn_metrics(win_rate, brier, psi):
            status = "warned"
            logger.warning(
                f"[HealthMonitor] Strategy '{strategy}' WARNED — "
                f"win_rate={win_rate:.3f}, brier={brier:.3f}, psi={psi:.3f}"
            )
        else:
            status = "active"

        health = {
            "strategy": strategy,
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "sharpe": sharpe,
            "max_drawdown": max_dd,
            "brier_score": brier,
            "psi_score": psi,
            "status": status,
        }

        if not readonly:
            self._persist_health(health, db)

        try:
            from backend.monitoring.metrics import set_strategy_health

            set_strategy_health(strategy, "win_rate", win_rate)
            set_strategy_health(strategy, "sharpe", sharpe)
            set_strategy_health(strategy, "max_drawdown", max_dd)
            set_strategy_health(strategy, "brier_score", brier)
        except Exception:
            logger.exception(
                f"[HealthMonitor] Failed to export strategy health metrics for '{strategy}'"
            )

        return health

    def should_kill(
        self, strategy: str, db: Session, trading_mode: str = "live"
    ) -> bool:
        if strategy == "unknown":
            return False
        outcomes = (
            db.query(StrategyOutcome)
            .filter(
                StrategyOutcome.strategy == strategy,
                StrategyOutcome.trading_mode == trading_mode,
            )
            .all()
        )
        total = len(outcomes)
        if total < self.MIN_WARMUP_TRADES:
            return False
        wins = sum(1 for o in outcomes if o.result == "win")
        win_rate = wins / total
        sharpe = self._sharpe_from_outcomes(outcomes)
        max_dd = self._max_drawdown_from_outcomes(outcomes)
        cumulative_pnl = sum(o.pnl or 0 for o in outcomes)
        win_pnls = [o.pnl for o in outcomes if o.result == "win" and o.pnl]
        loss_pnls = [o.pnl for o in outcomes if o.result == "loss" and o.pnl]
        avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
        avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0
        return self._should_kill_metrics(
            total, win_rate, sharpe, max_dd, cumulative_pnl, avg_win, avg_loss
        ) or self._check_consecutive_losses(outcomes)

    def should_warn(
        self, strategy: str, db: Session, trading_mode: str = "live"
    ) -> bool:
        outcomes = (
            db.query(StrategyOutcome)
            .filter(
                StrategyOutcome.strategy == strategy,
                StrategyOutcome.trading_mode == trading_mode,
            )
            .all()
        )
        if not outcomes:
            return False
        total = len(outcomes)
        wins = sum(1 for o in outcomes if o.result == "win")
        win_rate = wins / total if total > 0 else 0.0
        brier = self._brier_from_outcomes(outcomes)
        psi = self.compute_psi(strategy, db, trading_mode=trading_mode)
        return self._should_warn_metrics(win_rate, brier, psi)

    def compute_psi(
        self, strategy: str, db: Session, trading_mode: str = "live"
    ) -> float:
        outcomes = (
            db.query(StrategyOutcome)
            .filter(
                StrategyOutcome.strategy == strategy,
                StrategyOutcome.trading_mode == trading_mode,
            )
            .order_by(StrategyOutcome.settled_at.desc())
            .limit(60)
            .all()
        )
        if len(outcomes) < 60:
            return 0.0

        recent = outcomes[:30]
        previous = outcomes[30:60]

        def win_rate(group):
            wins = sum(1 for o in group if o.result == "win")
            return wins / len(group)

        r_win = win_rate(recent)
        p_win = win_rate(previous)

        # Clamp to avoid log(0)
        eps = 1e-6
        r_win = max(eps, min(1 - eps, r_win))
        p_win = max(eps, min(1 - eps, p_win))
        r_loss = 1 - r_win
        p_loss = 1 - p_win

        psi = (r_win - p_win) * math.log(r_win / p_win) + (r_loss - p_loss) * math.log(
            r_loss / p_loss
        )
        return abs(psi)

    def compute_sharpe(
        self, strategy: str, db: Session, trading_mode: str = "live"
    ) -> float:
        outcomes = (
            db.query(StrategyOutcome)
            .filter(
                StrategyOutcome.strategy == strategy,
                StrategyOutcome.trading_mode == trading_mode,
            )
            .order_by(StrategyOutcome.settled_at.desc())
            .limit(100)
            .all()
        )
        return self._sharpe_from_outcomes(outcomes)

    def compute_max_drawdown(
        self, strategy: str, db: Session, trading_mode: str = "live"
    ) -> float:
        outcomes = (
            db.query(StrategyOutcome)
            .filter(
                StrategyOutcome.strategy == strategy,
                StrategyOutcome.trading_mode == trading_mode,
            )
            .order_by(StrategyOutcome.settled_at.asc())
            .all()
        )
        return self._max_drawdown_from_outcomes(outcomes)

    # ── private helpers ──────────────────────────────────────────────────────

    def _should_kill_metrics(
        self, total: int, win_rate: float, sharpe: float, max_dd: float,
        cumulative_pnl: float = 0.0, avg_win: float = 0.0, avg_loss: float = 0.0,
    ) -> bool:
        if total < self.MIN_WARMUP_TRADES:
            return False
        if win_rate < self.KILL_WIN_RATE:
            return True
        if sharpe < self.KILL_SHARPE and max_dd > self.KILL_DRAWDOWN:
            return True
        if cumulative_pnl < self.KILL_CUMULATIVE_LOSS:
            logger.warning(
                "[HealthMonitor] KILL: cumulative_pnl=${:.2f} < threshold=${:.2f}".format(
                    cumulative_pnl, self.KILL_CUMULATIVE_LOSS,
                )
            )
            return True
        if avg_win > 0 and avg_loss < 0:
            loss_ratio = abs(avg_loss / avg_win)
            if loss_ratio > self.KILL_AVG_LOSS_RATIO:
                logger.warning(
                    "[HealthMonitor] KILL: avg_loss/avg_win={:.1f} > threshold={:.1f}".format(
                        loss_ratio, self.KILL_AVG_LOSS_RATIO,
                    )
                )
                return True
        return False

    def _check_consecutive_losses(self, outcomes) -> bool:
        """Return True if last 10+ outcomes are all losses."""
        CONSECUTIVE_LOSS_KILL = 10
        if len(outcomes) < CONSECUTIVE_LOSS_KILL:
            return False
        recent = outcomes[-CONSECUTIVE_LOSS_KILL:]
        return all(o.result == "loss" for o in recent)

    def _check_daily_loss_exceeded(self, outcomes, max_daily_loss: float) -> bool:
        """Return True if cumulative loss in last 24h exceeds threshold."""
        from datetime import timedelta

        cutoff = _now_utc() - timedelta(hours=24)
        daily_pnl = 0.0
        for o in outcomes:
            settled = getattr(o, "settled_at", None) or getattr(
                o, "settlement_time", None
            )
            if settled and settled >= cutoff and o.pnl is not None:
                daily_pnl += o.pnl
        return daily_pnl < -max_daily_loss

    def _should_warn_metrics(self, win_rate: float, brier: float, psi: float) -> bool:
        return (
            win_rate < self.WARN_WIN_RATE
            or brier > self.WARN_BRIER
            or psi > self.WARN_PSI
        )

    def _sharpe_from_outcomes(self, outcomes) -> float:
        pnls = [o.pnl for o in outcomes if o.pnl is not None]
        if len(pnls) < 2:
            return 0.0
        n = len(pnls)
        mean = sum(pnls) / n
        variance = sum((p - mean) ** 2 for p in pnls) / n
        std = math.sqrt(variance) if variance > 0 else 1e-9
        return (mean / std) * math.sqrt(n)

    def _max_drawdown_from_outcomes(self, outcomes) -> float:
        pnls = [o.pnl for o in outcomes if o.pnl is not None]
        if not pnls:
            return 0.0
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
        return max_dd

    def _brier_from_outcomes(self, outcomes) -> float:
        pairs = [
            (o.model_probability, 1 if o.result == "win" else 0)
            for o in outcomes
            if o.model_probability is not None and o.result in ("win", "loss")
        ]
        if not pairs:
            return 0.0
        return sum((p - a) ** 2 for p, a in pairs) / len(pairs)

    def _disable_strategy(self, strategy: str, db: Session) -> None:
        """Disable strategy for rehab: keep enabled in paper mode."""
        try:
            from backend.models.database import StrategyConfig

            config = (
                db.query(StrategyConfig)
                .filter(StrategyConfig.strategy_name == strategy)
                .first()
            )
            if config:
                disable_for_rehab(config)
                db.commit()
                logger.info(
                    f"[HealthMonitor] Strategy '{strategy}' entered rehab (paper mode)"
                )
                self._run_postmortem(strategy, db)
            else:
                logger.warning(
                    f"[HealthMonitor] No config row for '{strategy}' — cannot disable"
                )
        except Exception as e:
            logger.error(
                f"[HealthMonitor] Failed to disable strategy '{strategy}': {e}"
            )
            db.rollback()

    def _run_postmortem(self, strategy: str, db: Session) -> None:
        """Analyze killed strategy decision records for root cause anomalies."""
        try:
            from backend.models.database import DecisionLog, StrategyProposal

            decisions = (
                db.query(DecisionLog)
                .filter(DecisionLog.strategy == strategy)
                .order_by(DecisionLog.created_at.desc())
                .limit(50)
                .all()
            )
            if not decisions:
                return

            anomalies = []
            probs = []
            edges = []
            for d in decisions:
                try:
                    data = json.loads(d.signal_data) if d.signal_data else {}
                except (json.JSONDecodeError, TypeError):
                    continue
                p = data.get("model_probability") or data.get("oracle_price")
                e = data.get("edge")
                if p is not None:
                    probs.append(float(p))
                if e is not None:
                    edges.append(float(e))

            if probs:
                unique_probs = len(set(probs))
                if unique_probs == 1:
                    anomalies.append(
                        f"Constant model_probability={probs[0]} across {len(probs)} decisions"
                    )
                elif max(probs) >= 0.99:
                    anomalies.append(
                        f"Suspiciously high max model_probability={max(probs):.2f}"
                    )

            if edges and all(e > 0 for e in edges):
                anomalies.append(
                    f"Edge always positive across {len(edges)} decisions (avg={sum(edges)/len(edges):.3f})"
                )

            if not anomalies:
                return

            existing = (
                db.query(StrategyProposal)
                .filter(
                    StrategyProposal.strategy_name == strategy,
                    StrategyProposal.status == "pending",
                )
                .first()
            )
            if existing:
                return

            proposal = StrategyProposal(
                strategy_name=strategy,
                change_details={
                    "type": "postmortem",
                    "trigger": "strategy_killed",
                    "anomalies": anomalies,
                    "win_rate": 0.0,
                    "total_decisions": len(decisions),
                },
                expected_impact=f"Postmortem: {strategy} killed — {'; '.join(anomalies)}",
                admin_decision="pending",
                status="pending",
                auto_promotable=False,
            )
            db.add(proposal)
            db.commit()
            logger.info(
                "[HealthMonitor] Created postmortem proposal for '%s': %s",
                strategy,
                anomalies,
            )
        except Exception as e:
            logger.error(f"[HealthMonitor] Postmortem failed for '{strategy}': {e}")
            db.rollback()

    def _persist_health(self, health: Dict[str, Any], db: Session) -> None:
        """Insert a StrategyHealthRecord row."""
        try:
            record = StrategyHealthRecord(
                strategy=health["strategy"],
                total_trades=health["total_trades"],
                wins=health["wins"],
                losses=health["losses"],
                win_rate=health["win_rate"],
                sharpe=health["sharpe"],
                max_drawdown=health["max_drawdown"],
                brier_score=health["brier_score"],
                psi_score=health["psi_score"],
                status=health["status"],
                last_updated=datetime.now(timezone.utc),
            )
            db.add(record)
            db.commit()
        except Exception as e:
            logger.error(f"[HealthMonitor] Failed to persist health record: {e}")
            db.rollback()

    def _empty_health(self, strategy: str, status: str) -> Dict[str, Any]:
        return {
            "strategy": strategy,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "brier_score": 0.0,
            "psi_score": 0.0,
            "status": status,
        }

    def _outcomes_from_trades(
        self, strategy: str, db: Session, trading_mode: str = "live"
    ) -> list:
        from backend.models.database import Trade

        return (
            db.query(Trade)
            .filter(
                Trade.strategy == strategy,
                Trade.settled.is_(True),
                Trade.trading_mode == trading_mode,
                Trade.result.in_(["win", "loss"]),
            )
            .order_by(Trade.settlement_time.asc())
            .all()
        )
