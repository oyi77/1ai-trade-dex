"""Shadow genome validation job for promotion eligibility."""

import logging
from datetime import datetime, timezone

from backend.models.database import SessionLocal, GenomeRegistry, EvolutionLog
from backend.application.strategy.shadow_runner import DBSessionShadowRunner

logger = logging.getLogger("trading_bot")


def shadow_validation_job():
    """Validate all SHADOW stage genomes for promotion eligibility.

    Runs every 5 minutes when SHADOW_VALIDATE_ENABLED=True.
    - Evaluates promotion eligibility for all genomes in SHADOW stage
    - Publishes events for eligible genomes
    - Auto-kills stale low-accuracy genomes (>7 days with accuracy < 0.40)
    """
    from backend.config import settings

    if not getattr(settings, "SHADOW_VALIDATE_ENABLED", True):
        logger.info("Shadow validation disabled by config")
        return

    logger.info("Starting shadow validation job...")

    db = SessionLocal()
    shadow_runner = DBSessionShadowRunner()

    try:
        # Get all genomes in SHADOW stage
        shadow_genomes = db.query(GenomeRegistry).filter(
            GenomeRegistry.stage == "SHADOW"
        ).all()

        logger.info(f"Found {len(shadow_genomes)} genomes in SHADOW stage")

        for genome in shadow_genomes:
            genome_id = genome.genome_id
            stage_entered_at = genome.stage_entered_at

            if not stage_entered_at:
                logger.warning(f"Genome {genome_id} has no stage_entered_at, skipping")
                continue

            # Evaluate promotion eligibility
            eligibility = shadow_runner.evaluate_promotion_eligibility(genome_id)

            logger.info(
                f"Genome {genome_id} eligibility: "
                f"trades={eligibility['total_trades']}, "
                f"accuracy={eligibility['accuracy']:.2f}, "
                f"days_active={eligibility['days_active']:.1f}, "
                f"eligible={eligibility['eligible']}"
            )

            # Check if eligible for promotion
            if eligibility['eligible']:
                # Publish event for eligible genomes
                from backend.core.event_bus import publish_event as publish_event
                event_data = {
                    "genome_id": genome_id,
                    "stage": "SHADOW",
                    "target_stage": "PAPER",
                    "total_trades": eligibility['total_trades'],
                    "accuracy": eligibility['accuracy'],
                    "days_active": eligibility['days_active'],
                    "reason": eligibility['reason']
                }
                publish_event("genome_ready_for_paper", event_data)

                # Log to evolution log
                log_entry = EvolutionLog(
                    genome_id=genome_id,
                    event_type="promotion_ready",
                    from_stage="SHADOW",
                    to_stage="PAPER",
                    data={
                        "accuracy": eligibility['accuracy'],
                        "days_active": eligibility['days_active'],
                        "total_trades": eligibility['total_trades']
                    },
                    timestamp=datetime.now(timezone.utc)
                )
                db.add(log_entry)
                db.commit()

                logger.info(f"Genome {genome_id} is ready for PAPER promotion")

            # Check for stale low-accuracy genomes (>7 days with accuracy < 0.40)
            if stage_entered_at.tzinfo is None:
                stage_entered_at = stage_entered_at.replace(tzinfo=timezone.utc)
            days_in_shadow = (datetime.now(timezone.utc) - stage_entered_at).days
            if (days_in_shadow >= 7 and
                eligibility['accuracy'] < 0.40 and
                eligibility['total_trades'] >= 10):

                # Auto-kill to GRAVEYARD
                genome.stage = "GRAVEYARD"
                genome.stage_entered_at = datetime.now(timezone.utc)

                # Log to evolution log
                log_entry = EvolutionLog(
                    genome_id=genome_id,
                    event_type="auto_killed",
                    from_stage="SHADOW",
                    to_stage="GRAVEYARD",
                    data={
                        "accuracy": eligibility['accuracy'],
                        "days_active": eligibility['days_active'],
                        "total_trades": eligibility['total_trades'],
                        "reason": "Stale low-accuracy genome (>7 days, accuracy < 0.40)"
                    },
                    timestamp=datetime.now(timezone.utc)
                )
                db.add(log_entry)
                db.commit()

                logger.warning(f"Auto-killed genome {genome_id} to GRAVEYARD due to poor performance")

    except Exception as e:
        logger.error(f"Error in shadow validation job: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()

    logger.info("Shadow validation job completed")
