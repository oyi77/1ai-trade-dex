"""Methods carved verbatim out of ``backend/core/autonomous_promoter/workflow.py``."""

from __future__ import annotations

from .workflow import (
    ExperimentRunner,
    Optional,
    Session,
)

from . import workflow as _facade

class WorkflowMixinMixin:
    def __init__(self, runner: Optional[ExperimentRunner] = None):
        self.runner = runner
        self._last_run: _facade.Optional[_facade.datetime] = None
    async def run_once(self) -> dict[str, int]:
        """Evaluate all experiments and apply promotion/retirement actions.

        Returns stats: {promoted_shadow→paper, promoted_paper→live, retired, errors}
        """
        stats: dict[str, int] = {
            "shadow_to_paper": 0,
            "paper_to_live": 0,
            "retired": 0,
            "errors": 0,
        }
        with _facade.get_db_session() as db:
            health_mon = (
                _facade.StrategyHealthMonitor()
                if getattr(_facade.settings, "AGI_STRATEGY_HEALTH_ENABLED", True)
                else None
            )

            # -1. Bootstrap genome_registry genomes into experiment_records if missing
            self._bootstrap_genome_experiments(db)

            # 0. Evaluate REVIEW experiments → back to BACKTEST after improvement cycle
            self._run_review_cycle(db, stats)

            # 1–3. Promotion pipeline: DRAFT→BACKTEST→SHADOW→PAPER→LIVE_TRIAL
            self._run_promotion_cycle(db, stats, health_mon)

            # 4–5. Demotion pipeline: LIVE_TRIAL and LIVE_PROMOTED degradation
            await self._run_demotion_cycle(db, stats, health_mon)

            self._last_run = _facade.datetime.now(_facade.timezone.utc)
            _facade.logger.info(
                f"[AutonomousPromoter] Run complete: "
                f"+{stats['shadow_to_paper']} shadow→paper, "
                f"+{stats['paper_to_live']} paper→live, "
                f"retired={stats['retired']}"
            )
            return stats
    def _run_review_cycle(self, db: Session, stats: dict[str, int]) -> None:
        """Phase 0: Check REVIEW experiments → BACKTEST (if improved) or RETIRE (if expired)."""
        reviews = (
            db.query(_facade.ExperimentRecord)
            .filter_by(status=_facade.ExperimentStatus.REVIEW.value)
            .all()
        )
        for exp in reviews:
            improved = self._check_review_completion(exp, db)
            if improved:
                exp.status = _facade.ExperimentStatus.BACKTEST.value
                exp.degradation_count = 0
                exp.review_reason = None
                db.add(exp)
                _facade.logger.info(
                    f"[AutonomousPromoter] REVIEW→BACKTEST '{exp.name}' (improvements applied)"
                )
            elif self._is_review_expired(exp):
                exp.status = _facade.ExperimentStatus.RETIRED.value
                exp.retired_at = _facade.datetime.now(_facade.timezone.utc)
                db.add(exp)
                _facade.logger.warning(
                    f"[AutonomousPromoter] RETIRED '{exp.name}' (review expired without improvement)"
                )
                stats["retired"] += 1
        if reviews:
            db.commit()
    def _run_promotion_cycle(
        self, db: Session, stats: dict[str, int], health_mon
    ) -> None:
        """Phases 1–3: Promote experiments along DRAFT→BACKTEST→SHADOW→PAPER→LIVE_TRIAL pipeline."""
        # ---- Phase 1: DRAFT → BACKTEST ----
        drafts = (
            db.query(_facade.ExperimentRecord)
            .filter_by(status=_facade.ExperimentStatus.DRAFT.value)
            .all()
        )
        for exp in drafts:
            exp.status = _facade.ExperimentStatus.BACKTEST.value
            db.add(exp)
            _facade.logger.info(
                f"[AutonomousPromoter] Draft '{exp.name}' → BACKTEST (awaiting validation)"
            )
        if drafts:
            db.commit()

        # ---- Phase 1b: BACKTEST → SHADOW ----
        backtests = (
            db.query(_facade.ExperimentRecord)
            .filter_by(status=_facade.ExperimentStatus.BACKTEST.value)
            .all()
        )
        for exp in backtests:
            bt_result = self._check_backtest_gate(exp, db)
            if bt_result:
                exp.status = _facade.ExperimentStatus.SHADOW.value
                exp.shadow_trades = 0
                exp.shadow_win_rate = 0.0
                exp.shadow_pnl = 0.0
                exp.backtest_passed = True
                exp.created_at = _facade.datetime.now(_facade.timezone.utc)
                db.add(exp)
                bt_sharpe = (
                    f"{exp.backtest_sharpe:.2f}"
                    if exp.backtest_sharpe is not None
                    else "N/A"
                )
                bt_wr = (
                    f"{exp.backtest_win_rate:.1%}"
                    if exp.backtest_win_rate is not None
                    else "N/A"
                )
                _facade.logger.info(
                    f"[AutonomousPromoter] BACKTEST→SHADOW '{exp.name}': "
                    f"sharpe={bt_sharpe} wr={bt_wr}"
                )
            else:
                ref_time = exp.created_at
                if ref_time and ref_time.tzinfo is None:
                    ref_time = ref_time.replace(tzinfo=_facade.timezone.utc)
                age_days = (
                    _facade.datetime.now(_facade.timezone.utc)
                    - (ref_time or _facade.datetime.now(_facade.timezone.utc))
                ).days
                if age_days > 7:
                    exp.status = _facade.ExperimentStatus.RETIRED.value
                    exp.retired_at = _facade.datetime.now(_facade.timezone.utc)
                    db.add(exp)
                    _facade.logger.warning(
                        f"[AutonomousPromoter] RETIRED '{exp.name}' (backtest failed after 7d)"
                    )
                    stats["retired"] += 1
        if backtests:
            db.commit()

        # ---- Phase 2: SHADOW → PAPER ----
        shadows = (
            db.query(_facade.ExperimentRecord)
            .filter_by(status=_facade.ExperimentStatus.SHADOW.value)
            .all()
        )
        for exp in shadows:
            meets, reasons = self._check_shadow_criteria(exp, db)
            if meets:
                exp.status = _facade.ExperimentStatus.PAPER.value
                exp.promoted_at = _facade.datetime.now(_facade.timezone.utc)
                db.add(exp)
                try:
                    _facade.publish_event(
                        "experiment_promoted",
                        {
                            "genome_id": exp.id,
                            "strategy_name": exp.strategy_name or exp.name,
                            "from_stage": "SHADOW",
                            "to_stage": "PAPER",
                            "shadow_trades": exp.shadow_trades,
                            "shadow_win_rate": exp.shadow_win_rate,
                            "timestamp": _facade.datetime.now(_facade.timezone.utc).isoformat(),
                        },
                    )
                except Exception as e:
                    _facade.logger.warning(
                        f"[AutonomousPromoter] publish_event failed (non-fatal): {e}"
                    )
                shadow_health = {
                    "total_trades": exp.shadow_trades or 0,
                    "win_rate": exp.shadow_win_rate or 0.0,
                    "pnl": exp.shadow_pnl or 0.0,
                    "sharpe": 0.0,
                    "max_drawdown": self._compute_shadow_drawdown(exp, db),
                }
                self._capture_promotion_review(
                    exp, db, "SHADOW", "PAPER", shadow_health
                )
                _facade.logger.info(
                    f"[AutonomousPromoter] SHADOW→PAPER '{exp.name}': "
                    f"trades={exp.shadow_trades}, wr={exp.shadow_win_rate:.1%}"
                )
                stats["shadow_to_paper"] += 1
            else:
                created_at = exp.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=_facade.timezone.utc)
                age_days = (_facade.datetime.now(_facade.timezone.utc) - created_at).days
                if age_days > self.MIN_DAYS_SHADOW * 2:
                    exp.status = _facade.ExperimentStatus.RETIRED.value
                    exp.retired_at = _facade.datetime.now(_facade.timezone.utc)
                    db.add(exp)
                    _facade.logger.warning(
                        f"[AutonomousPromoter] RETIRED '{exp.name}' (shadow, age={age_days}d): "
                        f"{'; '.join(reasons)}"
                    )
                    stats["retired"] += 1
        if shadows:
            db.commit()

        # ---- Phase 3: PAPER → LIVE_TRIAL (or demotion/retirement) ----
        papers = (
            db.query(_facade.ExperimentRecord)
            .filter_by(status=_facade.ExperimentStatus.PAPER.value)
            .all()
        )
        for exp in papers:
            strategy_name = exp.strategy_name or exp.name

            health = (
                health_mon.assess(strategy_name, db)
                if health_mon
                else {
                    "status": "active",
                    "total_trades": 0,
                    "win_rate": 0.0,
                    "sharpe": 0.0,
                    "max_drawdown": 0.0,
                    "brier_score": 1.0,
                    "psi_score": 0.0,
                }
            )
            if health.get("status") == "killed":
                exp.status = _facade.ExperimentStatus.PAPER.value
                exp.promoted_at = None
                exp.last_demoted_at = _facade.datetime.now(_facade.timezone.utc) + _facade.timedelta(hours=48)

                _md = exp.misc_data if isinstance(exp.misc_data, dict) else {}
                retry_count = _md.get("kill_retry_count", 0)
                retry_count += 1
                _md["kill_retry_count"] = retry_count
                exp.misc_data = _md
                max_retries = getattr(_facade.settings, "AGI_DEMOTION_RETRY_LIMIT", 3)
                if retry_count >= max_retries:
                    exp.status = _facade.ExperimentStatus.RETIRED.value
                    exp.retired_at = _facade.datetime.now(_facade.timezone.utc)
                    _facade.logger.warning(
                        f"[AutonomousPromoter] RETIRED (kill, {retry_count} retries) '{exp.name}': "
                        f"wr={health.get('win_rate', 0):.1%}, sharpe={health.get('sharpe', 0):.2f}"
                    )
                    stats["retired"] += 1
                else:
                    db.add(exp)
                    _facade.logger.warning(
                        f"[AutonomousPromoter] DEMOTED (kill) '{exp.name}' → PAPER, "
                        f"retry {retry_count}/{max_retries}, cooldown 48h: "
                        f"wr={health.get('win_rate', 0):.1%}, sharpe={health.get('sharpe', 0):.2f}"
                    )
                    stats["demoted_live_to_paper"] = stats.get("demoted_live_to_paper", 0) + 1
                db.add(exp)
                continue

            if getattr(exp, "last_demoted_at", None):
                cooldown_end = exp.last_demoted_at
                if cooldown_end.tzinfo is None:
                    cooldown_end = cooldown_end.replace(tzinfo=_facade.timezone.utc)
                if _facade.datetime.now(_facade.timezone.utc) < cooldown_end:
                    _facade.logger.info(
                        f"[AutonomousPromoter] PAPER→LIVE SKIPPED '{exp.name}': "
                        f"cooldown active until {cooldown_end.isoformat()}"
                    )
                    continue

            meets, reasons = self._check_paper_criteria_from_health(exp, health, db=db)
            if meets:
                if not _facade.settings.AGI_AUTO_PROMOTE:
                    _facade.logger.info(
                        f"[AutonomousPromoter] PAPER→LIVE_TRIAL SKIPPED '{exp.name}': "
                        f"AGI_AUTO_PROMOTE=false (manual intervention required)"
                    )
                    continue
                try:
                    _facade.publish_event(
                        "experiment_promoted",
                        {
                            "genome_id": exp.id,
                            "strategy_name": exp.strategy_name or exp.name,
                            "from_stage": "PAPER",
                            "to_stage": "LIVE_TRIAL",
                            "win_rate": health.get("win_rate", 0.0),
                            "sharpe": health.get("sharpe", 0.0),
                            "timestamp": _facade.datetime.now(_facade.timezone.utc).isoformat(),
                        },
                    )
                except Exception as e:
                    _facade.logger.warning(
                        f"[AutonomousPromoter] publish_event failed (non-fatal): {e}"
                    )
                self._capture_promotion_review(
                    exp, db, "PAPER", "LIVE_TRIAL", health
                )
                exp.status = _facade.ExperimentStatus.LIVE_TRIAL.value
                exp.promoted_at = _facade.datetime.now(_facade.timezone.utc)
                db.add(exp)
                _facade.logger.info(
                    f"[AutonomousPromoter] PAPER→LIVE_TRIAL '{exp.name}' promoted to trial "
                    f"(trades={health.get('total_trades', 0)}, wr={health.get('win_rate', 0):.1%})"
                )
                stats["paper_to_live_trial"] = (
                    stats.get("paper_to_live_trial", 0) + 1
                )
                ref_time = exp.promoted_at or exp.created_at
                if ref_time.tzinfo is None:
                    ref_time = ref_time.replace(tzinfo=_facade.timezone.utc)
                age_days = (_facade.datetime.now(_facade.timezone.utc) - ref_time).days
                if age_days > self.MIN_DAYS_PAPER * 3:
                    exp.status = _facade.ExperimentStatus.RETIRED.value
                    exp.retired_at = _facade.datetime.now(_facade.timezone.utc)
                    db.add(exp)
                    _facade.logger.warning(
                        f"[AutonomousPromoter] RETIRED '{exp.name}' (paper, age={age_days}d): "
                        f"{'; '.join(reasons)}"
                    )
                    stats["retired"] += 1
        if papers:
            db.commit()
