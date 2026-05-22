"""PolyEdge top-level orchestrator — wires together CLOB, Telegram, scheduler, and strategies."""

import asyncio
import signal
from typing import Optional, Dict

from cachetools import TTLCache

from backend.config import settings
from backend.data.polymarket_clob import (
    PolymarketCLOB,
    clob_from_settings,
    clob_breaker,
)
from backend.core.risk_profiles import apply_profile, get_active_profile_name

from loguru import logger


class Orchestrator:
    """Top-level coordinator. Create one per process."""

    def __init__(self):
        self._clob: Optional[PolymarketCLOB] = None
        self._clob_clients: Dict[str, PolymarketCLOB] = {}
        self._bot = None
        self._copy_trader = None
        self._copy_task: Optional[asyncio.Task] = None
        self._running = False
        self._condition_cache: TTLCache = TTLCache(maxsize=2000, ttl=3600)

    def clear_cache(self) -> None:
        """Clear the condition cache. Call after major state changes."""
        self._condition_cache.clear()

    async def start(self) -> None:
        """Start all subsystems."""
        self._running = True
        logger.info("Orchestrator starting...")

        # Publish a startup heartbeat immediately so the external guardian
        # does not treat cold start as an event-loop freeze before the
        # scheduler's watchdog job begins touching the file.
        try:
            from backend.core.heartbeat import _touch_heartbeat_file

            _touch_heartbeat_file()
        except Exception as exc:
            logger.debug(f"Startup heartbeat touch failed (non-fatal): {exc}")

        # Start BalanceAggregator (real-time multi-venue balance tracking)
        try:
            from backend.core.balance_aggregator import BalanceAggregator
            self._balance_aggregator = BalanceAggregator()
            asyncio.create_task(self._balance_aggregator.start())
            logger.info("BalanceAggregator started (WS + polling)")
        except Exception as e:
            logger.warning(f"BalanceAggregator failed to start: {e}")
            self._balance_aggregator = None

        # Start ActivityTracker (real-time blockchain activity: fills, transfers)
        try:
            from backend.core.activity.tracker import ActivityTracker
            from backend.core.activity import set_tracker
            self._activity_tracker = ActivityTracker()
            set_tracker(self._activity_tracker)
            # Register platform sources
            await self._register_activity_sources()
            asyncio.create_task(self._activity_tracker.start_all())
            logger.info("ActivityTracker started")
        except Exception as e:
            logger.warning(f"ActivityTracker failed to start: {e}")
            self._activity_tracker = None

        # Reset CLOB circuit breaker to ensure we start in CLOSED state
        clob_breaker.reset()

        for mode in ["paper", "testnet", "live"]:
            try:
                clob_client = clob_from_settings(mode=mode)
                await clob_client.__aenter__()
                self._clob_clients[mode] = clob_client
                logger.info(f"CLOB client initialized for mode: {mode}")
            except Exception as exc:
                logger.warning(f"CLOB client init failed for mode {mode}: {exc}")
                if mode in ("testnet", "live"):
                    raise RuntimeError(
                        f"Failed to initialize CLOB client for {mode} mode. "
                        f"Check POLYMARKET_PRIVATE_KEY and CLOB_API_* in .env."
                    ) from exc
                self._clob_clients[mode] = None

        self._clob = self._clob_clients.get("live") or self._clob_clients.get("paper")

        if settings.is_mode_active("live"):
            logger.info("Live mode: deriving API credentials from private key...")
            try:
                creds = await self._clob_clients["live"].create_or_derive_api_key()
                if creds:
                    logger.info("API credentials derived successfully.")
                else:
                    logger.warning(
                        "Failed to derive API credentials. Bot will continue in degraded mode. "
                        "CLOB balance checks and live orders will be unavailable."
                    )
            except Exception as e:
                logger.warning(
                    f"API credential derivation failed: {e}. "
                    f"Bot continuing in degraded mode."
                )

        if settings.TELEGRAM_BOT_TOKEN:
            from backend.bot.telegram_bot import bot_from_settings

            self._bot = bot_from_settings()
            self._bot.on_copy_trade = self._execute_weather_signal
            self._bot.on_pause = self._on_pause
            self._bot.on_resume = self._on_resume
            self._bot.on_mode_switch = self.on_mode_switch
            await self._bot.start()
            from backend.bot.notifier import set_bot

            set_bot(self._bot)

        profile_name = get_active_profile_name()
        profile = apply_profile(profile_name)
        logger.info(
            "Applied risk profile '%s': drawdown=%d%%, confidence=%s, edge=%s",
            profile.name,
            int(profile.daily_drawdown_limit_pct * 100),
            profile.auto_approve_min_confidence,
            profile.min_edge_threshold,
        )

        from backend.strategies.loader import load_all_strategies

        load_all_strategies()  # trigger auto-registration

        # Seed is handled by lifespan.py - don't call twice
        logger.info("Strategy config seeding handled by lifespan startup")

        # Single session for backfill + mode context setup (fixes USE-AFTER-CLOSE CORE-1)
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            from backend.core.outcome_repository import backfill_missing_outcomes

            backfilled = backfill_missing_outcomes(db)
            if backfilled > 0:
                logger.info(
                    f"Backfilled {backfilled} missing strategy outcomes on startup"
                )
            db.commit()

            self._copy_trader = None
            self._copy_task = None

            # Create 3 ModeExecutionContext instances for per-mode execution isolation
            from backend.core.mode_context import ModeExecutionContext, register_context
            from backend.core.risk_manager import RiskManager
            from backend.models.database import StrategyConfig

            for mode in ["paper", "testnet", "live"]:
                # Create RiskManager instance for this mode
                risk_manager = RiskManager()

                # Load StrategyConfig rows filtered by mode
                strategy_configs = {}
                configs = (
                    db.query(StrategyConfig)
                    .filter(
                        (StrategyConfig.trading_mode == mode)
                        | (StrategyConfig.trading_mode.is_(None))
                    )
                    .all()
                )
                for config in configs:
                    strategy_configs[config.strategy_name] = config

                # Create ModeExecutionContext
                context = ModeExecutionContext(
                    mode=mode,
                    clob_client=self._clob_clients[mode],
                    risk_manager=risk_manager,
                    strategy_configs=strategy_configs,
                )

                # Register context
                register_context(mode, context)
                logger.info(
                    f"Registered ModeExecutionContext for mode: {mode} (client={'SET' if clob_client else 'NONE'})"
                )
                logger.info(
                    f"ModeExecutionContext registered for mode: {mode} with {len(strategy_configs)} strategies"
                )

        self._patch_weather_job()

        from backend.core.scheduler import start_scheduler

        start_scheduler()
        logger.info(
            "[DEBUG] start_scheduler() completed, now registering AGI event handlers"
        )

        from backend.core.agi_event_handlers import register_agi_event_handlers

        register_agi_event_handlers()
        logger.info("[DEBUG] register_agi_event_handlers() completed")

        # Start real-time settlement WebSocket handler
        # if settings.is_mode_active("paper") or settings.is_mode_active("live"):
        #     try:
        #         from backend.core.settlement_ws import SettlementWebSocketHandler

        #         self._settlement_handler = SettlementWebSocketHandler(task_manager=self._task_manager)
        #         await self._settlement_handler.start()
        #         logger.info("Settlement WebSocket handler started")
        #     except Exception as e:
        #         logger.warning(
        #             f"[orchestrator.start] {type(e).__name__}: Could not start settlement WebSocket handler: {e}",
        #             exc_info=True,
        #         )
        logger.info("Settlement WebSocket handler skipped for now.")
        self._phase2 = init_phase2_modules()
        logger.info(
            f"[DEBUG] Phase 2 modules: {list(self._phase2.keys()) if self._phase2 else 'none'}"
        )
        if self._phase2:
            logger.info(f"Phase 2 modules active: {list(self._phase2.keys())}")

        logger.info("Orchestrator started.")

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("Orchestrator stopping...")
        self._running = False
        self._condition_cache.clear()

        if self._bot:
            await self._bot.stop()

        if self._clob:
            if settings.is_mode_active("live"):
                await self._clob.cancel_all_orders()
            await self._clob.__aexit__(None, None, None)

        for mode, clob_client in self._clob_clients.items():
            if not clob_client:
                continue
            if mode == "live":
                await clob_client.cancel_all_orders()
            await clob_client.__aexit__(None, None, None)
            logger.info(f"CLOB client closed for mode: {mode}")

        from backend.core.scheduler import stop_scheduler

        stop_scheduler()

        if hasattr(self, "_settlement_handler") and self._settlement_handler:
            from backend.core.settlement_ws import stop_settlement_handler

            await stop_settlement_handler()

        if hasattr(self, "_activity_tracker") and self._activity_tracker:
            await self._activity_tracker.stop_all()

        logger.info("Orchestrator stopped.")

    async def _register_activity_sources(self):
        """Register platform activity sources with ActivityTracker."""
        from backend.core.wallet.bankroll_reconciliation import get_wallet

        wallet = get_wallet()
        addr = wallet.address if hasattr(wallet, "address") else str(wallet)
        tracker = self._activity_tracker

        # Aster — WebSocket fills + balance + positions
        try:
            from backend.markets.providers.aster_provider import AsterProvider
            from backend.core.activity.sources.aster_source import AsterActivitySource

            aster = AsterProvider()
            await aster.connect()
            tracker.register_source("aster", AsterActivitySource(addr, aster))
        except Exception as e:
            logger.warning(f"Aster activity source skipped: {e}")

        # Hyperliquid — WebSocket user_fills
        try:
            from backend.markets.providers.hyperliquid_provider import HyperliquidProvider
            from backend.core.activity.sources.hyperliquid_source import HyperliquidActivitySource

            hl = HyperliquidProvider()
            await hl.connect()
            tracker.register_source("hyperliquid", HyperliquidActivitySource(addr, hl))
        except Exception as e:
            logger.warning(f"Hyperliquid activity source skipped: {e}")

        # Lighter — WebSocket balance + fills
        try:
            from backend.markets.providers.lighter_provider import LighterProvider
            from backend.core.activity.sources.lighter_source import LighterActivitySource

            lighter = LighterProvider()
            await lighter.connect()
            tracker.register_source("lighter", LighterActivitySource(addr, lighter))
        except Exception as e:
            logger.warning(f"Lighter activity source skipped: {e}")

        # Polymarket — CLOB fills (REST) + Polygon on-chain
        try:
            from backend.data.polymarket_clob import PolymarketCLOBClient
            from backend.core.activity.sources.polymarket_source import PolymarketActivitySource

            clob = PolymarketCLOBClient()
            tracker.register_source("polymarket", PolymarketActivitySource(addr, clob))
        except Exception as e:
            logger.warning(f"Polymarket activity source skipped: {e}")

    def _patch_weather_job(self) -> None:
        """Replace weather_scan_and_trade_job with a version that dispatches Telegram alerts."""
        import backend.core.scheduler as sched_mod

        bot = self._bot
        clob = self._clob

        original_job = sched_mod.weather_scan_and_trade_job

        async def patched_weather_job(mode: str = "paper"):
            """Weather job with Telegram dispatch."""
            from backend.core.weather_signals import scan_for_weather_signals
            from backend.core.scheduler import log_event

            signals = await scan_for_weather_signals(mode=mode)
            actionable = [s for s in signals if s.passes_threshold]

            log_event(
                "data", f"Weather: {len(signals)} signals, {len(actionable)} actionable"
            )

            if not actionable:
                return

            # Telegram confirm-mode: send alert with keyboard, wait for user press
            if bot and bot._bot:
                for signal in actionable[:3]:
                    try:
                        await bot.send_weather_signal(signal)
                        log_event(
                            "info",
                            f"Telegram alert sent: {signal.market.city_name} {signal.direction.upper()}",
                        )
                    except Exception as e:
                        logger.warning(
                            f"[orchestrator.patched_weather_job] {type(e).__name__}: Failed to send weather alert: {e}",
                            exc_info=True,
                        )
            else:
                if mode == "paper":
                    await _auto_execute_weather(actionable[:3], clob)

            try:
                await original_job(mode)
            except Exception as e:
                logger.debug(
                    f"[orchestrator.patched_weather_job] {type(e).__name__}: Original weather job error (non-fatal): {e}",
                    exc_info=True,
                )

        sched_mod.weather_scan_and_trade_job = patched_weather_job

    async def _execute_weather_signal(self, signal) -> None:
        """Execute a weather signal triggered by Telegram COPY TRADE button."""
        from backend.core.strategy_executor import execute_decision

        market = signal.market
        token_id = getattr(market, "token_id", "") or market.market_id
        price = market.yes_price if signal.direction == "yes" else market.no_price

        decision = {
            "market_ticker": market.market_id,
            "direction": signal.direction,
            "size": signal.suggested_size,
            "entry_price": price,
            "edge": getattr(signal, "edge", 0.0),
            "confidence": getattr(signal, "model_probability", 0.5),
            "model_probability": getattr(signal, "model_probability", 0.5),
            "token_id": token_id,
            "platform": settings.DEFAULT_VENUE,
            "market_type": "weather",
            "reasoning": "weather copy trade",
        }

        result = await execute_decision(decision, "weather_emos", db=None)
        if result is None:
            logger.warning(
                f"Weather copy trade rejected (non-fatal): {signal.direction} "
                f"${signal.suggested_size:.2f} @ {price:.3f}"
            )
            return None

        logger.info(
            f"Weather trade executed: {signal.direction} ${signal.suggested_size:.2f} @ {price:.3f}"
        )
        return result

    async def _handle_copy_signals(self, signals: list) -> None:
        # Apply CopyPolicyEngine filtering if available
        from backend.core.wallet.registry import get_copy_engine

        copy_engine = get_copy_engine()
        if copy_engine is not None:
            try:
                from backend.core.copy_source import CopySignalData
                from datetime import datetime, timezone

                policy_signals = [
                    CopySignalData(
                        source_name=getattr(sig, "source_name", "orchestrator"),
                        leader_address=getattr(sig, "leader_address", ""),
                        condition_id=getattr(sig.source_trade, "condition_id", ""),
                        side=getattr(sig, "our_side", "BUY"),
                        raw_size=getattr(sig, "our_size", 0.0),
                        confidence=getattr(sig, "confidence", 0.5),
                        captured_at=datetime.now(timezone.utc),
                    )
                    for sig in signals
                ]
                source_name = getattr(signals[0], "source_name", "orchestrator") if signals else "orchestrator"
                accepted = await copy_engine.process(policy_signals, source_name)
                if not accepted:
                    logger.info("[orchestrator] CopyPolicyEngine filtered all signals")
                    return
                # Map back: keep only signals whose (condition_id, side) survived policy
                accepted_keys = {(s.condition_id, s.side) for s in accepted}
                signals = [
                    sig for sig in signals
                    if (getattr(getattr(sig, "source_trade", None), "condition_id", ""), getattr(sig, "our_side", "")) in accepted_keys
                ]
            except Exception as e:
                logger.warning(f"CopyPolicyEngine filtering failed (non-fatal): {e}")

        for sig in signals:
            try:
                result = await self._execute_copy_signal(sig)
                executed = result.success if result else False
                order_id = result.order_id if result else ""

                if self._bot:
                    await self._bot.send_copy_alert(
                        sig, executed=executed, order_id=order_id
                    )
                else:
                    logger.info(
                        f"Copy signal: {sig.our_side} ${sig.our_size:.2f} "
                        f"executed={executed} order={order_id}"
                    )
            except Exception as e:
                logger.error(
                    f"[orchestrator._handle_copy_signals] {type(e).__name__}: Copy signal execution error: {e}",
                    exc_info=True,
                )
                if self._bot:
                    await self._bot.send_error_alert(
                        str(e), context="Copy trade execution"
                    )

    async def _execute_copy_signal(self, signal):
        if not self._clob:
            return None

        trade = signal.source_trade
        token_id = await self._condition_to_token(trade.condition_id, trade.outcome)

        if signal.our_side == "SELL":
            size = signal.our_size if signal.our_size > 0 else 10.0
        else:
            size = signal.our_size

        if size < 1.0:
            logger.debug(f"Copy signal size ${size:.2f} below minimum — skipping")
            return None

        if not self._clob:
            logger.warning("CLOB not available — skipping order placement")
            return None

        return await self._clob.place_limit_order(
            token_id=token_id,
            side=signal.our_side,
            price=signal.market_price,
            size=size,
        )

    async def on_mode_switch(self, new_mode: str) -> None:
        settings.ACTIVE_MODES = new_mode
        logger.info(f"Trading modes updated to: {new_mode}")

    async def _on_pause(self) -> None:
        from backend.core.scheduler import stop_scheduler

        stop_scheduler()
        logger.info("Trading paused via Telegram")

    async def _on_resume(self) -> None:
        from backend.core.scheduler import start_scheduler

        start_scheduler()
        logger.info("Trading resumed via Telegram")

    async def _condition_to_token(self, condition_id: str, outcome: str) -> str:
        """Map condition_id + outcome ("YES"/"NO") to a CLOB token ID via Gamma API."""
        cache_key = f"{condition_id}:{outcome}"
        if cache_key in self._condition_cache:
            return self._condition_cache[cache_key]

        import httpx as _httpx

        try:
            async with _httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{settings.GAMMA_API_URL}/markets",
                    params={"conditionId": condition_id},
                    timeout=10.0,
                )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                logger.warning(
                    f"No market found for condition_id={condition_id}, using fallback"
                )
                result = condition_id
                self._condition_cache[cache_key] = result
                return result

            market = data[0]
            tokens = market.get("tokens", [])
            if outcome.upper() == "YES" and len(tokens) > 0:
                result = str(tokens[0].get("token_id", condition_id))
            elif outcome.upper() == "NO" and len(tokens) > 1:
                result = str(tokens[1].get("token_id", condition_id))
            else:
                result = condition_id

            self._condition_cache[cache_key] = result
            return result
        except (_httpx.HTTPError, KeyError, IndexError) as e:
            logger.warning(
                f"[orchestrator._condition_to_token] {type(e).__name__}: Failed to resolve token_id for {condition_id}/{outcome}: {e}",
                exc_info=True,
            )
            return condition_id


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
            logger.info(
                f"[AUTO-SIM] Weather trade: {sig.market.city_name} "
                f"{sig.direction.upper()} ${sig.suggested_size:.2f} "
                f"order={result.order_id}"
            )
        except Exception as e:
            logger.warning(
                f"[orchestrator._auto_execute_weather] {type(e).__name__}: Auto-execute failed: {e}",
                exc_info=True,
            )


