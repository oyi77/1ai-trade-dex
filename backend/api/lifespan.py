"""Lifespan management for FastAPI application - startup and shutdown handlers."""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from loguru import logger
from fastapi import FastAPI

from backend.config import settings
from backend.core.log import configure_logging
from backend.api.connection_limits import connection_limiter
from backend.api.ws_manager_v2 import topic_manager
from backend.core.scheduling.task_manager import TaskManager
from backend.data.polymarket_clob import clob_from_settings
from backend.core.mode_context import ModeExecutionContext, register_context
from backend.core.risk.risk_manager import RiskManager
from backend.api_websockets import brain_stream, activity_stream, proposals, livestream
from backend.db.utils import get_db_session


_app_ref = None


async def _redis_log_bridge():
    """Background task that bridges logs from Redis to the internal EventBus."""
    from backend.config import settings
    import logging

    if not settings.REDIS_ENABLED or not settings.REDIS_URL:
        return

    bridge_logger = logging.getLogger("backend.monitoring.bridge")
    bridge_logger.info("Starting Redis log bridge...")
    from backend.core.event_bus import event_bus

    try:
        import redis.asyncio as aioredis
    except ImportError:
        return

    while True:
        try:
            async with aioredis.from_url(settings.REDIS_URL) as client:
                async with client.pubsub() as pubsub:
                    await pubsub.subscribe("logs:system")
                    async for message in pubsub.listen():
                        if message["type"] == "message":
                            try:
                                import json

                                log_data = json.loads(message["data"])
                                event_bus.publish("system_log", log_data)
                            except Exception:
                                logger.warning(
                                    "lifespan: failed to parse log bridge JSON"
                                )
        except Exception as e:
            bridge_logger.debug(f"Redis log bridge reconnecting: {e}")
            import asyncio

            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan context manager - handles startup and shutdown."""
    import time as _time

    start_time = _time.time()

    global _app_ref
    _app_ref = app

    # Initialize loguru logging (replaces old stdlib logging setup)
    configure_logging(
        level=settings.LOG_LEVEL,
        json_output=settings.LOG_JSON,
        log_file=settings.LOG_FILE,
        rotation=settings.LOG_ROTATION,
        retention=settings.LOG_RETENTION,
    )

    # --- Startup ---
    from datetime import datetime, timezone as _tz

    logger.info("[LIFESPAN] Starting lifespan")
    app.state.start_time = datetime.now(_tz.utc)
    app.state.task_manager = TaskManager()
    logger.info(f"[LIFESPAN] TaskManager created in {_time.time() - start_time:.2f}s")

    if "sqlite" in settings.DATABASE_URL:
        try:
            from sqlalchemy import text

            with get_db_session() as db:
                db.execute(text("PRAGMA busy_timeout=1000"))
                logger.info("  SQLite busy_timeout set to 1000ms")
        except Exception as exc:
            logger.debug(f"SQLite busy_timeout setup failed: {exc}")
    logger.info(f"[LIFESPAN] After DB setup in {_time.time() - start_time:.2f}s")

    # Set WebSocket task managers
    brain_stream.set_task_manager(app.state.task_manager)
    activity_stream.set_task_manager(app.state.task_manager)
    proposals.set_task_manager(app.state.task_manager)
    livestream.set_task_manager(app.state.task_manager)
    logger.info(
        f"[LIFESPAN] WebSocket managers set in {_time.time() - start_time:.2f}s"
    )

    logger.info("=" * 60)
    logger.info("BTC 5-MIN TRADING BOT v3.0")
    logger.info("=" * 60)

    _t0 = _time.time()
    logger.info("Initializing database...")
    from backend.models.database import init_db, register_corruption_alert_handler
    from backend.core.event_bus import publish_event

    register_corruption_alert_handler(publish_event)
    init_db()
    logger.info(f"  init_db done in {_time.time()-_t0:.1f}s")

    _t1 = _time.time()
    try:
        from alembic.config import Config
        from alembic import command
        from alembic.runtime.migration import MigrationContext
        from sqlalchemy import create_engine

        _alembic_cfg = Config("alembic.ini")
        _engine = create_engine(settings.DATABASE_URL)
        with _engine.connect() as _conn:
            _ctx = MigrationContext.configure(_conn)
            _current_rev = _ctx.get_current_revision()

        logger.info(f"  alembic check: rev={_current_rev!r} in {_time.time()-_t1:.1f}s")
        if _current_rev is None:
            command.stamp(_alembic_cfg, "head")
            logger.info("Fresh DB detected — stamped at Alembic head")
        else:
            command.upgrade(_alembic_cfg, "head")
            logger.info("Alembic migrations up to date")
    except Exception as exc:
        logger.warning("Alembic migration check skipped — continuing: %s", exc)

    logger.info("[LIFESPAN] API Lifespan startup completed")
    logger.info(
        "[LIFESPAN] Lifespan duration: {:.2f}s".format(_time.time() - start_time)
    )

    # Register mode execution contexts for paper/testnet/live.
    # Paper and testnet don't require live CLOB connections; live gets
    # a best-effort client (warns on failure rather than crashing startup).
    from backend.models.database import StrategyConfig

    for _mode in ["paper", "testnet", "live"]:
        from backend.db.utils import get_db_session as _get_db

        with _get_db() as _db:
            _configs = {}
            for _cfg in _db.query(StrategyConfig).all():
                _configs[_cfg.strategy_name] = _cfg

            _clob = None
            if _mode == "live":
                try:
                    _clob = clob_from_settings(mode="live")
                    await _clob.__aenter__()
                except Exception as _exc:
                    logger.warning(f"[LIFESPAN] Live CLOB init deferred: {_exc}")
                    _clob = None

            _ctx = ModeExecutionContext(
                mode=_mode,
                clob_client=_clob,
                risk_manager=RiskManager(),
                strategy_configs=_configs,
            )
            register_context(_mode, _ctx)
            logger.info(
                f"[LIFESPAN] Registered mode context for {_mode} (clob={'SET' if _clob else 'NONE'}, strategies={len(_configs)})"
            )

    # --- Wire WalletRouter (multi-wallet N:N fan-out) ---
    encryption_key = settings.WALLET_ENCRYPTION_KEY or settings.WALLET_FERNET_KEY
    if encryption_key and settings.WALLET_ROUTER_ENABLED:
        try:
            from backend.core.wallet.wallet_router import WalletRouter

            with get_db_session() as db:
                wallet_router = WalletRouter(db, fernet_key=encryption_key.encode())
            app.state.wallet_router = wallet_router
            from backend.core.wallet.registry import set_wallet_router

            set_wallet_router(wallet_router)
            logger.info("[LIFESPAN] WalletRouter initialized")
        except Exception as e:
            logger.warning(f"WalletRouter init failed: {e}")
            app.state.wallet_router = None
    else:
        app.state.wallet_router = None

    # --- Wire CopyPolicyEngine ---
    if settings.COPY_POLICY_ENABLED:
        try:
            from backend.core.copy_engine import CopyPolicyEngine

            with get_db_session() as db:
                copy_engine = CopyPolicyEngine(db)
            app.state.copy_engine = copy_engine
            from backend.core.wallet.registry import set_copy_engine

            set_copy_engine(copy_engine)
            logger.info("[LIFESPAN] CopyPolicyEngine initialized")
        except Exception as e:
            logger.warning(f"CopyPolicyEngine init failed: {e}")
            app.state.copy_engine = None
    else:
        app.state.copy_engine = None

    # Start Redis log bridge
    if settings.REDIS_ENABLED:
        asyncio.create_task(_redis_log_bridge())

    # --- Market Provider Discovery ---
    try:
        from backend.markets.provider_registry import market_registry

        market_registry.auto_discover("backend.markets.providers")
        logger.info(
            f"[LIFESPAN] Market providers discovered: {list(market_registry._plugins.keys())}"
        )
    except Exception as e:
        logger.warning(f"[LIFESPAN] Market provider discovery failed: {e}")

    # --- AGI Node Discovery ---
    try:
        from backend.agi.node_registry import node_registry

        node_registry.auto_discover("backend.agi.nodes")
        logger.info(f"[LIFESPAN] AGI nodes discovered: {len(node_registry._plugins)}")
    except Exception as e:
        logger.warning(f"[LIFESPAN] AGI node discovery failed: {e}")

    # --- AGI Graph Registration ---
    try:
        from backend.agi.graph_engine import GraphEngine
        from backend.agi.graphs import register_default_graphs

        graph_engine = GraphEngine()
        register_default_graphs(graph_engine)
        app.state.graph_engine = graph_engine
        logger.info(
            f"[LIFESPAN] AGI graphs registered: {list(graph_engine.graphs.keys())}"
        )
    except Exception as e:
        logger.warning(f"[LIFESPAN] AGI graph registration failed: {e}")

    # --- AGI Research Module Loading ---
    try:
        from backend.agi.research.github_scanner import GitHubScanner
        from backend.agi.research.paper_scanner import PaperScanner
        from backend.agi.research.competitor_monitor import CompetitorMonitor
        from backend.agi.research.whale_tracker import WhaleTracker

        app.state.agi_research_modules = {
            "github_scanner": GitHubScanner(),
            "paper_scanner": PaperScanner(),
            "competitor_monitor": CompetitorMonitor(),
            "whale_tracker": WhaleTracker(),
        }
        logger.info(
            f"[LIFESPAN] AGI research modules loaded: {list(app.state.agi_research_modules.keys())}"
        )
    except Exception as e:
        logger.warning(f"[LIFESPAN] AGI research module loading failed: {e}")

    # --- Data Feed Discovery ---
    try:
        import backend.data.providers  # triggers provider auto-registration
        import backend.data.crypto_feeds  # triggers crypto feed auto-registration
        import backend.data.bitget_wallet  # triggers Bitget Wallet provider auto-registration

        logger.info("[LIFESPAN] Data providers and crypto feeds loaded")
    except Exception as e:
        logger.warning(f"[LIFESPAN] Data feed discovery failed: {e}")

    # --- Notification Provider Registration ---
    try:
        import os as _os

        _notify_providers = []
        if _os.environ.get("SLACK_WEBHOOK_URL"):
            from backend.bot.notification.providers.slack import SlackProvider

            _notify_providers.append("slack")
        if _os.environ.get("DISCORD_WEBHOOK_URL"):
            from backend.bot.notification.providers.discord import DiscordProvider

            _notify_providers.append("discord")
        if _os.environ.get("WEBHOOK_URL"):
            from backend.bot.notification.providers.webhook import (
                GenericWebhookProvider,
            )

            _notify_providers.append("webhook")
        if _notify_providers:
            logger.info(
                f"[LIFESPAN] Notification providers registered: {_notify_providers}"
            )
        else:
            logger.info(
                "[LIFESPAN] No notification providers configured (set SLACK_WEBHOOK_URL / DISCORD_WEBHOOK_URL / WEBHOOK_URL)"
            )
    except Exception as e:
        logger.warning(f"[LIFESPAN] Notification provider registration failed: {e}")

    # --- Balance Aggregator (real-time multi-venue balance tracking) ---
    try:
        from backend.core.balance_aggregator import BalanceAggregator

        balance_agg = BalanceAggregator()
        app.state.balance_aggregator = balance_agg
        asyncio.create_task(balance_agg.start())
        logger.info("[LIFESPAN] BalanceAggregator started (WS + polling)")
    except Exception as e:
        logger.warning(f"[LIFESPAN] BalanceAggregator failed to start: {e}")
        app.state.balance_aggregator = None

    # Start Binance WebSocket feed for real-time crypto klines
    try:
        from backend.data.crypto_ws import start_crypto_ws_feed

        await start_crypto_ws_feed(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        logger.info("[LIFESPAN] Binance WS feed started (BTC, ETH, SOL)")
    except Exception as e:
        logger.warning(f"[LIFESPAN] Binance WS feed failed to start: {e}")

    # --- Load Strategies and Start Scheduler ---
    _t_strat = _time.time()
    try:
        from backend.strategies.loader import load_all_strategies
        from backend.core.scheduling.scheduler import start_scheduler

        # Load all strategy modules (triggers auto-registration via BaseStrategy.__init_subclass__)
        load_all_strategies()
        logger.info(f"[LIFESPAN] Strategies loaded in {_time.time() - _t_strat:.2f}s")

        # Start APScheduler with all registered strategies
        start_scheduler()
        logger.info("[LIFESPAN] APScheduler started — strategies now running")
    except Exception as e:
        logger.error(f"[LIFESPAN] Failed to start strategies/scheduler: {e}", exc_info=True)

    # --- Start Real-Time Event-Driven Strategies ---
    try:
        from backend.bot.realtime_manager import start_realtime_strategies
        from backend.strategies.base import StrategyContext

        # Create a minimal context for real-time strategies
        # They don't need full StrategyContext since they're event-driven
        class MinimalContext:
            def __init__(self):
                self.mode = "paper"
                self.bankroll = 100.0

        ctx = MinimalContext()
        await start_realtime_strategies(ctx)
        logger.info("[LIFESPAN] Real-time strategies started (copy_trader, whale_tracker)")
    except Exception as e:
        logger.warning(f"[LIFESPAN] Real-time strategies failed to start: {e}")

    yield

    # --- Shutdown ---
    getattr(app.state, "shutdown_handler", None)
    shutdown_start = time.time()

    logger.info("=" * 60)
    logger.info("GRACEFUL SHUTDOWN SEQUENCE INITIATED")
    logger.info("=" * 60)

    try:
        logger.info("1. Stopping new request acceptance...")
        app.state.shutting_down = True
        logger.info("   ✓ New requests blocked")

        logger.info("2. Waiting for active requests to complete (max 5s)...")
        active_requests = getattr(app.state, "active_requests", 0)
        wait_start = time.time()
        while active_requests > 0 and (time.time() - wait_start) < 5.0:
            await asyncio.sleep(0.1)
            active_requests = getattr(app.state, "active_requests", 0)
        if active_requests > 0:
            logger.warning(
                f"   ⚠ {active_requests} active requests still pending after 5s"
            )
        else:
            logger.info("   ✓ All active requests completed")

        logger.info("3. Closing WebSocket connections...")
        try:
            from backend.api.ws_manager_v2 import topic_manager

            ws_count = sum(len(subs) for subs in topic_manager.subscriptions.values())
            for topic_subs in topic_manager.subscriptions.values():
                for ws in list(topic_subs):
                    try:
                        await ws.close(code=1001, reason="Server shutting down")
                    except Exception:
                        logger.exception(
                            "Failed to close WebSocket connection during shutdown"
                        )
            logger.info(f"   ✓ Closed {ws_count} WebSocket connections")
        except Exception as e:
            logger.debug(f"WebSocket shutdown skipped: {e}")

        logger.info("4. Shutting down Redis pub/sub...")
        try:
            await topic_manager.shutdown_redis()
            logger.info("   ✓ Redis pub/sub shut down")
        except Exception as e:
            logger.warning(f"   ⚠ Error shutting down Redis: {e}")

        logger.info("5. Shutting down connection limiter...")
        try:
            await connection_limiter.shutdown()
            logger.info("   ✓ Connection limiter shut down")
        except Exception as e:
            logger.warning(f"   ⚠ Error shutting down connection limiter: {e}")

        logger.info("6. Closing ccxt/aiohttp clients...")
        try:
            from backend.clients.aster_client import close_all_aster_clients

            await close_all_aster_clients()
            logger.info("   ✓ Closed all AsterClient instances")
        except Exception as e:
            logger.debug(f"ccxt client cleanup skipped: {e}")

        logger.info("7. Shutting down TaskManager...")
        try:
            task_count = len(app.state.task_manager.tasks)
            await app.state.task_manager.shutdown()
            logger.info(f"   ✓ TaskManager shut down ({task_count} tasks cancelled)")
        except Exception as e:
            logger.warning(f"   ⚠ Error shutting down TaskManager: {e}")

        logger.info("8. Stopping real-time strategies...")
        try:
            from backend.bot.realtime_manager import stop_realtime_strategies

            await stop_realtime_strategies()
            logger.info("   ✓ Real-time strategies stopped")
        except Exception as e:
            logger.warning(f"   ⚠ Error stopping real-time strategies: {e}")

        logger.info("9. Stopping scheduler...")
        try:
            from backend.core.scheduling.scheduler import stop_scheduler

            stop_scheduler()
            logger.info("   ✓ Scheduler stopped")
        except Exception as e:
            logger.warning(f"   ⚠ Error stopping scheduler: {e}")

        logger.info("10. Waiting for in-flight jobs (max 3s)...")
        await asyncio.sleep(3.0)
        logger.info("   ✓ Grace period complete")

        logger.info("11. Closing database connections...")
        try:
            from backend.models.database import engine

            engine.dispose()
            logger.info("   ✓ Database connections closed")
        except Exception as e:
            logger.warning(f"   ⚠ Error closing database: {e}")

    except Exception as e:
        logger.error(
            f"[api.main.lifespan] {type(e).__name__}: Error during shutdown sequence: {e}",
            exc_info=True,
        )

    elapsed = time.time() - shutdown_start
    logger.info("=" * 60)
    logger.info(f"SHUTDOWN COMPLETE (took {elapsed:.1f}s)")
    logger.info("=" * 60)
