"""Scheduled job wrappers for AGI-loop components (self-review, research)."""
from sqlalchemy import distinct

from loguru import logger
def _get_active_market_queries() -> list[str]:
    """Extract market topic queries from recent trades and signals."""
    try:
        from backend.models.database import SessionLocal, Trade

        with SessionLocal() as db:
            tickers = (
                db.query(distinct(Trade.market_ticker))
                .filter(Trade.market_ticker.isnot(None))
                .order_by(Trade.created_at.desc())
                .limit(20)
                .all()
            )
            return [t[0].replace("-", " ").replace("_", " ") for t in tickers if t[0]]
    except Exception:
        logger.exception("[AGI Jobs] Failed to get active market queries")
        return []


async def self_review_job() -> None:
    """Run the self-review cycle: attribution, postmortems, degradation detection."""
    from backend.core.scheduler import log_event

    log_event("info", "Running self-review cycle...")
    try:
        from backend.ai.self_review import SelfReview

        reviewer = SelfReview()
        result = await reviewer.run_review_cycle()

        n_alerts = len(result.get("degradation_alerts", []))
        n_postmortems = len(result.get("postmortems", []))
        log_event(
            "success",
            f"Self-review complete: {n_postmortems} postmortems, {n_alerts} degradation alerts",
        )
    except Exception as exc:
        logger.exception("self_review_job failed: %s", exc)
        log_event("error", f"Self-review failed: {exc}")


async def research_pipeline_job() -> None:
    """Run the autonomous research pipeline: RSS, BigBrain search, scoring."""
    from backend.core.scheduler import log_event

    log_event("info", "Running research pipeline...")
    try:
        from backend.research.pipeline import ResearchPipeline

        pipeline = ResearchPipeline()

        active_markets = _get_active_market_queries()

        items = await pipeline.run_research_cycle(markets=active_markets)

        if items:
            from backend.research.storage import ResearchStorage

            storage = ResearchStorage()
            stored = await storage.store_items(items)
            log_event(
                "success",
                f"Research pipeline complete: {len(items)} found, {stored} stored",
            )
        else:
            log_event(
                "success",
                "Research pipeline complete: 0 relevant items found",
            )
    except Exception as exc:
        logger.exception("research_pipeline_job failed: %s", exc)
        log_event("error", f"Research pipeline failed: {exc}")


async def agi_health_check_job() -> None:
    from backend.core.scheduler import log_event

    log_event("info", "Running AGI health check...")
    try:
        from backend.core.agi_health_check import agi_health_checker

        results = agi_health_checker.run_checks()
        summary = results.get("summary", {})
        if summary.get("all_healthy"):
            log_event("success", "AGI health check: all checks passed")
        else:
            passed = summary.get("passed", 0)
            total = summary.get("total", 0)
            log_event("warning", f"AGI health check: {passed}/{total} checks passed")
    except Exception as exc:
        logger.exception("agi_health_check_job failed: %s", exc)
        log_event("error", f"AGI health check failed: {exc}")


async def nightly_review_job() -> None:
    from backend.core.scheduler import log_event

    log_event("info", "Running nightly review...")
    try:
        from backend.core.nightly_review import nightly_review_writer

        path = nightly_review_writer.generate()
        if path:
            log_event("success", f"Nightly review written to {path}")
        else:
            log_event("warning", "Nightly review generation returned no path")
    except Exception as exc:
        logger.exception("nightly_review_job failed: %s", exc)
        log_event("error", f"Nightly review failed: {exc}")


async def strategy_rehabilitation_job() -> None:
    from backend.core.scheduler import log_event

    log_event("info", "Running strategy rehabilitation...")
    try:
        from backend.core.strategy_rehabilitator import strategy_rehabilitator

        rehabilitated = strategy_rehabilitator.run()
        if rehabilitated:
            log_event("success", f"Rehabilitated strategies: {rehabilitated}")
        else:
            log_event("info", "No strategies eligible for rehabilitation")
    except Exception as exc:
        logger.exception("strategy_rehabilitation_job failed: %s", exc)
        log_event("error", f"Strategy rehabilitation failed: {exc}")


async def historical_data_collection_job() -> None:
    from backend.core.scheduler import log_event

    log_event("info", "Running historical data collection...")
    try:
        from backend.core.historical_data_collector import historical_data_collector

        results = await historical_data_collector.run_collection_cycle()
        total = sum(results.values())
        log_event("success", f"Historical data collection: {total} new rows — {results}")
    except Exception as exc:
        logger.exception("historical_data_collection_job failed: %s", exc)
        log_event("error", f"Historical data collection failed: {exc}")


