from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Any

from backend.config import settings
from backend.core.event_bus import subscribe_handler, publish_event

logger = logging.getLogger("trading_bot.agi_events")

USE_EVENT_BUS_HANDLERS = getattr(settings, "USE_EVENT_BUS_HANDLERS", True)


def _handler_flag(name: str, default: bool = True) -> bool:
    if not USE_EVENT_BUS_HANDLERS:
        return False
    return getattr(settings, f"AGI_HANDLER_{name.upper()}_ENABLED", default)


def _get_db():
    from backend.models.database import SessionLocal
    return SessionLocal()


async def on_trade_executed(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("trade_executed"):
        return
    strategy_name = data.get("strategy_name")
    trade_id = data.get("trade_id")
    genome_id = data.get("genome_id")
    logger.info(f"EVENT [trade_executed] strategy={strategy_name} trade_id={trade_id} genome={genome_id}")
    if genome_id and trade_id:
        try:
            from backend.application.agi.performance_attributor import attribute_trade_to_chromosomes
            from backend.models.database import GenomeRegistry, Trade
            db = _get_db()
            try:
                trade = db.query(Trade).filter_by(id=trade_id).first()
                genome = db.query(GenomeRegistry).filter_by(genome_id=genome_id).first()
                if trade and genome and genome.chromosomes_json:
                    import json
                    try:
                        chromosomes = json.loads(genome.chromosomes_json)
                    except json.JSONDecodeError:
                        chromosomes = {}
                    from backend.domain.genome.models import StrategyGenome
                    try:
                        strategy_genome = StrategyGenome(
                            genome_id=genome.genome_id,
                            strategy_name=genome.strategy_name,
                            chromosomes=chromosomes,
                        )
                        market_state = {"regime": "neutral"}
                        attribute_trade_to_chromosomes(trade, strategy_genome, market_state)
                        logger.info(f"Performance attribution triggered for genome={genome_id}")
                    except Exception:
                        pass
            except Exception:
                pass
            finally:
                db.close()
        except Exception as exc:
            logger.error(f"Handler trade_executed attribution failed: {exc}", exc_info=True)


async def on_trade_settled(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("trade_settled"):
        return
    strategy_name = data.get("strategy_name")
    result = data.get("result")
    pnl = data.get("pnl", 0.0)
    mode = data.get("trading_mode", "paper")
    genome_id = data.get("genome_id")
    logger.info(f"EVENT [trade_settled] strategy={strategy_name} result={result} pnl={pnl} mode={mode}")
    try:
        from backend.core.agi_goal_engine import AGIGoalEngine
        engine = AGIGoalEngine()
        engine.handle_regime_change({
            "strategy_name": strategy_name,
            "result": result,
            "pnl": pnl,
        })
    except Exception as exc:
        logger.error(f"Handler trade_settled goal_engine failed: {exc}", exc_info=True)
    if result == "loss":
        try:
            from backend.core.forensics_integration import generate_forensics_proposals
            db = _get_db()
            try:
                generate_forensics_proposals(db=db)
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.error(f"Handler trade_settled forensics failed: {exc}", exc_info=True)
    if mode in ("shadow", "paper") and genome_id:
        try:
            from backend.core.autonomous_promoter import autonomous_promoter
            import asyncio
            asyncio.create_task(autonomous_promoter.run_once())
        except Exception as exc:
            logger.error(f"Handler trade_settled promoter failed: {exc}", exc_info=True)


async def on_trade_rejected(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("trade_rejected"):
        return
    strategy_name = data.get("strategy_name")
    reason = data.get("reason")
    logger.info(f"EVENT [trade_rejected] strategy={strategy_name} reason={reason}")
    if reason and "risk" in str(reason).lower():
        logger.info(f"Risk rejection tracked for {strategy_name} — will decay confidence if repeated")


async def on_strategy_killed(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("strategy_killed"):
        return
    strategy_name = data.get("strategy_name")
    reason = data.get("reason")
    logger.info(f"EVENT [strategy_killed] strategy={strategy_name} reason={reason}")
    try:
        from backend.application.agi.necromancer import run_necromancy_analysis
        db = _get_db()
        try:
            report = run_necromancy_analysis(db)
            db.commit()
            publish_event("necromancy_report", {
                "death_causes": report.death_causes if hasattr(report, "death_causes") else [],
                "high_risk_genes": len(report.high_risk_genes) if hasattr(report, "high_risk_genes") else 0,
                "legend_genes": len(report.legend_genes) if hasattr(report, "legend_genes") else 0,
            })
        finally:
            db.close()
    except Exception as exc:
        logger.error(f"Handler strategy_killed necromancy failed: {exc}", exc_info=True)
    try:
        from backend.models.database import GenomeRegistry
        db = _get_db()
        try:
            genome = db.query(GenomeRegistry).filter_by(strategy_name=strategy_name).order_by(GenomeRegistry.created_at.desc()).first()
            if genome and genome.stage != "GRAVEYARD":
                genome.stage = "GRAVEYARD"
                genome.updated_at = datetime.now(timezone.utc)
                db.commit()
                publish_event("lifecycle_transition", {
                    "genome_id": genome.genome_id,
                    "strategy_name": strategy_name,
                    "from_stage": "LIVE",
                    "to_stage": "GRAVEYARD",
                    "reason": reason,
                })
                logger.info(f"Moved genome {genome.genome_id} to GRAVEYARD")
        finally:
            db.close()
    except Exception as exc:
        logger.error(f"Handler strategy_killed lifecycle failed: {exc}", exc_info=True)


async def on_experiment_promoted(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("experiment_promoted"):
        return
    genome_id = data.get("genome_id")
    strategy_name = data.get("strategy_name")
    to_stage = data.get("to_stage")
    logger.info(f"EVENT [experiment_promoted] genome={genome_id} to_stage={to_stage}")
    try:
        from backend.core.bankroll_allocator import BankrollAllocator
        allocator = BankrollAllocator()
        import asyncio
        asyncio.create_task(allocator.run_once())
    except Exception as exc:
        logger.error(f"Handler experiment_promoted bankroll failed: {exc}", exc_info=True)
    if to_stage == "LIVE" and getattr(settings, "AGI_AUTO_ENABLE", False):
        try:
            db = _get_db()
            try:
                from backend.models.database import StrategyConfig
                cfg = db.query(StrategyConfig).filter_by(strategy_name=strategy_name).first()
                if cfg and not cfg.enabled:
                    cfg.enabled = True
                    db.commit()
                    logger.info(f"Auto-enabled strategy {strategy_name} after LIVE promotion")
            finally:
                db.close()
        except Exception as exc:
            logger.error(f"Handler experiment_promoted auto_enable failed: {exc}", exc_info=True)


async def on_chromosome_flagged(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("chromosome_flagged"):
        return
    genome_id = data.get("genome_id")
    chrom_name = data.get("chromosome")
    avg_score = data.get("avg_score", "N/A")
    logger.info(f"EVENT [chromosome_flagged] genome={genome_id} chrom={chrom_name} avg_score={avg_score}")
    try:
        from backend.application.agi.evolution_jobs import targeted_mutation
        db = _get_db()
        try:
            targeted_mutation(genome_id=genome_id, chrom_name=chrom_name, db=db)
            db.commit()
            logger.info(f"Targeted mutation applied: genome={genome_id} chrom={chrom_name}")
        except Exception as exc:
            logger.warning(f"Targeted mutation failed for genome={genome_id}: {exc}")
        finally:
            db.close()
    except Exception as exc:
        logger.error(f"Handler chromosome_flagged failed: {exc}", exc_info=True)


async def on_mutation_proposed(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("mutation_proposed"):
        return
    strategy_name = data.get("strategy_name")
    root_cause = data.get("root_cause")
    logger.info(f"EVENT [mutation_proposed] strategy={strategy_name} cause={root_cause}")
    try:
        from backend.core.forensics_integration import generate_forensics_proposals
        db = _get_db()
        try:
            generate_forensics_proposals(db=db)
            db.commit()
            logger.info(f"Forensics proposals generated for {strategy_name}")
        finally:
            db.close()
    except Exception as exc:
        logger.error(f"Handler mutation_proposed forensics failed: {exc}", exc_info=True)


async def on_regime_shift(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("regime_shift"):
        return
    new_regime = data.get("new_regime")
    old_regime = data.get("old_regime", "unknown")
    logger.info(f"EVENT [regime_shift] {old_regime}→{new_regime}")
    try:
        from backend.application.agi.regime_population_manager import detect_regime_and_rebalance
        db = _get_db()
        try:
            detect_regime_and_rebalance(db)
            db.commit()
        except Exception:
            pass
        finally:
            db.close()
    except Exception as exc:
        logger.error(f"Handler regime_shift rebalance failed: {exc}", exc_info=True)
    try:
        from backend.core.agi_goal_engine import AGIGoalEngine
        from backend.core.agi_types import MarketRegime
        engine = AGIGoalEngine()
        try:
            to_regime = MarketRegime(new_regime) if isinstance(new_regime, str) else new_regime
        except ValueError:
            to_regime = MarketRegime.UNKNOWN
        transition = {
            "from_regime": old_regime,
            "to_regime": to_regime,
        }
        engine.handle_regime_change(transition)
    except Exception as exc:
        logger.error(f"Handler regime_shift goal_engine failed: {exc}", exc_info=True)


async def on_signal_found(event_type: str, data: Dict[str, Any]) -> None:
    pass


async def on_genome_promoted(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("genome_promoted"):
        return
    await on_experiment_promoted(event_type, data)


async def on_lifecycle_transition(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("lifecycle_transition"):
        return
    to_stage = data.get("to_stage")
    logger.info(f"EVENT [lifecycle_transition] {data.get('genome_id')}→{to_stage}")
    if to_stage in ("PAPER", "LIVE"):
        await on_experiment_promoted(event_type, data)


async def on_evolution_action(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("evolution_action"):
        return
    logger.info(f"EVENT [evolution_action] type={data.get('action_type')} genome={data.get('genome_id')}")
    try:
        from backend.core.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        kg.add_entity("evolution", f"evolution:{data.get('genome_id')}", data)
    except Exception as exc:
        logger.error(f"Handler evolution_action KG failed: {exc}", exc_info=True)


async def on_synthesis_priors_updated(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("synthesis_priors_updated"):
        return
    logger.info(f"EVENT [synthesis_priors_updated] prefer={len(data.get('prefer', []))} avoid={len(data.get('avoid', []))}")
    try:
        from backend.core.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        kg.add_entity("synthesis", "priors:latest", data)
    except Exception as exc:
        logger.error(f"Handler synthesis_priors_updated failed: {exc}", exc_info=True)


async def on_risk_manager_updated(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("risk_manager_updated"):
        return
    logger.info(f"EVENT [risk_manager_updated] rules={len(data.get('new_rules', []))}")


async def on_necromancy_report(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("necromancy_report"):
        return
    logger.info(f"EVENT [necromancy_report] deaths={len(data.get('death_causes', []))}")
    try:
        from backend.core.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        kg.add_entity("necromancy", "report:latest", data)
    except Exception as exc:
        logger.error(f"Handler necromancy_report failed: {exc}", exc_info=True)


async def on_archetype_allocation_changed(event_type: str, data: Dict[str, Any]) -> None:
    if not _handler_flag("archetype_allocation_changed"):
        return
    logger.info(f"EVENT [archetype_allocation_changed] regime={data.get('regime')} archetypes={data.get('archetypes')}")


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
}


def register_agi_event_handlers() -> None:
    if not USE_EVENT_BUS_HANDLERS:
        logger.info("AGI event handlers DISABLED (USE_EVENT_BUS_HANDLERS=false). Scheduler jobs remain primary.")
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
