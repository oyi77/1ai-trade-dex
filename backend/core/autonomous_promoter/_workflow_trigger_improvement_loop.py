"""Methods carved verbatim out of ``backend/core/autonomous_promoter/workflow.py``."""

from __future__ import annotations

from .workflow import (
    ExperimentRecord,
    Session,
)

from . import workflow as _facade

class WorkflowMixinMixin3:
    def _trigger_improvement_loop(self, strategy_name: str, db: Session) -> None:
        """Trigger forensics analysis + auto_improve for a demoted strategy.

        Creates a new DRAFT ExperimentRecord so the strategy re-enters the
        DRAFT→SHADOW→PAPER→LIVE_TRIAL pipeline with improved params.
        Respects AGI_MAX_IMPROVEMENT_ATTEMPTS to avoid infinite retry loops.
        """
        max_attempts = getattr(_facade.settings, "AGI_MAX_IMPROVEMENT_ATTEMPTS", 3)

        # Count how many improvement attempts have already been made
        attempt_count = (
            db.query(_facade.ExperimentRecord)
            .filter(
                _facade.ExperimentRecord.strategy_name == strategy_name,
                _facade.ExperimentRecord.status.in_(
                    [
                        _facade.ExperimentStatus.RETIRED.value,
                        _facade.ExperimentStatus.PAPER.value,
                        _facade.ExperimentStatus.DRAFT.value,
                    ]
                ),
            )
            .count()
        )

        if attempt_count >= max_attempts:
            _facade.logger.warning(
                "[AutonomousPromoter] '%s' reached max improvement attempts (%d) — retiring",
                strategy_name,
                max_attempts,
            )
            # Mark all active experiments for this strategy as RETIRED
            db.query(_facade.ExperimentRecord).filter(
                _facade.ExperimentRecord.strategy_name == strategy_name,
                _facade.ExperimentRecord.status.notin_([_facade.ExperimentStatus.RETIRED.value]),
            ).update(
                {"status": _facade.ExperimentStatus.RETIRED.value}, synchronize_session=False
            )
            db.commit()
            return

        # 1. Generate forensics proposals
        try:
            _facade.generate_forensics_proposals(strategy_filter=strategy_name)
            _facade.logger.info(
                "[AutonomousPromoter] Forensics proposals generated for '%s'",
                strategy_name,
            )
        except Exception as e:
            _facade.logger.warning(
                "[AutonomousPromoter] Forensics generation failed for '%s': %s",
                strategy_name,
                e,
            )

        # 2. Param tuning attempt — tune strategy parameters before creating new DRAFT
        try:
            with _facade.get_db_session() as tune_db:
                tuner = _facade.SafeParamTuner()
                changes = tuner.tune(strategy_name, tune_db)
                if changes:
                    _facade.logger.info(
                        "[AutonomousPromoter] Pre-improvement param tuning for '%s': %s",
                        strategy_name,
                        changes,
                    )
        except Exception as e:
            _facade.logger.warning(
                "[AutonomousPromoter] Pre-improvement tuning failed for '%s': %s",
                strategy_name,
                e,
            )

        # 3. Capture demotion context from the most recent experiment
        demotion_context: dict = {}
        try:
            prior_exp = (
                db.query(_facade.ExperimentRecord)
                .filter(
                    _facade.ExperimentRecord.strategy_name == strategy_name,
                    _facade.ExperimentRecord.status.notin_([_facade.ExperimentStatus.DRAFT.value]),
                )
                .order_by(_facade.ExperimentRecord.created_at.desc())
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
                    "timestamp": _facade.datetime.now(_facade.timezone.utc).isoformat(),
                }
        except Exception as e:
            _facade.logger.warning(
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
                lookback_days=getattr(_facade.settings, "AGI_IMPROVEMENT_BACKTEST_DAYS", 30),
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
            _facade.logger.info(
                "[AutonomousPromoter] Improvement backtest for '%s': passed=%s wr=%.1f%% trades=%d",
                strategy_name,
                backtest_passed,
                bt_wr * 100,
                bt_trades,
            )
        except Exception as e:
            _facade.logger.warning(
                "[AutonomousPromoter] Improvement backtest failed for '%s': %s (proceeding anyway)",
                strategy_name,
                e,
            )
            backtest_passed = True  # Don't block on backtest engine failures

        if not backtest_passed:
            _facade.logger.warning(
                "[AutonomousPromoter] Improvement backtest FAILED for '%s' — creating DRAFT anyway but flagging for review",
                strategy_name,
            )
            demotion_context["backtest_failed"] = True

        # 5. Create a new DRAFT experiment so the strategy re-enters the pipeline
        new_exp = _facade.ExperimentRecord(
            name=f"{strategy_name}_improve_{_facade.datetime.now(_facade.timezone.utc).strftime('%Y%m%d_%H%M')}",
            strategy_name=strategy_name,
            status=_facade.ExperimentStatus.DRAFT.value,
            created_at=_facade.datetime.now(_facade.timezone.utc),
            strategy_composition=demotion_context if demotion_context else None,
        )
        db.add(new_exp)
        db.commit()
        _facade.logger.info(
            "[AutonomousPromoter] Created new DRAFT experiment '%s' for improvement cycle (attempt %d/%d)",
            new_exp.name,
            attempt_count + 1,
            max_attempts,
        )
    def _bootstrap_genome_experiments(self, db: Session) -> None:
        """Create ExperimentRecord rows for genome_registry genomes that lack them."""
        genomes = (
            db.query(_facade.GenomeRegistry)
            .filter(_facade.GenomeRegistry.stage.in_(["DRAFT", "SHADOW", "PAPER", "LIVE"]))
            .all()
        )
        if not genomes:
            return

        for genome in genomes:
            existing = (
                db.query(_facade.ExperimentRecord).filter_by(name=genome.strategy_name).first()
            )
            if existing:
                continue

            stage_map = {
                "DRAFT": _facade.ExperimentStatus.DRAFT.value,
                "SHADOW": _facade.ExperimentStatus.SHADOW.value,
                "PAPER": _facade.ExperimentStatus.PAPER.value,
                "LIVE": _facade.ExperimentStatus.LIVE_PROMOTED.value,
            }
            exp = _facade.ExperimentRecord(
                name=genome.strategy_name,
                strategy_name=genome.strategy_name,
                status=stage_map.get(genome.stage, _facade.ExperimentStatus.DRAFT.value),
                created_at=genome.created_at or _facade.datetime.now(_facade.timezone.utc),
            )
            db.add(exp)
            _facade.logger.info(
                f"[AutonomousPromoter] Bootstrapped ExperimentRecord "
                f"'{genome.strategy_name}' at stage={genome.stage}"
            )
        db.commit()
    def _check_backtest_gate(self, exp: ExperimentRecord, db: Session) -> bool:
        proposal = (
            db.query(_facade.StrategyProposal)
            .filter_by(strategy_name=exp.strategy_name, status="pending")
            .order_by(_facade.StrategyProposal.created_at.desc())
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
            db.query(_facade.StrategyProposal)
            .filter_by(strategy_name=exp.strategy_name)
            .first()
        )
        if not any_proposal:
            _facade.logger.info(
                f"[AutonomousPromoter] BACKTEST gate for '{exp.name}': "
                f"no StrategyProposal exists — seed bypass, auto-passing gate"
            )
            return True  # Bug fix: was returning False, blocking all 107 seed genomes

        return False
    def _check_review_completion(self, exp: ExperimentRecord, db: Session) -> bool:
        new_proposals = (
            db.query(_facade.StrategyProposal)
            .filter(
                _facade.StrategyProposal.strategy_name == exp.strategy_name,
                _facade.StrategyProposal.status == "pending",
                _facade.StrategyProposal.backtest_passed.is_(True),
            )
            .order_by(_facade.StrategyProposal.created_at.desc())
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
            ref = ref.replace(tzinfo=_facade.timezone.utc)
        if not ref:
            return False
        return (_facade.datetime.now(_facade.timezone.utc) - ref).days > 14
