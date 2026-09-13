"""Scheduled AGI improvement-cycle job (7 closed loops)."""

from __future__ import annotations

from loguru import logger

from backend.core import agi_orchestrator_errors as _errors
from backend.core.agi_orchestrator_errors import (
    ErrorType,
    classify_exception,
    _alert_permanent_failure,
    _record_transient_failure,
    _reset_circuit,
)


async def agi_improvement_cycle_job() -> None:
    """Scheduled job: runs the full closed-loop AGI improvement cycle.

    Errors are classified via :func:`classify_exception`:
      * BENIGN    — log a warning and continue running remaining stages.
      * TRANSIENT — log a warning, track consecutive failures, and re-raise
                    so the scheduler notes the failure; trips the circuit
                    breaker after :data:`_TRANSIENT_FAILURE_THRESHOLD`
                    consecutive failures.
      * PERMANENT — log at CRITICAL and re-raise immediately so the cycle
                    fails visibly (programming errors, missing modules, etc.).
    """
    if _errors._circuit_open:
        logger.warning(
            "[agi_improvement_cycle] circuit OPEN — skipping cycle until manually reset",
        )
        return

    stats = {
        "feedback_measured": 0,
        "meta_learned": 0,
        "evolution_variants": 0,
        "proposals_promoted": 0,
        "strategies_composed": 0,
        "strategies_replaced": 0,
        "counterfactual_scored": 0,
        "counterfactual_insights": 0,
        "errors": [],
        # Per-stage result tracking for observability (AGI-6)
        "stage_results": {
            "feedback": None,
            "meta_learning": None,
            "evolution": None,
            "promotion": None,
            "replacement": None,
            "composition": None,
            "counterfactual": None,
        },
    }

    try:
        from backend.ai.feedback_tracker import measure_recent_changes

        result = measure_recent_changes()
        stats["feedback_measured"] = result.get("measured", 0)
        stats["stage_results"]["feedback"] = "ok"
    except Exception as e:
        etype = classify_exception(e)
        stats["stage_results"]["feedback"] = f"error:{etype.value}"
        if etype == ErrorType.PERMANENT:
            logger.critical(
                "[agi_improvement_cycle] feedback stage PERMANENT failure: %s",
                e,
                exc_info=True,
            )
            _alert_permanent_failure("feedback", e)
            stats["errors"].append(f"feedback: {e}")
            raise
        elif etype == ErrorType.TRANSIENT:
            _record_transient_failure("feedback", e)
            stats["errors"].append(f"feedback: {e}")
            raise
        logger.warning(
            "[agi_improvement_cycle] feedback stage failed (BENIGN): %s",
            e,
            exc_info=True,
        )
        stats["errors"].append(f"feedback: {e}")

    try:
        from backend.ai.meta_learner import MetaLearner

        stats["meta_learned"] = MetaLearner().update_from_feedback()
        stats["stage_results"]["meta_learning"] = "ok"
    except Exception as e:
        etype = classify_exception(e)
        stats["stage_results"]["meta_learning"] = f"error:{etype.value}"
        if etype == ErrorType.PERMANENT:
            logger.critical(
                "[agi_improvement_cycle] meta_learn stage PERMANENT failure: %s",
                e,
                exc_info=True,
            )
            _alert_permanent_failure("meta_learning", e)
            stats["errors"].append(f"meta_learn: {e}")
            raise
        elif etype == ErrorType.TRANSIENT:
            _record_transient_failure("meta_learn", e)
            stats["errors"].append(f"meta_learn: {e}")
            raise
        logger.warning(
            "[agi_improvement_cycle] meta_learn stage failed (BENIGN): %s",
            e,
            exc_info=True,
        )
        stats["errors"].append(f"meta_learn: {e}")

    try:
        from backend.agents.autoresearch.evolver import StrategyEvolver

        stats["evolution_variants"] = len(StrategyEvolver().run_evolution_cycle())
        stats["stage_results"]["evolution"] = "ok"
    except Exception as e:
        etype = classify_exception(e)
        stats["stage_results"]["evolution"] = f"error:{etype.value}"
        if etype == ErrorType.PERMANENT:
            logger.critical(
                "[agi_improvement_cycle] evolution stage PERMANENT failure: %s",
                e,
                exc_info=True,
            )
            _alert_permanent_failure("evolution", e)
            stats["errors"].append(f"evolution: {e}")
            raise
        elif etype == ErrorType.TRANSIENT:
            _record_transient_failure("evolution", e)
            stats["errors"].append(f"evolution: {e}")
            raise
        logger.warning(
            "[agi_improvement_cycle] evolution stage failed (BENIGN): %s",
            e,
            exc_info=True,
        )
        stats["errors"].append(f"evolution: {e}")
    try:
        from backend.ai.proposal_generator import auto_promote_eligible_proposals

        auto_promote_eligible_proposals()
        from backend.models.database import StrategyProposal
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            stats["proposals_promoted"] = (
                db.query(StrategyProposal)
                .filter(StrategyProposal.admin_decision == "auto_approved")
                .count()
            )
        stats["stage_results"]["promotion"] = "ok"
    except Exception as e:
        etype = classify_exception(e)
        stats["stage_results"]["promotion"] = f"error:{etype.value}"
        if etype == ErrorType.PERMANENT:
            logger.critical(
                "[agi_improvement_cycle] proposals stage PERMANENT failure: %s",
                e,
                exc_info=True,
            )
            _alert_permanent_failure("promotion", e)
            stats["errors"].append(f"proposals: {e}")
            raise
        _record_transient_failure("proposals", e)
        stats["errors"].append(f"proposals: {e}")
        raise

    try:
        from backend.models.database import StrategyConfig, Trade
        from backend.models.outcome_tables import StrategyHealthRecord
        from backend.db.utils import get_db_session
        from sqlalchemy import func

        with get_db_session() as db:
            killed = (
                db.query(StrategyHealthRecord)
                .filter(
                    StrategyHealthRecord.status == "killed",
                )
                .all()
            )
            for hr in killed:
                config = (
                    db.query(StrategyConfig)
                    .filter(StrategyConfig.strategy_name == hr.strategy)
                    .first()
                )
                if config and config.enabled:
                    # ponytail: don't kill profitable strategies
                    total_pnl = (
                        db.query(func.coalesce(func.sum(Trade.pnl), 0.0))
                        .filter(
                            Trade.strategy == hr.strategy,
                            Trade.settled.is_(True),
                            Trade.pnl.isnot(None),
                        )
                        .scalar() or 0.0
                    )
                    if total_pnl > 0:
                        logger.info(
                            f"[agi_improvement_cycle] SKIP kill '{hr.strategy}' — "
                            f"profitable (PnL=${total_pnl:.2f})"
                        )
                        continue
                    from backend.core.strategy_health import disable_for_rehab

                    disable_for_rehab(config)
                    stats["strategies_replaced"] += 1
            if killed:
                db.commit()
        stats["stage_results"]["replacement"] = "ok"
    except Exception as e:
        etype = classify_exception(e)
        stats["stage_results"]["replacement"] = f"error:{etype.value}"
        if etype == ErrorType.PERMANENT:
            logger.critical(
                "[agi_improvement_cycle] replacement stage PERMANENT failure: %s",
                e,
                exc_info=True,
            )
            _alert_permanent_failure("replacement", e)
            stats["errors"].append(f"replacement: {e}")
            raise
        _record_transient_failure("replacement", e)
        stats["errors"].append(f"replacement: {e}")
        raise

    try:
        from backend.core.strategy_synthesizer import StrategySynthesizer
        from backend.core.agi_types import MarketRegime as _MR
        from backend.core.knowledge_graph import KnowledgeGraph
        from backend.db.utils import get_db_session

        _kg_ctx: dict = {}
        try:
            with get_db_session() as kg_db:
                _kg = KnowledgeGraph(session=kg_db)
                _kg_ctx = {
                    "recent_regimes": [
                        e.properties.get("value")
                        for e in _kg.query_by_type("regime", limit=5)
                        if e.properties.get("value")
                    ],
                    "best_strategies": [
                        e.properties for e in _kg.query_by_type("strategy", limit=5)
                    ],
                }
        except Exception as _kg_err:
            logger.debug(
                "[agi_improvement_cycle] KG context fetch failed (non-fatal): %s",
                _kg_err,
            )

        with get_db_session() as synth_db:
            synthesizer = StrategySynthesizer(session=synth_db)
            generated = await synthesizer.generate_strategy(
                description="New strategy for current market regime",
                regime=_MR.UNKNOWN,
                kg_context=_kg_ctx,
            )
            if generated.validation_passed:
                exp_id = synthesizer.register_generated(generated)
                stats["strategies_composed"] = 1
                stats["stage_results"]["composition"] = "ok"
                logger.info(
                    "[agi_improvement_cycle] Synthesized strategy '%s' passed all gates → SHADOW (exp_id=%s)",
                    generated.name,
                    exp_id,
                )
            else:
                stats["strategies_composed"] = 0
                failed_gates = [
                    k
                    for k, v in generated.gate_results.items()
                    if not v.get("passed", True)
                ]
                stats["stage_results"]["composition"] = f"gate_failed:{failed_gates}"
                logger.warning(
                    "[agi_improvement_cycle] Synthesized strategy '%s' failed gates: %s",
                    generated.name,
                    failed_gates,
                )
    except Exception as e:
        etype = classify_exception(e)
        stats["stage_results"]["composition"] = f"error:{etype.value}"
        if etype == ErrorType.PERMANENT:
            logger.critical(
                "[agi_improvement_cycle] composition stage PERMANENT failure: %s",
                e,
                exc_info=True,
            )
            _alert_permanent_failure("composition", e)
            stats["errors"].append(f"composition: {e}")
            raise
        _record_transient_failure("composition", e)
        stats["errors"].append(f"composition: {e}")
        raise

    try:
        from backend.ai.counterfactual_scorer import run_counterfactual_cycle

        cf_result = await run_counterfactual_cycle()
        stats["counterfactual_scored"] = cf_result.get("scoring", {}).get("scored", 0)
        stats["counterfactual_insights"] = cf_result.get("insights", {}).get(
            "insights", 0
        )
        stats["stage_results"]["counterfactual"] = "ok"
    except Exception as e:
        etype = classify_exception(e)
        stats["stage_results"]["counterfactual"] = f"error:{etype.value}"
        if etype == ErrorType.PERMANENT:
            logger.critical(
                "[agi_improvement_cycle] counterfactual stage PERMANENT failure: %s",
                e,
                exc_info=True,
            )
            _alert_permanent_failure("counterfactual", e)
            stats["errors"].append(f"counterfactual: {e}")
            raise
        elif etype == ErrorType.TRANSIENT:
            _record_transient_failure("counterfactual", e)
            stats["errors"].append(f"counterfactual: {e}")
            raise
        logger.warning(
            "[agi_improvement_cycle] counterfactual stage failed (BENIGN): %s",
            e,
            exc_info=True,
        )
        stats["errors"].append(f"counterfactual: {e}")

    if not stats["errors"]:
        _reset_circuit()
    else:
        logger.warning(
            "[agi_improvement_cycle] cycle completed with %d error(s)",
            len(stats["errors"]),
        )

    if len(stats["errors"]) >= 4:
        logger.critical(
            "[agi_improvement_cycle] %d/7 stages failed — AGI cycle may be non-functional",
            len(stats["errors"]),
        )
        if _errors._STATS_REPORT_CRITICAL_ERRORS:
            try:
                from backend.core.monitoring import ProductionMonitor
                from backend.db.utils import get_db_session

                with get_db_session() as db:
                    ProductionMonitor(db).send_alert(
                        severity="critical",
                        message=f"AGI cycle critical: {len(stats['errors'])}/7 stages failed",
                        details={"errors": stats["errors"]},
                    )
            except Exception:
                logger.exception(
                    "[agi_improvement_cycle] failed to send critical alert via ProductionMonitor"
                )

    logger.info(
        "[agi_improvement_cycle] feedback=%d meta=%d evolved=%d promoted=%d composed=%d replaced=%d cf_scored=%d errors=%d",
        stats["feedback_measured"],
        stats["meta_learned"],
        stats["evolution_variants"],
        stats["proposals_promoted"],
        stats["strategies_composed"],
        stats["strategies_replaced"],
        stats.get("counterfactual_scored", 0),
        len(stats["errors"]),
    )
