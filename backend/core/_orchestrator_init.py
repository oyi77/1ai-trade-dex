"""Methods carved verbatim out of ``backend/core/orchestrator.py``."""

from . import orchestrator as _facade

class OrchestratorMixin:
    def __init__(self):
        self._clob: _facade.Optional[_facade.PolymarketCLOB] = None
        self._clob_clients: _facade.Dict[str, _facade.PolymarketCLOB] = {}
        self._bot = None
        self._copy_trader = None
        self._copy_task: _facade.Optional[_facade.asyncio.Task] = None
        self._running = False
        self._condition_cache: _facade.TTLCache = _facade.TTLCache(maxsize=2000, ttl=3600)
    def clear_cache(self) -> None:
        """Clear the condition cache. Call after major state changes."""
        self._condition_cache.clear()
    async def start(self) -> None:
        """Start all subsystems."""
        self._running = True
        _facade.logger.info("Orchestrator starting...")

        # Publish a startup heartbeat immediately so the external guardian
        # does not treat cold start as an event-loop freeze before the
        # scheduler's watchdog job begins touching the file.
        try:
            from backend.core.heartbeat import _touch_heartbeat_file

            _touch_heartbeat_file()
        except Exception as exc:
            _facade.logger.debug(f"Startup heartbeat touch failed (non-fatal): {exc}")

        # Start BalanceAggregator (real-time multi-venue balance tracking)
        try:
            from backend.core.balance_aggregator import BalanceAggregator

            self._balance_aggregator = BalanceAggregator()
            _facade.asyncio.create_task(self._balance_aggregator.start())
            _facade.logger.info("BalanceAggregator started (WS + polling)")
        except Exception as e:
            _facade.logger.warning(f"BalanceAggregator failed to start: {e}")
            self._balance_aggregator = None

        # Start ActivityTracker (real-time blockchain activity: fills, transfers)
        try:
            from backend.core.activity.tracker import ActivityTracker
            from backend.core.activity import set_tracker
            from backend.core.activity.event_handler import ActivityHandler
            from backend.db.utils import get_db_session

            self._activity_tracker = ActivityTracker()
            set_tracker(self._activity_tracker)
            # Register ActivityHandler to process events into DB
            self._activity_handler = ActivityHandler(
                self._activity_tracker, get_db_session
            )
            # Register platform sources
            await self._register_activity_sources()
            _facade.asyncio.create_task(self._activity_tracker.start_all())
            _facade.logger.info("ActivityTracker started")
        except Exception as e:
            _facade.logger.warning(f"ActivityTracker failed to start: {e}")
            self._activity_tracker = None

        # Reset CLOB circuit breaker to ensure we start in CLOSED state
        _facade.clob_breaker.reset()

        for mode in ["paper", "testnet", "live"]:
            try:
                clob_client = _facade.clob_from_settings(mode=mode)
                await clob_client.__aenter__()
                self._clob_clients[mode] = clob_client
                _facade.logger.info(f"CLOB client initialized for mode: {mode}")
            except Exception as exc:
                _facade.logger.warning(f"CLOB client init failed for mode {mode}: {exc}")
                if mode in ("testnet", "live"):
                    raise RuntimeError(
                        f"Failed to initialize CLOB client for {mode} mode. "
                        f"Check POLYMARKET_PRIVATE_KEY and CLOB_API_* in .env."
                    ) from exc
                self._clob_clients[mode] = None

        self._clob = self._clob_clients.get("live") or self._clob_clients.get("paper")

        if _facade.settings.is_mode_active("live"):
            _facade.logger.info("Live mode: deriving API credentials from private key...")
            try:
                creds = await self._clob_clients["live"].create_or_derive_api_key()
                if creds:
                    _facade.logger.info("API credentials derived successfully.")
                else:
                    _facade.logger.warning(
                        "Failed to derive API credentials. Bot will continue in degraded mode. "
                        "CLOB balance checks and live orders will be unavailable."
                    )
            except Exception as e:
                _facade.logger.warning(
                    f"API credential derivation failed: {e}. "
                    f"Bot continuing in degraded mode."
                )

        if _facade.settings.TELEGRAM_BOT_TOKEN:
            from backend.bot.telegram_bot import bot_from_settings

            self._bot = bot_from_settings()
            self._bot.on_copy_trade = self._execute_weather_signal
            self._bot.on_pause = self._on_pause
            self._bot.on_resume = self._on_resume
            self._bot.on_mode_switch = self.on_mode_switch
            await self._bot.start()
            from backend.bot.notification.providers.telegram import set_bot

            set_bot(self._bot)
            from backend.bot.notification.registry import registry

            registry.auto_discover()

        profile_name = _facade.get_active_profile_name()
        profile = _facade.apply_profile(profile_name)
        _facade.logger.info(
            "Applied risk profile '%s': drawdown=%d%%, confidence=%s, edge=%s",
            profile.name,
            int(profile.daily_drawdown_limit_pct * 100),
            profile.auto_approve_min_confidence,
            profile.min_edge_threshold,
        )

        from backend.strategies.loader import load_all_strategies, load_active_genome_strategies

        load_all_strategies()  # trigger auto-registration
        genome_count = load_active_genome_strategies()  # compile DB genome strategies
        if genome_count:
            _facade.logger.info(f"Loaded {genome_count} genome-compiled strategies from registry")

        # Seed is handled by lifespan.py - don't call twice
        _facade.logger.info("Strategy config seeding handled by lifespan startup")

        # Single session for backfill + mode context setup (fixes USE-AFTER-CLOSE CORE-1)
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            from backend.core.outcome_repository import backfill_missing_outcomes

            backfilled = backfill_missing_outcomes(db)
            if backfilled > 0:
                _facade.logger.info(
                    f"Backfilled {backfilled} missing strategy outcomes on startup"
                )
            db.commit()

            self._copy_trader = None
            self._copy_task = None

            # Create 3 ModeExecutionContext instances for per-mode execution isolation
            from backend.core.mode_context import ModeExecutionContext, register_context
            from backend.core.risk.risk_manager import RiskManager
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
                _facade.logger.info(
                    f"Registered ModeExecutionContext for mode: {mode} (client={'SET' if clob_client else 'NONE'})"
                )
                _facade.logger.info(
                    f"ModeExecutionContext registered for mode: {mode} with {len(strategy_configs)} strategies"
                )

        self._patch_weather_job()

        from backend.core.scheduling.scheduler import start_scheduler

        start_scheduler()
        _facade.logger.info(
            "[DEBUG] start_scheduler() completed, now registering AGI event handlers"
        )

        from backend.core.agi_event_handlers import register_agi_event_handlers

        register_agi_event_handlers()
        _facade.logger.info("[DEBUG] register_agi_event_handlers() completed")

        # --- AGI Node Discovery ---
        try:
            from backend.agi.node_registry import node_registry

            node_registry.auto_discover("backend.agi.nodes")
            _facade.logger.info(f"AGI nodes discovered: {len(node_registry._plugins)}")
        except Exception as e:
            _facade.logger.warning(f"AGI node discovery failed: {e}")

        _facade.logger.info("Settlement WebSocket handler skipped for now.")
        self._phase2 = _facade.init_phase2_modules()
        _facade.logger.info(
            f"[DEBUG] Phase 2 modules: {list(self._phase2.keys()) if self._phase2 else 'none'}"
        )
        if self._phase2:
            _facade.logger.info(f"Phase 2 modules active: {list(self._phase2.keys())}")

        _facade.logger.info("Orchestrator started.")
    async def stop(self) -> None:
        """Graceful shutdown."""
        _facade.logger.info("Orchestrator stopping...")
        self._running = False
        self._condition_cache.clear()

        # Cancel all strategy background tasks (e.g. MarketMaker queue loop)
        try:
            from backend.strategies.registry import STRATEGY_REGISTRY

            for name, cls in STRATEGY_REGISTRY.items():
                try:
                    instances = getattr(cls, "_instances", [])
                    for inst in instances:
                        stop = getattr(inst, "stop_consumer", None)
                        if stop:
                            await stop()
                except Exception:
                    _facade.logger.debug("orchestrator: failed to stop market_maker consumer instances")
        except Exception:
            _facade.logger.debug("orchestrator: failed during market_maker consumer cleanup")

        if self._bot:
            await self._bot.stop()

        if self._clob:
            if _facade.settings.is_mode_active("live"):
                await self._clob.cancel_all_orders()
            await self._clob.__aexit__(None, None, None)

        # Close shared httpx/crypto clients to prevent resource leaks
        try:
            from backend.data.crypto import close_crypto_client

            await close_crypto_client()
        except Exception:
            _facade.logger.debug("orchestrator: failed to close crypto client on shutdown")

        for mode, clob_client in self._clob_clients.items():
            if not clob_client:
                continue
            if mode == "live":
                await clob_client.cancel_all_orders()
            await clob_client.__aexit__(None, None, None)
            _facade.logger.info(f"CLOB client closed for mode: {mode}")

        from backend.core.scheduling.scheduler import stop_scheduler

        stop_scheduler()

        if hasattr(self, "_settlement_handler") and self._settlement_handler:
            from backend.core.settlement.settlement_ws import stop_settlement_handler

            await stop_settlement_handler()

        if hasattr(self, "_activity_tracker") and self._activity_tracker:
            await self._activity_tracker.stop_all()

        _facade.logger.info("Orchestrator stopped.")
