"""Carved verbatim out of ``backend/core/orchestrator.py`` — statements moved, no logic changed."""

from .orchestrator import (
    Optional,
    PolymarketCLOB,
)

from . import orchestrator as _facade

async def _auto_execute_weather(signals: list, clob: Optional[PolymarketCLOB]) -> None:
    """Execute weather signals without Telegram confirmation (simulation only)."""
    if not clob:
        return
    for sig in signals:
        try:
            market = sig.market
            token_id = getattr(market, "token_id", "") or market.market_id
            price = market.yes_price if sig.direction == "yes" else market.no_price
            result = await clob.place_limit_order(
                token_id=token_id,
                side="BUY",
                price=price,
                size=sig.suggested_size,
            )
            _facade.logger.info(
                f"[AUTO-SIM] Weather trade: {sig.market.city_name} "
                f"{sig.direction.upper()} ${sig.suggested_size:.2f} "
                f"order={result.order_id}"
            )
        except Exception as e:
            _facade.logger.warning(
                f"[orchestrator._auto_execute_weather] {type(e).__name__}: Auto-execute failed: {e}",
                exc_info=True,
            )
async def main() -> None:
    """Run the orchestrator until interrupted."""

    from backend.core.log import configure_logging

    configure_logging()

    orchestrator = _facade.Orchestrator()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        _facade.logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (_facade.signal.SIGINT, _facade.signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    def _dump_handler(sig, frame):
        import traceback
        import sys
        import asyncio

        try:
            with open("/tmp/orchestrator_stack.txt", "w") as f:
                f.write("=== Thread Stacks ===\n")
                for thread_id, stack in sys._current_frames().items():
                    f.write(f"\n--- Thread {thread_id} ---\n")
                    traceback.print_stack(stack, file=f)

                f.write("\n=== Async Tasks ===\n")
                try:
                    loop = asyncio.get_event_loop()
                    for task in asyncio.all_tasks(loop):
                        f.write(
                            f"\n--- Task {task.get_name()} ({task.get_coro()}) ---\n"
                        )
                        for task_frame in task.get_stack():
                            traceback.print_stack(task_frame, file=f)
                except Exception as e:
                    f.write(f"Failed to dump async tasks: {e}\n")
            print(
                "Dumped stack traces to /tmp/orchestrator_stack.txt",
                file=sys.stderr,
                flush=True,
            )
        except Exception as err:
            print(f"Error in signal handler: {err}", file=sys.stderr, flush=True)

    _facade.signal.signal(_facade.signal.SIGUSR1, _dump_handler)

    await orchestrator.start()
    _facade.logger.info("[DEBUG] orchestrator.start() completed — now entering main event loop")

    try:
        from backend.models.database import SystemSettings
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            mirofish_enabled = (
                db.query(SystemSettings)
                .filter(SystemSettings.key == "mirofish_enabled")
                .first()
            )
            if mirofish_enabled and str(mirofish_enabled.value).lower() in (
                "true",
                "1",
                "yes",
            ):
                from backend.services.mirofish_service import get_mirofish_service

                service = get_mirofish_service()
                if not service.is_active():
                    service.start()
                    _facade.logger.info("MiroFish service auto-started (enabled in settings)")
    except Exception as e:
        _facade.logger.debug(f"MiroFish auto-start check failed: {e}")

    _facade.logger.info("PolyEdge running. Press Ctrl+C to stop.")
    await stop_event.wait()

    await orchestrator.stop()
    _facade.logger.info("PolyEdge stopped.")
def init_phase2_modules() -> dict:
    """Initialize Phase 2 modules based on feature flags. Returns dict of active instances."""
    from backend.config import settings

    active: dict = {}

    if getattr(settings, "WHALE_LISTENER_ENABLED", False):
        try:
            from backend.data.polygon_listener import PolygonListener

            active["whale_listener"] = PolygonListener()
        except Exception as e:
            _facade.logger.warning(
                f"[orchestrator.init_phase2_modules] {type(e).__name__}: PolygonListener init failed: {e}",
                exc_info=True,
            )

    if getattr(settings, "NEWS_FEED_ENABLED", False):
        try:
            from backend.data.feed_aggregator import FeedAggregator

            active["news_feed"] = FeedAggregator()
        except Exception as e:
            _facade.logger.warning(
                f"[orchestrator.init_phase2_modules] {type(e).__name__}: FeedAggregator init failed: {e}",
                exc_info=True,
            )

    if getattr(settings, "AUTO_TRADER_ENABLED", False):
        try:
            from backend.core.auto_trader import AutoTrader
            from backend.core.risk.risk_manager import RiskManager

            from backend.core.wallet.registry import get_wallet_router

            active["auto_trader"] = AutoTrader(
                RiskManager(), wallet_router=get_wallet_router()
            )
        except Exception as e:
            _facade.logger.warning(
                f"[orchestrator.init_phase2_modules] {type(e).__name__}: AutoTrader init failed: {e}",
                exc_info=True,
            )

    if getattr(settings, "ARBITRAGE_DETECTOR_ENABLED", False):
        try:
            from backend.core.arbitrage_detector import ArbitrageDetector

            active["arbitrage"] = ArbitrageDetector()
        except Exception as e:
            _facade.logger.warning(
                f"[orchestrator.init_phase2_modules] {type(e).__name__}: ArbitrageDetector init failed: {e}",
                exc_info=True,
            )

    if getattr(settings, "AGI_PIPELINE_ENABLED", False):
        try:
            from backend.research.pipeline import AutonomousResearchPipeline
            import asyncio as _asyncio

            _research = AutonomousResearchPipeline()
            _task = _asyncio.ensure_future(_research.run_continuous())
            active["agi_research"] = _research
            active["agi_research_task"] = _task
        except Exception as e:
            _facade.logger.warning(
                f"[orchestrator.init_phase2_modules] {type(e).__name__}: AGI research pipeline init failed: {e}",
                exc_info=True,
            )

    return active
