from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any

from backend.config import settings
from backend.core.event_bus import subscribe_handler, publish_event
from backend.db.utils import get_db_session
from backend.db.utils import utcnow

from loguru import logger

USE_EVENT_BUS_HANDLERS = getattr(settings, "USE_EVENT_BUS_HANDLERS", True)


def _handler_flag(name: str, default: bool = True) -> bool:
    if not USE_EVENT_BUS_HANDLERS:
        return False
    return getattr(settings, f"AGI_HANDLER_{name.upper()}_ENABLED", default)


async def on_trade_executed(event_type: str, data: Dict[str, Any]) -> None:
    await asyncio.sleep(0)  # yield control to event loop
    if not _handler_flag("trade_executed"):
        return
    strategy_name = data.get("strategy_name")
    trade_id = data.get("trade_id")
    genome_id = data.get("genome_id")
    logger.info(
        f"EVENT [trade_executed] strategy={strategy_name} trade_id={trade_id} genome={genome_id}"
    )
    if genome_id and trade_id:

        def _attribute():
            from backend.application.agi.performance_attributor import (
                attribute_trade_to_chromosomes,
            )
            from backend.models.database import GenomeRegistry, Trade

            with get_db_session() as db:
                trade = db.query(Trade).filter_by(id=trade_id).first()
                genome = db.query(GenomeRegistry).filter_by(genome_id=genome_id).first()
                if trade and genome and genome.chromosomes:
                    from backend.domain.genome.models import StrategyGenome

                    strategy_genome = StrategyGenome(
                        genome_id=genome.genome_id,
                        strategy_name=genome.strategy_name,
                        chromosomes=genome.chromosomes,
                    )
                    market_state = {"regime": "neutral"}
                    attribute_trade_to_chromosomes(trade, strategy_genome, market_state)
                    logger.info(
                        f"Performance attribution triggered for genome={genome_id}"
                    )

        try:
            await asyncio.to_thread(_attribute)
        except Exception as exc:
            logger.error(
                f"Handler trade_executed attribution failed: {exc}", exc_info=True
            )


async def on_trade_settled(event_type: str, data: Dict[str, Any]) -> None:
    await asyncio.sleep(0)  # noqa: F823 — yield control to event loop
    if not _handler_flag("trade_settled"):
        return
    strategy_name = data.get("strategy_name")
    result = data.get("result")
    pnl = data.get("pnl", 0.0)
    mode = data.get("trading_mode", "paper")
    genome_id = data.get("genome_id")
    logger.info(
        f"EVENT [trade_settled] strategy={strategy_name} result={result} pnl={pnl} mode={mode}"
    )
    try:
        from backend.core.agi_goal_engine import AGIGoalEngine

        def _goal_engine():
            engine = AGIGoalEngine()
            engine.handle_regime_change(
                {
                    "strategy_name": strategy_name,
                    "result": result,
                    "pnl": pnl,
                }
            )

        await asyncio.to_thread(_goal_engine)
    except Exception as exc:
        logger.error(f"Handler trade_settled goal_engine failed: {exc}", exc_info=True)
    if result == "loss":

        def _forensics():
            from backend.core.forensics_integration import generate_forensics_proposals

            with get_db_session() as db:
                generate_forensics_proposals(db=db)
                db.commit()

        try:
            await asyncio.to_thread(_forensics)
        except Exception as exc:
            logger.error(
                f"Handler trade_settled forensics failed: {exc}", exc_info=True
            )
    if mode in ("shadow", "paper") and genome_id:
        try:
            from backend.core.autonomous_promoter import autonomous_promoter

            asyncio.create_task(autonomous_promoter.run_once())
        except Exception as exc:
            logger.error(f"Handler trade_settled promoter failed: {exc}", exc_info=True)


