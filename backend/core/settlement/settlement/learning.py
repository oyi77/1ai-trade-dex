"""Fire-and-forget learning pipeline for settled trades."""

from typing import List

from backend.models.database import Trade
from loguru import logger


def _run_learning_pipeline_background(settled_trades: List[Trade]) -> None:
    """Fire-and-forget learning pipeline for settled trades.

    Schedules an async task so settlement is never blocked.
    """
    from backend.core.learning.learning_pipeline import get_learning_pipeline
    import asyncio

    async def _process_all() -> None:
        pipeline = get_learning_pipeline()
        for trade in settled_trades:
            if trade.result in ("win", "loss"):
                try:
                    await pipeline.process_settlement(
                        trade_id=trade.id,
                        strategy_name=getattr(trade, "strategy", "unknown")
                        or "unknown",
                        market_id=trade.market_ticker or "unknown",
                        outcome=trade.result,
                        pnl_usd=trade.pnl or 0.0,
                        genome_id=getattr(trade, "genome_id", None),
                        regime_at_entry=getattr(trade, "regime", None),
                        signal_confidence=getattr(trade, "confidence", None),
                    )
                except Exception as e:
                    logger.debug(f"Learning pipeline failed for trade {trade.id}: {e}")

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_process_all())
    except RuntimeError:
        # No running loop — run in a thread
        import threading

        def _runner() -> None:
            try:
                asyncio.run(_process_all())
            except Exception as e:
                logger.debug(f"Learning pipeline thread failed: {e}")

        threading.Thread(target=_runner, name="learning-pipeline", daemon=True).start()
