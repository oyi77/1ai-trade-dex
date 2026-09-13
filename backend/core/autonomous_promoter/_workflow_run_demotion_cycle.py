"""Methods carved verbatim out of ``backend/core/autonomous_promoter/workflow.py``."""

from __future__ import annotations

from .workflow import (
    ExperimentRecord,
    Optional,
    Session,
)

from . import workflow as _facade

class WorkflowMixinMixin2:
    async def _run_demotion_cycle(
        self, db: Session, stats: dict[str, int], health_mon
    ) -> None:
        """Phases 4–5: Evaluate LIVE_TRIAL and LIVE_PROMOTED for demotion/degradation."""
        # ---- Phase 4: LIVE_TRIAL → LIVE_PROMOTED or → PAPER ----
        trials = (
            db.query(_facade.ExperimentRecord)
            .filter_by(status=_facade.ExperimentStatus.LIVE_TRIAL.value)
            .all()
        )
        for exp in trials:
            strategy_name = exp.strategy_name or exp.name
            promoted = exp.promoted_at or exp.created_at
            if promoted.tzinfo is None:
                promoted = promoted.replace(tzinfo=_facade.timezone.utc)
            trial_days = (_facade.datetime.now(_facade.timezone.utc) - promoted).days
            min_trial_days = getattr(_facade.settings, "AGI_LIVE_TRIAL_DAYS", 7)
            min_trial_trades = getattr(_facade.settings, "AGI_LIVE_TRIAL_MIN_TRADES", 10)

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
                exp.status = _facade.ExperimentStatus.PAPER.value
                exp.promoted_at = None
                db.add(exp)
                _facade.logger.warning(
                    f"[AutonomousPromoter] LIVE_TRIAL→PAPER (kill) '{exp.name}': wr={health.get('win_rate', 0):.1%}"
                )
                stats["demoted"] = stats.get("demoted", 0) + 1
                _facade.publish_event(
                    "strategy_demoted",
                    {
                        "strategy_name": strategy_name,
                        "from_stage": "LIVE_TRIAL",
                        "to_stage": "PAPER",
                        "reason": "health_killed",
                        "win_rate": health.get("win_rate", 0.0),
                        "sharpe": health.get("sharpe", 0.0),
                        "timestamp": _facade.datetime.now(_facade.timezone.utc).isoformat(),
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
                    exp.status = _facade.ExperimentStatus.LIVE_PROMOTED.value
                    exp.promoted_at = _facade.datetime.now(_facade.timezone.utc)
                    if _facade.settings.AGI_AUTO_ENABLE:
                        await self._enable_strategy(
                            strategy_name, db, experiment=exp
                        )
                    db.add(exp)
                    try:
                        _facade.publish_event(
                            "experiment_promoted",
                            {
                                "genome_id": exp.id,
                                "strategy_name": exp.strategy_name or exp.name,
                                "from_stage": "LIVE_TRIAL",
                                "to_stage": "LIVE_PROMOTED",
                                "win_rate": wr,
                                "sharpe": sharpe,
                                "timestamp": _facade.datetime.now(_facade.timezone.utc).isoformat(),
                            },
                        )
                    except Exception as e:
                        _facade.logger.warning(
                            f"[AutonomousPromoter] publish_event failed (non-fatal): {e}"
                        )
                    self._capture_promotion_review(
                        exp, db, "LIVE_TRIAL", "LIVE_PROMOTED", health
                    )
                    _facade.logger.info(
                        f"[AutonomousPromoter] LIVE_TRIAL→LIVE_PROMOTED '{exp.name}': wr={wr:.1%} sharpe={sharpe:.2f}"
                    )
                    stats["trial_to_live"] = stats.get("trial_to_live", 0) + 1
                else:
                    exp.status = _facade.ExperimentStatus.PAPER.value
                    exp.promoted_at = None
                    db.add(exp)
                    _facade.logger.warning(
                        f"[AutonomousPromoter] LIVE_TRIAL→PAPER (degraded) '{exp.name}': wr={wr:.1%} sharpe={sharpe:.2f}"
                    )
                    stats["demoted"] = stats.get("demoted", 0) + 1
                    _facade.publish_event(
                        "strategy_demoted",
                        {
                            "strategy_name": strategy_name,
                            "from_stage": "LIVE_TRIAL",
                            "to_stage": "PAPER",
                            "reason": "degraded",
                            "win_rate": wr,
                            "sharpe": sharpe,
                            "timestamp": _facade.datetime.now(_facade.timezone.utc).isoformat(),
                        },
                    )
                    self._trigger_improvement_loop(strategy_name, db)
        if trials:
            db.commit()

        # ---- Phase 5: LIVE_PROMOTED degradation → PAPER or REVIEW ----
        lives = (
            db.query(_facade.ExperimentRecord)
            .filter_by(status=_facade.ExperimentStatus.LIVE_PROMOTED.value)
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
                exp.status = _facade.ExperimentStatus.PAPER.value
                exp.promoted_at = None
                db.add(exp)
                _facade.logger.warning(
                    f"[AutonomousPromoter] LIVE_PROMOTED→PAPER (kill) '{exp.name}': "
                    f"wr={health.get('win_rate', 0):.1%}, sharpe={health.get('sharpe', 0):.2f}"
                )
                stats["demoted"] = stats.get("demoted", 0) + 1
                _facade.publish_event(
                    "strategy_demoted",
                    {
                        "strategy_name": strategy_name,
                        "from_stage": "LIVE_PROMOTED",
                        "to_stage": "PAPER",
                        "reason": "health_killed",
                        "win_rate": health.get("win_rate", 0.0),
                        "sharpe": health.get("sharpe", 0.0),
                        "timestamp": _facade.datetime.now(_facade.timezone.utc).isoformat(),
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
                exp.last_degradation_at = _facade.datetime.now(_facade.timezone.utc)
                if exp.degradation_count >= self.MAX_DEGRADATIONS_BEFORE_REVIEW:
                    exp.status = _facade.ExperimentStatus.REVIEW.value
                    exp.review_reason = (
                        f"Degraded: wr={wr:.1%} sharpe={sharpe:.2f} over {total_trades} trades "
                        f"({exp.degradation_count} degradation events)"
                    )
                    exp.degradation_count = 0
                    await self._disable_strategy(strategy_name, db)
                    _facade.publish_event(
                        "strategy_demoted",
                        {
                            "strategy_name": strategy_name,
                            "from_stage": "LIVE_PROMOTED",
                            "to_stage": "REVIEW",
                            "reason": "degraded",
                            "win_rate": wr,
                            "sharpe": sharpe,
                            "timestamp": _facade.datetime.now(_facade.timezone.utc).isoformat(),
                        },
                    )
                    _facade.logger.warning(
                        f"[AutonomousPromoter] LIVE→REVIEW '{exp.name}': {exp.review_reason}"
                    )
                else:
                    _facade.logger.warning(
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
        allowed = _facade.settings.LIVE_STRATEGY_ALLOWLIST
        if allowed and strategy_name not in allowed:
            _facade.logger.warning(
                f"[AutonomousPromoter] {strategy_name} NOT in LIVE_STRATEGY_ALLOWLIST, "
                f"skipping live promotion (allowed: {allowed})"
            )
            return

        config = db.query(_facade.StrategyConfig).filter_by(strategy_name=strategy_name).first()
        if config:
            config.enabled = True
            config.updated_at = _facade.utcnow()
            interval = config.interval_seconds or 60

            # Apply evolved params from experiment if available
            if experiment and experiment.strategy_composition:
                evolved_params = experiment.strategy_composition
                if isinstance(evolved_params, str):
                    try:
                        evolved_params = _facade._json.loads(evolved_params)
                    except (_facade._json.JSONDecodeError, TypeError):
                        evolved_params = {}
                # Strip internal evolver metadata
                evolved_params = {
                    k: v for k, v in evolved_params.items() if not k.startswith("_")
                }

                current_params = config.params or {}
                if isinstance(current_params, str):
                    try:
                        current_params = _facade._json.loads(current_params)
                    except (_facade._json.JSONDecodeError, TypeError):
                        current_params = {}

                merged = {**current_params, **evolved_params}
                config.params = merged
                _facade.logger.info(
                    f"[AutonomousPromoter] Applied evolved params to '{strategy_name}': "
                    f"merged {len(evolved_params)} param(s) into live config"
                )

            _facade.logger.info(
                f"[AutonomousPromoter] Enabled existing StrategyConfig '{strategy_name}' (interval={interval}s)"
            )
        else:
            # LIVE_STRATEGY_ALLOWLIST gate — also for new strategy creation
            if allowed and strategy_name not in allowed:
                _facade.logger.warning(
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
                        initial_params = _facade._json.loads(initial_params)
                    except (_facade._json.JSONDecodeError, TypeError):
                        initial_params = {}
                initial_params = {
                    k: v for k, v in initial_params.items() if not k.startswith("_")
                }

            config = _facade.StrategyConfig(
                strategy_name=strategy_name,
                enabled=True,
                interval_seconds=default_interval,
                mode="live",
                params=initial_params if initial_params else None,
            )
            db.add(config)
            interval = default_interval
            _facade.logger.info(
                f"[AutonomousPromoter] Created & enabled StrategyConfig '{strategy_name}' (interval={interval}s)"
            )
        db.commit()

        try:
            from backend.core.scheduling.scheduler import schedule_strategy

            schedule_strategy(strategy_name, interval, mode="live")
        except Exception as e:
            _facade.logger.warning(
                f"[AutonomousPromoter] Failed to dynamically schedule '{strategy_name}': {e}"
            )
    async def _disable_strategy(self, strategy_name: str, db: Session) -> None:
        config = db.query(_facade.StrategyConfig).filter_by(strategy_name=strategy_name).first()
        if config:
            _facade.disable_for_rehab(config)
            db.commit()
            _facade.logger.info(
                f"[AutonomousPromoter] Disabled StrategyConfig '{strategy_name}' (degradation fallback)"
            )