def on_trade_rejected(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("trade_rejected"):
        return
    strategy_name = data.get("strategy_name")
    reason = data.get("reason")
    logger.info(f"EVENT [trade_rejected] strategy={strategy_name} reason={reason}")
    if reason and "risk" in str(reason).lower():
        logger.info(
            f"Risk rejection tracked for {strategy_name} — will decay confidence if repeated"
        )


async def on_strategy_killed(event_type: str, data: Dict[str, Any]) -> None:
    await asyncio.sleep(0)  # yield control to event loop
    if not _handler_flag("strategy_killed"):
        return
    strategy_name = data.get("strategy_name")
    reason = data.get("reason")
    logger.info(f"EVENT [strategy_killed] strategy={strategy_name} reason={reason}")

    def _necromancy():
        from backend.application.agi.necromancer import run_necromancy_analysis

        with get_db_session() as db:
            report = run_necromancy_analysis(db)
            db.commit()
            return report

    try:
        report = await asyncio.to_thread(_necromancy)
        publish_event(
            "necromancy_report",
            {
                "death_causes": (
                    report.death_causes if hasattr(report, "death_causes") else []
                ),
                "high_risk_genes": (
                    len(report.high_risk_genes)
                    if hasattr(report, "high_risk_genes")
                    else 0
                ),
                "legend_genes": (
                    len(report.legend_genes) if hasattr(report, "legend_genes") else 0
                ),
            },
        )
    except Exception as exc:
        logger.error(f"Handler strategy_killed necromancy failed: {exc}", exc_info=True)

    def _graveyard():
        from backend.models.database import GenomeRegistry

        with get_db_session() as db:
            genome = (
                db.query(GenomeRegistry)
                .filter_by(strategy_name=strategy_name)
                .order_by(GenomeRegistry.created_at.desc())
                .first()
            )
            if genome and genome.stage != "GRAVEYARD":
                genome.stage = "GRAVEYARD"
                genome.updated_at = utcnow()
                db.commit()
                return genome
        return None

    try:
        genome = await asyncio.to_thread(_graveyard)
        if genome:
            publish_event(
                "lifecycle_transition",
                {
                    "genome_id": genome.genome_id,
                    "strategy_name": strategy_name,
                    "from_stage": "LIVE",
                    "to_stage": "GRAVEYARD",
                    "reason": reason,
                },
            )
            logger.info(f"Moved genome {genome.genome_id} to GRAVEYARD")
    except Exception as exc:
        logger.error(f"Handler strategy_killed lifecycle failed: {exc}", exc_info=True)

    # Create DRAFT experiment so AutonomousPromoter tracks rehab pipeline
    def _create_draft():
        from backend.models.database import ExperimentRecord
        from backend.agi_types import ExperimentStatus

        with get_db_session() as db:
            existing = (
                db.query(ExperimentRecord)
                .filter_by(
                    strategy_name=strategy_name,
                    status=(
                        ExperimentStatus.DRAFT.value
                        if hasattr(ExperimentStatus.DRAFT, "value")
                        else "DRAFT"
                    ),
                )
                .first()
            )
            if existing:
                return None
            draft = ExperimentRecord(
                strategy_name=strategy_name,
                status="DRAFT",
                created_at=datetime.now(timezone.utc),
                notes=f"Auto-created after kill: {reason}",
            )
            db.add(draft)
            db.commit()
            return draft

    try:
        draft = await asyncio.to_thread(_create_draft)
        if draft:
            logger.info(
                f"Created DRAFT experiment for killed strategy '{strategy_name}'"
            )
    except Exception as exc:
        logger.error(
            f"Handler strategy_killed draft creation failed: {exc}", exc_info=True
        )


async def on_experiment_promoted(event_type: str, data: Dict[str, Any]) -> None:
    await asyncio.sleep(0)  # noqa: F823 — yield control to event loop
    if not _handler_flag("experiment_promoted"):
        return
    genome_id = data.get("genome_id")
    strategy_name = data.get("strategy_name")
    to_stage = data.get("to_stage")
    logger.info(f"EVENT [experiment_promoted] genome={genome_id} to_stage={to_stage}")
    try:
        from backend.core.wallet.bankroll_allocator import BankrollAllocator

        allocator = BankrollAllocator()
        asyncio.create_task(allocator.run_once())
    except Exception as exc:
        logger.error(
            f"Handler experiment_promoted bankroll failed: {exc}", exc_info=True
        )
    if to_stage == "LIVE" and getattr(settings, "AGI_AUTO_ENABLE", False):

        def _auto_enable():
            from backend.models.database import StrategyConfig

            with get_db_session() as db:
                cfg = (
                    db.query(StrategyConfig)
                    .filter_by(strategy_name=strategy_name)
                    .first()
                )
                if cfg and not cfg.enabled:
                    cfg.enabled = True
                    db.commit()
                    logger.info(
                        f"Auto-enabled strategy {strategy_name} after LIVE promotion"
                    )

        try:
            await asyncio.to_thread(_auto_enable)
        except Exception as exc:
            logger.error(
                f"Handler experiment_promoted auto_enable failed: {exc}", exc_info=True
            )


async def on_chromosome_flagged(event_type: str, data: Dict[str, Any]) -> None:
    await asyncio.sleep(0)  # yield control to event loop
    if not _handler_flag("chromosome_flagged"):
        return
    genome_id = data.get("genome_id")
    chrom_name = data.get("chromosome")
    avg_score = data.get("avg_score", "N/A")
    logger.info(
        f"EVENT [chromosome_flagged] genome={genome_id} chrom={chrom_name} avg_score={avg_score}"
    )

    def _mutate():
        from backend.application.agi.evolution_jobs import targeted_mutation

        with get_db_session() as db:
            targeted_mutation(genome_id=genome_id, chrom_name=chrom_name, db=db)
            db.commit()

    try:
        await asyncio.to_thread(_mutate)
        logger.info(f"Targeted mutation applied: genome={genome_id} chrom={chrom_name}")
    except Exception as exc:
        logger.warning(f"Targeted mutation failed for genome={genome_id}: {exc}")
        logger.error(f"Handler chromosome_flagged failed: {exc}", exc_info=True)


async def on_mutation_proposed(event_type: str, data: Dict[str, Any]) -> None:
    await asyncio.sleep(0)  # yield control to event loop
    if not _handler_flag("mutation_proposed"):
        return
    strategy_name = data.get("strategy_name")
    root_cause = data.get("root_cause")
    logger.info(
        f"EVENT [mutation_proposed] strategy={strategy_name} cause={root_cause}"
    )

    def _forensics():
        from backend.core.forensics_integration import generate_forensics_proposals

        with get_db_session() as db:
            generate_forensics_proposals(db=db)
            db.commit()

    try:
        await asyncio.to_thread(_forensics)
        logger.info(f"Forensics proposals generated for {strategy_name}")
    except Exception as exc:
        logger.error(
            f"Handler mutation_proposed forensics failed: {exc}", exc_info=True
        )


async def on_regime_shift(event_type: str, data: Dict[str, Any]) -> None:
    await asyncio.sleep(0)  # yield control to event loop
    if not _handler_flag("regime_shift"):
        return
    new_regime = data.get("new_regime")
    old_regime = data.get("old_regime", "unknown")
    logger.info(f"EVENT [regime_shift] {old_regime}→{new_regime}")

    def _rebalance():
        from backend.application.agi.regime_population_manager import (
            detect_regime_and_rebalance,
        )

        with get_db_session() as db:
            detect_regime_and_rebalance(db)

    try:
        await asyncio.to_thread(_rebalance)
    except Exception as exc:
        logger.error(f"Handler regime_shift rebalance failed: {exc}", exc_info=True)
    try:
        from backend.core.agi_goal_engine import AGIGoalEngine
        from backend.core.agi_types import MarketRegime

        def _goal_transition():
            engine = AGIGoalEngine()
            try:
                to_r = (
                    MarketRegime(new_regime)
                    if isinstance(new_regime, str)
                    else new_regime
                )
            except ValueError:
                to_r = MarketRegime.UNKNOWN
            transition = {
                "from_regime": old_regime,
                "to_regime": to_r,
            }
            engine.handle_regime_change(transition)

        await asyncio.to_thread(_goal_transition)
    except Exception as exc:
        logger.error(f"Handler regime_shift goal_engine failed: {exc}", exc_info=True)


async def on_signal_found(event_type: str, data: Dict[str, Any]) -> None:
    """Handle signal_found events: log and persist to KnowledgeGraph for downstream analysis."""
    await asyncio.sleep(0)  # yield control to event loop
    if not _handler_flag("signal_found"):
        return
    market_ticker = data.get("market_ticker")
    direction = data.get("direction")
    confidence = data.get("confidence")
    strategy_name = data.get("strategy_name")
    logger.info(
        f"EVENT [signal_found] market={market_ticker} dir={direction} "
        f"conf={confidence} strategy={strategy_name}"
    )
    try:
        from backend.core.knowledge_graph import KnowledgeGraph

        def _kg_signal():
            kg = KnowledgeGraph()
            kg.add_entity(
                "signal",
                f"signal:{market_ticker}",
                {
                    "market_ticker": market_ticker,
                    "direction": direction,
                    "confidence": confidence,
                    "strategy_name": strategy_name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        await asyncio.to_thread(_kg_signal)
    except Exception as exc:
        logger.error(f"Handler signal_found KG failed: {exc}", exc_info=True)


async def on_genome_promoted(event_type: str, data: Dict[str, Any]) -> None:
    await asyncio.sleep(0)  # yield control to event loop
    if not _handler_flag("genome_promoted"):
        return
    await on_experiment_promoted(event_type, data)


async def on_lifecycle_transition(event_type: str, data: Dict[str, Any]) -> None:
    await asyncio.sleep(0)  # yield control to event loop
    if not _handler_flag("lifecycle_transition"):
        return
    to_stage = data.get("to_stage")
    logger.info(f"EVENT [lifecycle_transition] {data.get('genome_id')}→{to_stage}")
    if to_stage in ("PAPER", "LIVE"):
        await on_experiment_promoted(event_type, data)


async def on_evolution_action(event_type: str, data: Dict[str, Any]) -> None:
    await asyncio.sleep(0)  # yield control to event loop
    if not _handler_flag("evolution_action"):
        return
    logger.info(
        f"EVENT [evolution_action] type={data.get('action_type')} genome={data.get('genome_id')}"
    )
    try:
        from backend.core.knowledge_graph import KnowledgeGraph

        def _kg_evolution():
            kg = KnowledgeGraph()
            kg.add_entity("evolution", f"evolution:{data.get('genome_id')}", data)

        await asyncio.to_thread(_kg_evolution)
    except Exception as exc:
        logger.error(f"Handler evolution_action KG failed: {exc}", exc_info=True)


async def on_synthesis_priors_updated(event_type: str, data: Dict[str, Any]) -> None:
    await asyncio.sleep(0)  # yield control to event loop
    if not _handler_flag("synthesis_priors_updated"):
        return
    logger.info(
        f"EVENT [synthesis_priors_updated] prefer={len(data.get('prefer', []))} avoid={len(data.get('avoid', []))}"
    )
    try:
        from backend.core.knowledge_graph import KnowledgeGraph

        def _kg_priors():
            kg = KnowledgeGraph()
            kg.add_entity("synthesis", "priors:latest", data)

        await asyncio.to_thread(_kg_priors)
    except Exception as exc:
        logger.error(f"Handler synthesis_priors_updated failed: {exc}", exc_info=True)


def on_risk_manager_updated(event_type: str, data: Dict[str, Any]) -> None:
    """Log-only handler: no downstream action needed for risk_manager_updated events yet."""
    if not _handler_flag("risk_manager_updated"):
        return
    logger.info(f"EVENT [risk_manager_updated] rules={len(data.get('new_rules', []))}")


async def on_necromancy_report(event_type: str, data: Dict[str, Any]) -> None:
    await asyncio.sleep(0)  # yield control to event loop
    if not _handler_flag("necromancy_report"):
        return
    logger.info(f"EVENT [necromancy_report] deaths={len(data.get('death_causes', []))}")
    try:
        from backend.core.knowledge_graph import KnowledgeGraph

        def _kg_necro():
            kg = KnowledgeGraph()
            kg.add_entity("necromancy", "report:latest", data)

        await asyncio.to_thread(_kg_necro)
    except Exception as exc:
        logger.error(f"Handler necromancy_report failed: {exc}", exc_info=True)


async def on_nightly_review_complete(event_type: str, data: Dict[str, Any]) -> None:
    await asyncio.sleep(0)  # yield control to event loop
    if not _handler_flag("nightly_review_complete"):
        return
    logger.info(f"[NightlyReviewKG] Review complete: {data.get('date')}")
    try:
        from backend.core.knowledge_graph import KnowledgeGraph

        def _kg_review():
            kg = KnowledgeGraph()
            date_str = data.get("date")
            review_id = f"review:{date_str}"
            properties = {
                "file_path": data.get("file_path"),
                "date": date_str,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            kg.add_entity("nightly_review", review_id, properties)
            kg.add_entity("system", "system", {"name": "Polyedge Core"})
            kg.add_relation("system", review_id, "HAS_REVIEW", 1.0, 1.0)

        await asyncio.to_thread(_kg_review)
    except Exception as exc:
        logger.error(f"Handler nightly_review_complete failed: {exc}", exc_info=True)


def on_archetype_allocation_changed(event_type: str, data: Dict[str, Any]) -> None:
    """Log-only handler: no downstream action needed for archetype_allocation_changed events yet."""
    if not _handler_flag("archetype_allocation_changed"):
        return
    logger.info(
        f"EVENT [archetype_allocation_changed] regime={data.get('regime')} archetypes={data.get('archetypes')}"
    )


async def on_strategy_demoted(event_type: str, data: Dict[str, Any]) -> None:
    """Handle strategy_demoted events: trigger AGI improvement cycle for demoted strategy."""
    await asyncio.sleep(0)  # yield control to event loop
    if not _handler_flag("strategy_demoted"):
        return
    strategy_name = data.get("strategy_name")
    from_stage = data.get("from_stage")
    to_stage = data.get("to_stage")
    reason = data.get("reason")
    logger.info(
        f"EVENT [strategy_demoted] strategy={strategy_name} "
        f"{from_stage}→{to_stage} reason={reason}"
    )
    # Trigger AGI improvement cycle for the demoted strategy
    try:
        from backend.core.agi_self_tuner import get_agi_self_tuner

        # evaluate_and_tune is async, so we can't use to_thread for the whole block.
        # Wrap only the sync DB session setup in to_thread, keep await for async tuner.
        def _get_db():
            return get_db_session()

        db = await asyncio.to_thread(_get_db)
        try:
            tuner = get_agi_self_tuner()
            await tuner.evaluate_and_tune(strategy_name, db)
            logger.info(
                f"[strategy_demoted] Self-tune triggered for '{strategy_name}' after demotion"
            )
        finally:
            await asyncio.to_thread(db.close)
    except Exception as exc:
        logger.error(f"Handler strategy_demoted self_tune failed: {exc}", exc_info=True)
    # Store demotion context in KnowledgeGraph for analysis
    try:
        from backend.core.knowledge_graph import KnowledgeGraph

        def _kg_demotion():
            kg = KnowledgeGraph()
            kg.add_entity(
                "demotion",
                f"demotion:{strategy_name}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
                {
                    "strategy_name": strategy_name,
                    "from_stage": from_stage,
                    "to_stage": to_stage,
                    "reason": reason,
                    "win_rate": data.get("win_rate"),
                    "sharpe": data.get("sharpe"),
                    "timestamp": data.get("timestamp"),
                },
            )

        await asyncio.to_thread(_kg_demotion)
    except Exception as exc:
        logger.error(f"Handler strategy_demoted KG failed: {exc}", exc_info=True)


REGISTRY: Dict[str, Any] = {
    "trade_executed": on_trade_executed,
    "trade_settled": on_trade_settled,
    "trade_rejected": on_trade_rejected,
    "strategy_killed": on_strategy_killed,
    "experiment_promoted": on_experiment_promoted,
    "chromosome_flagged": on_chromosome_flagged,
    "mutation_proposed": on_mutation_proposed,
    "regime_shift": on_regime_shift,
    "signal_found": on_signal_found,
    "genome_promoted": on_genome_promoted,
    "lifecycle_transition": on_lifecycle_transition,
    "evolution_action": on_evolution_action,
    "synthesis_priors_updated": on_synthesis_priors_updated,
    "risk_manager_updated": on_risk_manager_updated,
    "necromancy_report": on_necromancy_report,
    "archetype_allocation_changed": on_archetype_allocation_changed,
    "nightly_review_complete": on_nightly_review_complete,
    "strategy_demoted": on_strategy_demoted,
}


def register_agi_event_handlers() -> None:
    if not USE_EVENT_BUS_HANDLERS:
        logger.info(
            "AGI event handlers DISABLED (USE_EVENT_BUS_HANDLERS=false). Scheduler jobs remain primary."
        )
        return
    for event_type, handler in REGISTRY.items():
        subscribe_handler(event_type, handler)
        logger.info(f"AGI handler registered: {event_type} -> {handler.__name__}")
    logger.info(f"AGI event handlers registered: {len(REGISTRY)} handlers active")


def check_agi_health() -> Dict[str, Any]:
    return {
        "handlers_registered": len(REGISTRY),
        "event_types": list(REGISTRY.keys()),
        "use_event_bus_handlers": USE_EVENT_BUS_HANDLERS,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
