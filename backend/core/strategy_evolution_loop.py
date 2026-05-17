"""Strategy Evolution Loop — automated scan -> disable -> enable -> create cycle.

Connects existing AGI pieces (strategy_health, forensics_integration,
strategy_rehabilitator) into a single scheduled job that runs the full
closed-loop strategy evolution cycle.

Called by APScheduler every AGI_IMPROVEMENT_CYCLE_INTERVAL_HOURS.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger


async def strategy_evolution_loop() -> dict[str, Any]:
    """Run the full strategy evolution cycle.

    Steps:
    1. Health scan — assess all active strategies, kill losers
    2. Forensics — generate proposals for loss patterns
    3. Rehabilitation — re-enable disabled strategies that recovered
    4. Variant creation — trigger evolution for winning strategies

    Returns stats dict for logging/monitoring.
    """
    stats: dict[str, Any] = {
        "strategies_scanned": 0,
        "strategies_killed": 0,
        "forensics_proposals": 0,
        "strategies_rehabilitated": 0,
        "winners_evolved": 0,
        "errors": [],
    }

    # Step 1: Health scan — assess all active strategies
    try:
        from backend.core.strategy_health import StrategyHealthMonitor
        from backend.models.database import StrategyConfig
        from backend.db.utils import get_db_session

        monitor = StrategyHealthMonitor()
        with get_db_session() as db:
            active_configs = (
                db.query(StrategyConfig)
                .filter(StrategyConfig.enabled.is_(True))
                .all()
            )
            for cfg in active_configs:
                stats["strategies_scanned"] += 1
                health = monitor.assess(cfg.strategy_name, db)
                if health.get("status") == "killed":
                    stats["strategies_killed"] += 1
                    logger.info(
                        "[EvolutionLoop] Killed strategy '%s' "
                        "(wr=%.3f, sharpe=%.2f, dd=%.2f)",
                        cfg.strategy_name,
                        health.get("win_rate", 0),
                        health.get("sharpe", 0),
                        health.get("max_drawdown", 0),
                    )
        logger.info(
            "[EvolutionLoop] Health scan: %d scanned, %d killed",
            stats["strategies_scanned"],
            stats["strategies_killed"],
        )
    except Exception as e:
        logger.error("[EvolutionLoop] Health scan failed: %s", e, exc_info=True)
        stats["errors"].append(f"health_scan: {e}")

    # Step 2: Forensics — generate proposals for loss patterns
    try:
        from backend.core.forensics_integration import generate_forensics_proposals

        proposal_ids = generate_forensics_proposals(lookback_hours=168, min_losses=5)
        stats["forensics_proposals"] = len(proposal_ids)
        logger.info(
            "[EvolutionLoop] Forensics: %d proposals generated",
            stats["forensics_proposals"],
        )
    except Exception as e:
        logger.error("[EvolutionLoop] Forensics failed: %s", e, exc_info=True)
        stats["errors"].append(f"forensics: {e}")

    # Step 3: Rehabilitation — re-enable disabled strategies that recovered
    try:
        from backend.core.strategy_rehabilitator import strategy_rehabilitator

        rehabilitated = strategy_rehabilitator.run()
        stats["strategies_rehabilitated"] = len(rehabilitated)
        if rehabilitated:
            logger.info(
                "[EvolutionLoop] Rehabilitated: %s", rehabilitated,
            )
    except Exception as e:
        logger.error("[EvolutionLoop] Rehabilitation failed: %s", e, exc_info=True)
        stats["errors"].append(f"rehabilitation: {e}")

    # Step 4: Variant creation — evolve winning strategies
    try:
        from backend.models.database import StrategyConfig
        from backend.models.outcome_tables import StrategyOutcome
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            active = (
                db.query(StrategyConfig)
                .filter(StrategyConfig.enabled.is_(True))
                .all()
            )
            for cfg in active:
                outcomes = (
                    db.query(StrategyOutcome)
                    .filter(
                        StrategyOutcome.strategy == cfg.strategy_name,
                        StrategyOutcome.result.in_(["win", "loss"]),
                    )
                    .order_by(StrategyOutcome.settled_at.desc())
                    .limit(50)
                    .all()
                )
                if len(outcomes) < 20:
                    continue
                wins = sum(1 for o in outcomes if o.result == "win")
                win_rate = wins / len(outcomes)
                # Winners (WR > 55%) get variant experiments created
                if win_rate > 0.55:
                    try:
                        from backend.models.kg_models import ExperimentRecord
                        from backend.core.agi_types import ExperimentStatus

                        exp = ExperimentRecord(
                            name=f"{cfg.strategy_name}_variant_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}",
                            strategy_name=cfg.strategy_name,
                            strategy_composition={
                                "source": "evolution_loop",
                                "parent_win_rate": round(win_rate, 4),
                                "parent_trades": len(outcomes),
                            },
                            status=ExperimentStatus.DRAFT.value,
                            created_at=datetime.now(timezone.utc),
                        )
                        db.add(exp)
                        stats["winners_evolved"] += 1
                        logger.info(
                            "[EvolutionLoop] Created variant experiment for '%s' (wr=%.1f%%)",
                            cfg.strategy_name, win_rate * 100,
                        )
                    except Exception as exp_err:
                        logger.warning(
                            "[EvolutionLoop] Variant creation failed for '%s': %s",
                            cfg.strategy_name, exp_err,
                        )
            if stats["winners_evolved"] > 0:
                db.commit()
        logger.info(
            "[EvolutionLoop] Evolution: %d winner variants created",
            stats["winners_evolved"],
        )
    except Exception as e:
        logger.error("[EvolutionLoop] Variant creation failed: %s", e, exc_info=True)
        stats["errors"].append(f"evolution: {e}")

    total_errors = len(stats["errors"])
    logger.info(
        "[EvolutionLoop] Cycle complete: scanned=%d killed=%d forensics=%d "
        "rehabilitated=%d evolved=%d errors=%d",
        stats["strategies_scanned"],
        stats["strategies_killed"],
        stats["forensics_proposals"],
        stats["strategies_rehabilitated"],
        stats["winners_evolved"],
        total_errors,
    )
    return stats