async def forensics_integration_job() -> None:
    from backend.core.scheduler import log_event

    log_event("info", "Running forensics integration...")
    try:
        from backend.core.forensics_integration import generate_forensics_proposals

        ids = generate_forensics_proposals()
        if ids:
            log_event("success", f"Forensics integration: created {len(ids)} proposals")
        else:
            log_event("info", "Forensics integration: no new proposals needed")
    except Exception as exc:
        logger.exception("forensics_integration_job failed: %s", exc)
        log_event("error", f"Forensics integration failed: {exc}")


async def fronttest_validation_job() -> None:
    from backend.core.scheduler import log_event

    log_event("info", "Running fronttest validation...")
    try:
        from backend.core.fronttest_validator import fronttest_validator
        from backend.models.database import SessionLocal, StrategyProposal
        from backend.config import settings

        results = fronttest_validator.validate_all_pending()
        passed = [r for r in results if r.get("approved")]
        failed = [r for r in results if not r.get("approved")]

        if passed:
            db = SessionLocal()
            try:
                for r in passed:
                    proposal = db.query(StrategyProposal).filter(
                        StrategyProposal.id == r["proposal_id"]
                    ).first()
                    if proposal and getattr(settings, "AGI_AUTO_PROMOTE", False):
                        proposal.admin_decision = "approved"
                        logger.info(
                            "[fronttest] Auto-approved proposal %d for '%s' (wr=%.1f%%, %d trades)",
                            r["proposal_id"], r["strategy"],
                            r.get("win_rate", 0) * 100, r.get("trade_count", 0),
                        )
                db.commit()
            except Exception as e:
                db.rollback()
                logger.warning("[fronttest] Auto-approve failed: %s", e)
            finally:
                db.close()

        log_event(
            "success" if not failed else "warning",
            f"Fronttest validation: {len(passed)} passed, {len(failed)} not ready",
        )
    except Exception as exc:
        logger.exception("fronttest_validation_job failed: %s", exc)
        log_event("error", f"Fronttest validation failed: {exc}")


async def model_calibration_check_job() -> None:
    """Check AI model calibration (Brier score) and trigger retraining on drift.

    Runs the ModelEvaluator against recent settled trades. If the Brier score
    exceeds the configured threshold (default 0.25), fires the retrain trigger.
    """
    from backend.core.scheduler import log_event

    log_event("info", "Running model calibration check...")
    try:
        from backend.models.database import SessionLocal, Trade
        from backend.ai.training.model_evaluator import ModelEvaluator
        from backend.config import settings

        brier_threshold = getattr(settings, "AGI_BRIER_DRIFT_THRESHOLD", 0.25)
        min_samples = getattr(settings, "AGI_CALIBRATION_MIN_SAMPLES", 30)

        with SessionLocal() as db:
            recent_trades = (
                db.query(Trade)
                .filter(
                    Trade.settled.is_(True),
                    Trade.result.in_(("win", "loss")),
                    Trade.model_probability.isnot(None),
                )
                .order_by(Trade.settlement_time.desc())
                .limit(200)
                .all()
            )

        if len(recent_trades) < min_samples:
            log_event("info", f"Calibration check skipped: only {len(recent_trades)} samples (need {min_samples})")
            return

        predictions = [
            (float(t.model_probability), 1.0 if t.result == "win" else 0.0)
            for t in recent_trades
            if t.model_probability is not None
        ]

        evaluator = ModelEvaluator()
        metrics = evaluator.evaluate(predictions)
        brier = metrics.get("brier", 0.0)

        if brier > brier_threshold:
            logger.warning(
                "[calibration_check] Brier score %.4f exceeds threshold %.4f — triggering retrain",
                brier, brier_threshold,
            )
            from backend.core.retrain_trigger import check_and_trigger_retraining
            retrain_result = await check_and_trigger_retraining()
            log_event(
                "warning" if retrain_result.get("status") != "ok" else "success",
                f"Calibration drift detected (Brier={brier:.4f}): retrain → {retrain_result.get('status')}",
            )
        else:
            log_event("success", f"Calibration OK: Brier={brier:.4f} (threshold={brier_threshold})")

    except Exception as exc:
        logger.exception("model_calibration_check_job failed: %s", exc)
        log_event("error", f"Model calibration check failed: {exc}")