async def main() -> None:
    """Run the orchestrator until interrupted."""

    from backend.core.log import configure_logging

    configure_logging()

    orchestrator = Orchestrator()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await orchestrator.start()
    logger.info("[DEBUG] orchestrator.start() completed — now entering main event loop")

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
                    logger.info("MiroFish service auto-started (enabled in settings)")
    except Exception as e:
        logger.debug(f"MiroFish auto-start check failed: {e}")

    logger.info("PolyEdge running. Press Ctrl+C to stop.")
    await stop_event.wait()

    await orchestrator.stop()
    logger.info("PolyEdge stopped.")


def init_phase2_modules() -> dict:
    """Initialize Phase 2 modules based on feature flags. Returns dict of active instances."""
    from backend.config import settings

    active: dict = {}

    if getattr(settings, "WHALE_LISTENER_ENABLED", False):
        try:
            from backend.data.polygon_listener import PolygonListener

            active["whale_listener"] = PolygonListener()
        except Exception as e:
            logger.warning(
                f"[orchestrator.init_phase2_modules] {type(e).__name__}: PolygonListener init failed: {e}",
                exc_info=True,
            )

    if getattr(settings, "NEWS_FEED_ENABLED", False):
        try:
            from backend.data.feed_aggregator import FeedAggregator

            active["news_feed"] = FeedAggregator()
        except Exception as e:
            logger.warning(
                f"[orchestrator.init_phase2_modules] {type(e).__name__}: FeedAggregator init failed: {e}",
                exc_info=True,
            )

    if getattr(settings, "AUTO_TRADER_ENABLED", False):
        try:
            from backend.core.auto_trader import AutoTrader
            from backend.core.risk_manager import RiskManager

            from backend.core.wallet.registry import get_wallet_router

            active["auto_trader"] = AutoTrader(
                RiskManager(), wallet_router=get_wallet_router()
            )
        except Exception as e:
            logger.warning(
                f"[orchestrator.init_phase2_modules] {type(e).__name__}: AutoTrader init failed: {e}",
                exc_info=True,
            )

    if getattr(settings, "ARBITRAGE_DETECTOR_ENABLED", False):
        try:
            from backend.core.arbitrage_detector import ArbitrageDetector

            active["arbitrage"] = ArbitrageDetector()
        except Exception as e:
            logger.warning(
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
            logger.warning(
                f"[orchestrator.init_phase2_modules] {type(e).__name__}: AGI research pipeline init failed: {e}",
                exc_info=True,
            )

    return active


if __name__ == "__main__":
    asyncio.run(main())
