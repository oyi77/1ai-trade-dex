"""WorkflowMixin — main promotion loop and strategy lifecycle management."""

from __future__ import annotations
import json as _json
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.database import StrategyConfig, GenomeRegistry, StrategyProposal
from backend.models.kg_models import ExperimentRecord
from backend.core.experiment_runner import ExperimentRunner
from backend.core.agi_types import ExperimentStatus
from backend.core.event_bus import publish_event
from backend.core.strategy_health import disable_for_rehab
from backend.core.forensics_integration import generate_forensics_proposals
from backend.core.safe_param_tuner import SafeParamTuner
from backend.db.utils import utcnow, get_db_session

from loguru import logger


class WorkflowMixin:
    """Mixin providing __init__, run_once, strategy enable/disable, and improvement loop."""

    def __init__(self, runner: Optional[ExperimentRunner] = None):
        self.runner = runner
        self._last_run: Optional[datetime] = None

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
        with get_db_session() as db:
            health_mon = (
                StrategyHealthMonitor()
                if getattr(settings, "AGI_STRATEGY_HEALTH_ENABLED", True)
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

            self._last_run = datetime.now(timezone.utc)
            logger.info(
                f"[AutonomousPromoter] Run complete: "
                f"+{stats['shadow_to_paper']} shadow→paper, "
                f"+{stats['paper_to_live']} paper→live, "
                f"retired={stats['retired']}"
            )
            return stats

    def _run_review_cycle(self, db: Session, stats: dict[str, int]) -> None:
        """Phase 0: Check REVIEW experiments → BACKTEST (if improved) or RETIRE (if expired)."""
        reviews = (
            db.query(ExperimentRecord)
            .filter_by(status=ExperimentStatus.REVIEW.value)
            .all()
        )
        for exp in reviews:
            improved = self._check_review_completion(exp, db)
            if improved:
                exp.status = ExperimentStatus.BACKTEST.value
                exp.degradation_count = 0
                exp.review_reason = None
                db.add(exp)
                logger.info(
                    f"[AutonomousPromoter] REVIEW→BACKTEST '{exp.name}' (improvements applied)"
                )
            elif self._is_review_expired(exp):
                exp.status = ExperimentStatus.RETIRED.value
                exp.retired_at = datetime.now(timezone.utc)
                db.add(exp)
                logger.warning(
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
            db.query(ExperimentRecord)
            .filter_by(status=ExperimentStatus.DRAFT.value)
            .all()
        )
        for exp in drafts:
            exp.status = ExperimentStatus.BACKTEST.value
            db.add(exp)
            logger.info(
                f"[AutonomousPromoter] Draft '{exp.name}' → BACKTEST (awaiting validation)"
            )
        if drafts:
            db.commit()

        # ---- Phase 1b: BACKTEST → SHADOW ----
        backtests = (
            db.query(ExperimentRecord)
            .filter_by(status=ExperimentStatus.BACKTEST.value)
            .all()
        )
        for exp in backtests:
            bt_result = self._check_backtest_gate(exp, db)
            if bt_result:
                exp.status = ExperimentStatus.SHADOW.value
                exp.shadow_trades = 0
                exp.shadow_win_rate = 0.0
                exp.shadow_pnl = 0.0
                exp.backtest_passed = True
                exp.created_at = datetime.now(timezone.utc)
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
                logger.info(
                    f"[AutonomousPromoter] BACKTEST→SHADOW '{exp.name}': "
                    f"sharpe={bt_sharpe} wr={bt_wr}"
                )
            else:
                ref_time = exp.created_at
                if ref_time and ref_time.tzinfo is None:
                    ref_time = ref_time.replace(tzinfo=timezone.utc)
                age_days = (
                    datetime.now(timezone.utc)
                    - (ref_time or datetime.now(timezone.utc))
                ).days
                if age_days > 7:
                    exp.status = ExperimentStatus.RETIRED.value
                    exp.retired_at = datetime.now(timezone.utc)
                    db.add(exp)
                    logger.warning(
                        f"[AutonomousPromoter] RETIRED '{exp.name}' (backtest failed after 7d)"
                    )
                    stats["retired"] += 1
        if backtests:
            db.commit()

        # ---- Phase 2: SHADOW → PAPER ----
        shadows = (
            db.query(ExperimentRecord)
            .filter_by(status=ExperimentStatus.SHADOW.value)
            .all()
        )
        for exp in shadows:
            meets, reasons = self._check_shadow_criteria(exp, db)
            if meets:
                exp.status = ExperimentStatus.PAPER.value
                exp.promoted_at = datetime.now(timezone.utc)
                db.add(exp)
                try:
                    publish_event(
                        "experiment_promoted",
                        {
                            "genome_id": exp.id,
                            "strategy_name": exp.strategy_name or exp.name,
                            "from_stage": "SHADOW",
                            "to_stage": "PAPER",
                            "shadow_trades": exp.shadow_trades,
                            "shadow_win_rate": exp.shadow_win_rate,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                except Exception as e:
                    logger.warning(
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
                logger.info(
                    f"[AutonomousPromoter] SHADOW→PAPER '{exp.name}': "
                    f"trades={exp.shadow_trades}, wr={exp.shadow_win_rate:.1%}"
                )
                stats["shadow_to_paper"] += 1
            else:
                created_at = exp.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - created_at).days
                if age_days > self.MIN_DAYS_SHADOW * 2:
                    exp.status = ExperimentStatus.RETIRED.value
                    exp.retired_at = datetime.now(timezone.utc)
                    db.add(exp)
                    logger.warning(
                        f"[AutonomousPromoter] RETIRED '{exp.name}' (shadow, age={age_days}d): "
                        f"{'; '.join(reasons)}"
                    )
                    stats["retired"] += 1
        if shadows:
            db.commit()

        # ---- Phase 3: PAPER → LIVE_TRIAL (or demotion/retirement) ----
        papers = (
            db.query(ExperimentRecord)
            .filter_by(status=ExperimentStatus.PAPER.value)
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
                exp.status = ExperimentStatus.PAPER.value
                exp.promoted_at = None
                exp.last_demoted_at = datetime.now(timezone.utc) + timedelta(hours=48)

                _md = exp.misc_data if isinstance(exp.misc_data, dict) else {}
                retry_count = _md.get("kill_retry_count", 0)
                retry_count += 1
                _md["kill_retry_count"] = retry_count
                exp.misc_data = _md
                max_retries = getattr(settings, "AGI_DEMOTION_RETRY_LIMIT", 3)
                if retry_count >= max_retries:
                    exp.status = ExperimentStatus.RETIRED.value
                    exp.retired_at = datetime.now(timezone.utc)
                    logger.warning(
                        f"[AutonomousPromoter] RETIRED (kill, {retry_count} retries) '{exp.name}': "
                        f"wr={health.get('win_rate', 0):.1%}, sharpe={health.get('sharpe', 0):.2f}"
                    )
                    stats["retired"] += 1
                else:
                    db.add(exp)
                    logger.warning(
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
                    cooldown_end = cooldown_end.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) < cooldown_end:
                    logger.info(
                        f"[AutonomousPromoter] PAPER→LIVE SKIPPED '{exp.name}': "
                        f"cooldown active until {cooldown_end.isoformat()}"
                    )
                    continue

            meets, reasons = self._check_paper_criteria_from_health(exp, health, db=db)
            if meets:
                if not settings.AGI_AUTO_PROMOTE:
                    logger.info(
                        f"[AutonomousPromoter] PAPER→LIVE_TRIAL SKIPPED '{exp.name}': "
                        f"AGI_AUTO_PROMOTE=false (manual intervention required)"
                    )
                    continue
                try:
                    publish_event(
                        "experiment_promoted",
                        {
                            "genome_id": exp.id,
                            "strategy_name": exp.strategy_name or exp.name,
                            "from_stage": "PAPER",
                            "to_stage": "LIVE_TRIAL",
                            "win_rate": health.get("win_rate", 0.0),
                            "sharpe": health.get("sharpe", 0.0),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                except Exception as e:
                    logger.warning(
                        f"[AutonomousPromoter] publish_event failed (non-fatal): {e}"
                    )
                self._capture_promotion_review(
                    exp, db, "PAPER", "LIVE_TRIAL", health
                )
                exp.status = ExperimentStatus.LIVE_TRIAL.value
                exp.promoted_at = datetime.now(timezone.utc)
                db.add(exp)
                logger.info(
                    f"[AutonomousPromoter] PAPER→LIVE_TRIAL '{exp.name}' promoted to trial "
                    f"(trades={health.get('total_trades', 0)}, wr={health.get('win_rate', 0):.1%})"
                )
                stats["paper_to_live_trial"] = (
                    stats.get("paper_to_live_trial", 0) + 1
                )
                ref_time = exp.promoted_at or exp.created_at
                if ref_time.tzinfo is None:
                    ref_time = ref_time.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - ref_time).days
                if age_days > self.MIN_DAYS_PAPER * 3:
                    exp.status = ExperimentStatus.RETIRED.value
                    exp.retired_at = datetime.now(timezone.utc)
                    db.add(exp)
                    logger.warning(
                        f"[AutonomousPromoter] RETIRED '{exp.name}' (paper, age={age_days}d): "
                        f"{'; '.join(reasons)}"
                    )
                    stats["retired"] += 1
        if papers:
            db.commit()

    async def _run_demotion_cycle(
        self, db: Session, stats: dict[str, int], health_mon
    ) -> None:
        """Phases 4–5: Evaluate LIVE_TRIAL and LIVE_PROMOTED for demotion/degradation."""
        # ---- Phase 4: LIVE_TRIAL → LIVE_PROMOTED or → PAPER ----
        trials = (
            db.query(ExperimentRecord)
            .filter_by(status=ExperimentStatus.LIVE_TRIAL.value)
            .all()
        )
        for exp in trials:
            strategy_name = exp.strategy_name or exp.name
            promoted = exp.promoted_at or exp.created_at
            if promoted.tzinfo is None:
                promoted = promoted.replace(tzinfo=timezone.utc)
            trial_days = (datetime.now(timezone.utc) - promoted).days
            min_trial_days = getattr(settings, "AGI_LIVE_TRIAL_DAYS", 7)
            min_trial_trades = getattr(settings, "AGI_LIVE_TRIAL_MIN_TRADES", 10)

            health = (
                health_mon.assess(strategy_name, db, readonly=True)
                if health_mon
                else {
                    "status": "active",
                    "total_trades": 0,
                    "win_rate": 0.0,
                    "sharpe": 0.0,
                }
            )
            if health.get("status") == "killed":
                exp.status = ExperimentStatus.PAPER.value
                exp.promoted_at = None
                db.add(exp)
                logger.warning(
                    f"[AutonomousPromoter] LIVE_TRIAL→PAPER (kill) '{exp.name}': wr={health.get('win_rate', 0):.1%}"
                )
                stats["demoted"] = stats.get("demoted", 0) + 1
                publish_event(
                    "strategy_demoted",
                    {
                        "strategy_name": strategy_name,
                        "from_stage": "LIVE_TRIAL",
                        "to_stage": "PAPER",
                        "reason": "health_killed",
                        "win_rate": health.get("win_rate", 0.0),
                        "sharpe": health.get("sharpe", 0.0),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
                self._trigger_improvement_loop(strategy_name, db)
                continue

            if (
                trial_days >= min_trial_days
                and health.get("total_trades", 0) >= min_trial_trades
            ):
                wr = health.get("win_rate", 0.0)
                sharpe = health.get("sharpe", 0.0)
                if wr >= 0.55 and sharpe >= 0.3:
                    exp.status = ExperimentStatus.LIVE_PROMOTED.value
                    exp.promoted_at = datetime.now(timezone.utc)
                    if settings.AGI_AUTO_ENABLE:
                        await self._enable_strategy(
                            strategy_name, db, experiment=exp
                        )
                    db.add(exp)
                    try:
                        publish_event(
                            "experiment_promoted",
                            {
                                "genome_id": exp.id,
                                "strategy_name": exp.strategy_name or exp.name,
                                "from_stage": "LIVE_TRIAL",
                                "to_stage": "LIVE_PROMOTED",
                                "win_rate": wr,
                                "sharpe": sharpe,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                    except Exception as e:
                        logger.warning(
                            f"[AutonomousPromoter] publish_event failed (non-fatal): {e}"
                        )
                    self._capture_promotion_review(
                        exp, db, "LIVE_TRIAL", "LIVE_PROMOTED", health
                    )
                    logger.info(
                        f"[AutonomousPromoter] LIVE_TRIAL→LIVE_PROMOTED '{exp.name}': wr={wr:.1%} sharpe={sharpe:.2f}"
                    )
                    stats["trial_to_live"] = stats.get("trial_to_live", 0) + 1
                else:
                    exp.status = ExperimentStatus.PAPER.value
                    exp.promoted_at = None
                    db.add(exp)
                    logger.warning(
                        f"[AutonomousPromoter] LIVE_TRIAL→PAPER (degraded) '{exp.name}': wr={wr:.1%} sharpe={sharpe:.2f}"
                    )
                    stats["demoted"] = stats.get("demoted", 0) + 1
                    publish_event(
                        "strategy_demoted",
                        {
                            "strategy_name": strategy_name,
                            "from_stage": "LIVE_TRIAL",
                            "to_stage": "PAPER",
                            "reason": "degraded",
                            "win_rate": wr,
                            "sharpe": sharpe,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    self._trigger_improvement_loop(strategy_name, db)
        if trials:
            db.commit()

        # ---- Phase 5: LIVE_PROMOTED degradation → PAPER or REVIEW ----
        lives = (
            db.query(ExperimentRecord)
            .filter_by(status=ExperimentStatus.LIVE_PROMOTED.value)
            .all()
        )
        for exp in lives:
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
                }
            )
            if health.get("status") == "killed":
                exp.status = ExperimentStatus.PAPER.value
                exp.promoted_at = None
                db.add(exp)
                logger.warning(
                    f"[AutonomousPromoter] LIVE_PROMOTED→PAPER (kill) '{exp.name}': "
                    f"wr={health.get('win_rate', 0):.1%}, sharpe={health.get('sharpe', 0):.2f}"
                )
                stats["demoted"] = stats.get("demoted", 0) + 1
                publish_event(
                    "strategy_demoted",
                    {
                        "strategy_name": strategy_name,
                        "from_stage": "LIVE_PROMOTED",
                        "to_stage": "PAPER",
                        "reason": "health_killed",
                        "win_rate": health.get("win_rate", 0.0),
                        "sharpe": health.get("sharpe", 0.0),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
                self._trigger_improvement_loop(strategy_name, db)
                continue

            wr = health.get("win_rate", 0.0)
            sharpe = health.get("sharpe", 0.0)
            total_trades = health.get("total_trades", 0)
            if total_trades >= self.MIN_WARMUP_TRADES and (
                wr < self.DEGRADATION_WR_THRESHOLD
                or sharpe < self.DEGRADATION_SHARPE_THRESHOLD
            ):
                exp.degradation_count = (exp.degradation_count or 0) + 1
                exp.last_degradation_at = datetime.now(timezone.utc)
                if exp.degradation_count >= self.MAX_DEGRADATIONS_BEFORE_REVIEW:
                    exp.status = ExperimentStatus.REVIEW.value
                    exp.review_reason = (
                        f"Degraded: wr={wr:.1%} sharpe={sharpe:.2f} over {total_trades} trades "
                        f"({exp.degradation_count} degradation events)"
                    )
                    exp.degradation_count = 0
                    await self._disable_strategy(strategy_name, db)
                    publish_event(
                        "strategy_demoted",
                        {
                            "strategy_name": strategy_name,
                            "from_stage": "LIVE_PROMOTED",
                            "to_stage": "REVIEW",
                            "reason": "degraded",
                            "win_rate": wr,
                            "sharpe": sharpe,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    logger.warning(
                        f"[AutonomousPromoter] LIVE→REVIEW '{exp.name}': {exp.review_reason}"
                    )
                else:
                    logger.warning(
                        f"[AutonomousPromoter] DEGRADATION #{exp.degradation_count} '{exp.name}': "
                        f"wr={wr:.1%} sharpe={sharpe:.2f}"
                    )
                db.add(exp)
        if lives:
            db.commit()

    async def _enable_strategy(
        self,
        strategy_name: str,
        db: Session,
        experiment: Optional[ExperimentRecord] = None,
    ) -> None:
        """Create/enable StrategyConfig for the promoted experiment and schedule it.

        If experiment carries evolved params (strategy_composition), merge them into
        the strategy's live config — this closes the RL loop: evolver generates variants,
        best variant promotes to live, params get applied.
        """
        # LIVE_STRATEGY_ALLOWLIST gate — only promote strategies that are explicitly
        # allowed. If list is empty, ALL strategies are allowed (permissive mode).
        allowed = settings.LIVE_STRATEGY_ALLOWLIST
        if allowed and strategy_name not in allowed:
            logger.warning(
                f"[AutonomousPromoter] {strategy_name} NOT in LIVE_STRATEGY_ALLOWLIST, "
                f"skipping live promotion (allowed: {allowed})"
            )
            return

        config = db.query(StrategyConfig).filter_by(strategy_name=strategy_name).first()
        if config:
            config.enabled = True
            config.updated_at = utcnow()
            interval = config.interval_seconds or 60

            # Apply evolved params from experiment if available
            if experiment and experiment.strategy_composition:
                evolved_params = experiment.strategy_composition
                if isinstance(evolved_params, str):
                    try:
                        evolved_params = _json.loads(evolved_params)
                    except (_json.JSONDecodeError, TypeError):
                        evolved_params = {}
                # Strip internal evolver metadata
                evolved_params = {
                    k: v for k, v in evolved_params.items() if not k.startswith("_")
                }

                current_params = config.params or {}
                if isinstance(current_params, str):
                    try:
                        current_params = _json.loads(current_params)
                    except (_json.JSONDecodeError, TypeError):
                        current_params = {}

                merged = {**current_params, **evolved_params}
                config.params = merged
                logger.info(
                    f"[AutonomousPromoter] Applied evolved params to '{strategy_name}': "
                    f"merged {len(evolved_params)} param(s) into live config"
                )

            logger.info(
                f"[AutonomousPromoter] Enabled existing StrategyConfig '{strategy_name}' (interval={interval}s)"
            )
        else:
            # LIVE_STRATEGY_ALLOWLIST gate — also for new strategy creation
            if allowed and strategy_name not in allowed:
                logger.warning(
                    f"[AutonomousPromoter] {strategy_name} NOT in LIVE_STRATEGY_ALLOWLIST, "
                    f"skipping new strategy creation (allowed: {allowed})"
                )
                return

            # Infer interval from strategy registry
            strategy_cls = STRATEGY_REGISTRY.get(strategy_name)
            default_interval = 60
            if strategy_cls and hasattr(strategy_cls, "default_interval"):
                default_interval = getattr(strategy_cls, "default_interval", 60)

            initial_params = {}
            if experiment and experiment.strategy_composition:
                initial_params = experiment.strategy_composition
                if isinstance(initial_params, str):
                    try:
                        initial_params = _json.loads(initial_params)
                    except (_json.JSONDecodeError, TypeError):
                        initial_params = {}
                initial_params = {
                    k: v for k, v in initial_params.items() if not k.startswith("_")
                }

            config = StrategyConfig(
                strategy_name=strategy_name,
                enabled=True,
                interval_seconds=default_interval,
                mode="live",
                params=initial_params if initial_params else None,
            )
            db.add(config)
            interval = default_interval
            logger.info(
                f"[AutonomousPromoter] Created & enabled StrategyConfig '{strategy_name}' (interval={interval}s)"
            )
        db.commit()

        try:
            schedule_strategy(strategy_name, interval, mode="live")
        except Exception as e:
            logger.warning(
                f"[AutonomousPromoter] Failed to dynamically schedule '{strategy_name}': {e}"
            )

    async def _disable_strategy(self, strategy_name: str, db: Session) -> None:
        config = db.query(StrategyConfig).filter_by(strategy_name=strategy_name).first()
        if config:
            disable_for_rehab(config)
            db.commit()
            logger.info(
                f"[AutonomousPromoter] Disabled StrategyConfig '{strategy_name}' (degradation fallback)"
            )

    def _trigger_improvement_loop(self, strategy_name: str, db: Session) -> None:
        """Trigger forensics analysis + auto_improve for a demoted strategy.

        Creates a new DRAFT ExperimentRecord so the strategy re-enters the
        DRAFT→SHADOW→PAPER→LIVE_TRIAL pipeline with improved params.
        Respects AGI_MAX_IMPROVEMENT_ATTEMPTS to avoid infinite retry loops.
        """
        max_attempts = getattr(settings, "AGI_MAX_IMPROVEMENT_ATTEMPTS", 3)

        # Count how many improvement attempts have already been made
        attempt_count = (
            db.query(ExperimentRecord)
            .filter(
                ExperimentRecord.strategy_name == strategy_name,
                ExperimentRecord.status.in_(
                    [
                        ExperimentStatus.RETIRED.value,
                        ExperimentStatus.PAPER.value,
                        ExperimentStatus.DRAFT.value,
                    ]
                ),
            )
            .count()
        )

        if attempt_count >= max_attempts:
            logger.warning(
                "[AutonomousPromoter] '%s' reached max improvement attempts (%d) — retiring",
                strategy_name,
                max_attempts,
            )
            # Mark all active experiments for this strategy as RETIRED
            db.query(ExperimentRecord).filter(
                ExperimentRecord.strategy_name == strategy_name,
                ExperimentRecord.status.notin_([ExperimentStatus.RETIRED.value]),
            ).update(
                {"status": ExperimentStatus.RETIRED.value}, synchronize_session=False
            )
            db.commit()
            return

        # 1. Generate forensics proposals
        try:
            generate_forensics_proposals(strategy_filter=strategy_name)
            logger.info(
                "[AutonomousPromoter] Forensics proposals generated for '%s'",
                strategy_name,
            )
        except Exception as e:
            logger.warning(
                "[AutonomousPromoter] Forensics generation failed for '%s': %s",
                strategy_name,
                e,
            )

        # 2. Param tuning attempt — tune strategy parameters before creating new DRAFT
        try:
            with get_db_session() as tune_db:
                tuner = SafeParamTuner()
                changes = tuner.tune(strategy_name, tune_db)
                if changes:
                    logger.info(
                        "[AutonomousPromoter] Pre-improvement param tuning for '%s': %s",
                        strategy_name,
                        changes,
                    )
        except Exception as e:
            logger.warning(
                "[AutonomousPromoter] Pre-improvement tuning failed for '%s': %s",
                strategy_name,
                e,
            )

        # 3. Capture demotion context from the most recent experiment
        demotion_context: dict = {}
        try:
            prior_exp = (
                db.query(ExperimentRecord)
                .filter(
                    ExperimentRecord.strategy_name == strategy_name,
                    ExperimentRecord.status.notin_([ExperimentStatus.DRAFT.value]),
                )
                .order_by(ExperimentRecord.created_at.desc())
                .first()
            )
            if prior_exp:
                demotion_context = {
                    "demoted_from": getattr(prior_exp, "status", "unknown"),
                    "demotion_reason": getattr(prior_exp, "review_reason", None)
                    or "health_monitor_kill",
                    "previous_metrics": {
                        "win_rate": getattr(prior_exp, "shadow_win_rate", 0.0) or 0.0,
                        "trades": getattr(prior_exp, "shadow_trades", 0) or 0,
                    },
                    "improvement_attempt": attempt_count + 1,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
        except Exception as e:
            logger.warning(
                "[AutonomousPromoter] Failed to capture demotion context for '%s': %s",
                strategy_name,
                e,
            )

        # 4. Backtest validation — verify tuned params don't crash before re-entering pipeline
        backtest_passed = False
        try:
            from backend.core.backtest_engine import BacktestEngine  # deferred: import fails at module level (wrong module path)

            bt_engine = BacktestEngine()
            bt_result = bt_engine.run_backtest(
                strategy_name=strategy_name,
                mode="quick",
                lookback_days=getattr(settings, "AGI_IMPROVEMENT_BACKTEST_DAYS", 30),
            )
            backtest_passed = (
                bt_result.get("success", False)
                if isinstance(bt_result, dict)
                else bool(bt_result)
            )
            bt_wr = (
                bt_result.get("win_rate", 0.0) if isinstance(bt_result, dict) else 0.0
            )
            bt_trades = (
                bt_result.get("total_trades", 0) if isinstance(bt_result, dict) else 0
            )
            logger.info(
                "[AutonomousPromoter] Improvement backtest for '%s': passed=%s wr=%.1f%% trades=%d",
                strategy_name,
                backtest_passed,
                bt_wr * 100,
                bt_trades,
            )
        except Exception as e:
            logger.warning(
                "[AutonomousPromoter] Improvement backtest failed for '%s': %s (proceeding anyway)",
                strategy_name,
                e,
            )
            backtest_passed = True  # Don't block on backtest engine failures

        if not backtest_passed:
            logger.warning(
                "[AutonomousPromoter] Improvement backtest FAILED for '%s' — creating DRAFT anyway but flagging for review",
                strategy_name,
            )
            demotion_context["backtest_failed"] = True

        # 5. Create a new DRAFT experiment so the strategy re-enters the pipeline
        new_exp = ExperimentRecord(
            name=f"{strategy_name}_improve_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}",
            strategy_name=strategy_name,
            status=ExperimentStatus.DRAFT.value,
            created_at=datetime.now(timezone.utc),
            strategy_composition=demotion_context if demotion_context else None,
        )
        db.add(new_exp)
        db.commit()
        logger.info(
            "[AutonomousPromoter] Created new DRAFT experiment '%s' for improvement cycle (attempt %d/%d)",
            new_exp.name,
            attempt_count + 1,
            max_attempts,
        )

    def _bootstrap_genome_experiments(self, db: Session) -> None:
        """Create ExperimentRecord rows for genome_registry genomes that lack them."""
        genomes = (
            db.query(GenomeRegistry)
            .filter(GenomeRegistry.stage.in_(["DRAFT", "SHADOW", "PAPER", "LIVE"]))
            .all()
        )
        if not genomes:
            return

        for genome in genomes:
            existing = (
                db.query(ExperimentRecord).filter_by(name=genome.strategy_name).first()
            )
            if existing:
                continue

            stage_map = {
                "DRAFT": ExperimentStatus.DRAFT.value,
                "SHADOW": ExperimentStatus.SHADOW.value,
                "PAPER": ExperimentStatus.PAPER.value,
                "LIVE": ExperimentStatus.LIVE_PROMOTED.value,
            }
            exp = ExperimentRecord(
                name=genome.strategy_name,
                strategy_name=genome.strategy_name,
                status=stage_map.get(genome.stage, ExperimentStatus.DRAFT.value),
                created_at=genome.created_at or datetime.now(timezone.utc),
            )
            db.add(exp)
            logger.info(
                f"[AutonomousPromoter] Bootstrapped ExperimentRecord "
                f"'{genome.strategy_name}' at stage={genome.stage}"
            )
        db.commit()

    def _check_backtest_gate(self, exp: ExperimentRecord, db: Session) -> bool:
        proposal = (
            db.query(StrategyProposal)
            .filter_by(strategy_name=exp.strategy_name, status="pending")
            .order_by(StrategyProposal.created_at.desc())
            .first()
        )
        if proposal and proposal.backtest_passed:
            exp.backtest_sharpe = proposal.backtest_sharpe
            exp.backtest_win_rate = proposal.backtest_win_rate
            return True
        if exp.backtest_passed:
            return True

        # Seed-genome bypass: if no StrategyProposal exists at all, auto-pass
        # the gate. Initial population genomes were hand-crafted with predefined
        # chromosome configs — they don't need formal backtest validation, they
        # need shadow testing. Only apply this bypass when there are zero
        # proposals for this strategy (not when proposals exist but haven't
        # passed — that case should still wait for backtest completion).
        any_proposal = (
            db.query(StrategyProposal)
            .filter_by(strategy_name=exp.strategy_name)
            .first()
        )
        if not any_proposal:
            logger.info(
                f"[AutonomousPromoter] BACKTEST gate for '{exp.name}': "
                f"no StrategyProposal exists — requires manual validation"
            )
            return False

        return False

    def _check_review_completion(self, exp: ExperimentRecord, db: Session) -> bool:
        new_proposals = (
            db.query(StrategyProposal)
            .filter(
                StrategyProposal.strategy_name == exp.strategy_name,
                StrategyProposal.status == "pending",
                StrategyProposal.backtest_passed.is_(True),
            )
            .order_by(StrategyProposal.created_at.desc())
            .first()
        )
        if new_proposals:
            exp.backtest_sharpe = new_proposals.backtest_sharpe
            exp.backtest_win_rate = new_proposals.backtest_win_rate
            return True
        return False

    def _is_review_expired(self, exp: ExperimentRecord) -> bool:
        ref = exp.last_degradation_at or exp.created_at
        if ref and ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        if not ref:
            return False
        return (datetime.now(timezone.utc) - ref).days > 14
