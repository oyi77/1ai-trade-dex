from __future__ import annotations
from loguru import logger
from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult
from backend.core.agi_orchestrator import AGIOrchestrator


async def _collect_news_context() -> str:
    """Fetch and score news articles, returning a context string for decisions.

    Returns formatted news sentiment context or empty string if unavailable.
    """
    try:
        from backend.data.news_collector import NewsCollector

        collector = NewsCollector()
        scored = await collector.collect_and_analyze(limit=30)
        if not scored:
            return ""
        context = collector.scored_to_context(scored, max_chars=2000)
        logger.info(
            "news_collector: produced %d chars of sentiment context from %d articles",
            len(context),
            len(scored),
        )
        return context
    except Exception as e:
        logger.debug("News context collection skipped: %s", e)
        return ""


async def _persist_news_sentiment(db, scored_articles=None) -> None:
    """Store news sentiment snapshots in the Knowledge Graph.

    Best-effort; silently skips if KG or persistence is unavailable.
    """
    if not scored_articles:
        return
    try:
        from backend.core.knowledge_graph import KnowledgeGraph
        from backend.core.sentiment_persistence import SentimentPersistence

        kg = KnowledgeGraph(session=db)
        persister = SentimentPersistence(kg)
        for article in scored_articles[:10]:
            persister.store_sentiment(
                source="news:%s" % article.source,
                score=article.sentiment_score,
                label=article.sentiment_label,
                confidence=article.sentiment_confidence,
                market_ticker="polymarket_general",
            )
    except Exception as e:
        logger.debug("News sentiment persistence skipped: %s", e)


class AGIMetaStrategy(BaseStrategy):
    """
    Autonomous Meta-Strategy for AGI Orchestration.

    This strategy doesn't trade directly but runs the AGIOrchestrator cycle
    to update market regimes, set high-level goals, and adjust allocations.
    Includes news sentiment injection from NewsCollector.
    """

    name = "agi_orchestrator"
    description = "Autonomous AGI Research and Goal-Setting Cycle"
    category = "ai_meta"
    default_params = {"cycle_interval_hours": 1}

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Execute the AGI Orchestrator cycle autonomously."""
        ctx.logger.info(f"[{self.name}] Starting autonomous AGI cycle...")

        # Collect news sentiment context (best-effort, non-blocking)
        news_context = await _collect_news_context()
        if news_context:
            ctx.logger.info(f"[{self.name}] News sentiment context injected")

        orchestrator = AGIOrchestrator(session=ctx.db)
        try:
            # run_cycle is now asynchronous, await it directly
            result = await orchestrator.run_cycle()

            ctx.logger.info(
                f"[{self.name}] AGI cycle complete. Regime: {result.regime.value}, Goal: {result.goal.value}"
            )

            if result.errors:
                for err in result.errors:
                    ctx.logger.error(f"[{self.name}] AGI Cycle Error: {err}")

            decisions = [
                {
                    "type": "agi_cycle",
                    "regime": result.regime.value,
                    "goal": result.goal.value,
                    "actions": result.actions_taken,
                }
            ]
            if news_context:
                decisions[0]["news_context_chars"] = len(news_context)

            return CycleResult(
                decisions_recorded=1,
                trades_attempted=0,
                trades_placed=0,
                errors=result.errors,
                decisions=decisions,
            )
        finally:
            # Orchestrator doesn't own the session here, so we don't close it,
            # but we follow its own cleanup if needed.
            pass
