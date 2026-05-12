"""Lifespan management for FastAPI application - startup and shutdown handlers."""

import asyncio
import signal
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from loguru import logger
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from backend.config import settings
from backend.core.log import configure_logging
from backend.api.connection_limits import connection_limiter
from backend.api.ws_manager_v2 import topic_manager
from backend.core.task_manager import TaskManager
from backend.core.wallet_reconciliation import WalletReconciler
from backend.data.polymarket_clob import clob_from_settings
from backend.data.polymarket_websocket import get_market_websocket, shutdown_market_websocket, get_user_websocket, shutdown_user_websocket
from backend.data.orderbook_cache import get_orderbook_cache
from backend.models.database import BotState, MarketWatch, Trade, StrategyConfig
from backend.core.mode_context import ModeExecutionContext, register_context
from backend.core.risk_manager import RiskManager
from backend.core.bankroll_reconciliation import reconcile_bot_state
from backend.api_websockets import brain_stream, activity_stream, proposals, livestream
from backend.db.utils import get_db_session


def _set_startup_sqlite_busy_timeout(db, timeout_ms: int) -> None:
    """Keep best-effort startup writes from blocking API availability."""

    if "sqlite" not in settings.DATABASE_URL:
        return

    try:
        from sqlalchemy import text

        db.execute(text(f"PRAGMA busy_timeout={int(timeout_ms)}"))
    except Exception as exc:
        logger.debug(f"Failed to set startup SQLite busy_timeout={timeout_ms}: {exc}")


class GracefulShutdownHandler:
    """Handles graceful shutdown on SIGTERM/SIGINT with timeout."""

    def __init__(self, app: FastAPI):
        self.app = app
        self.shutdown_event = asyncio.Event()
        self.shutdown_timeout = 30.0
        self.start_time = None

    def _signal_handler(self, signum, frame):
        """Signal handler for SIGTERM and SIGINT."""
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name} signal, initiating graceful shutdown...")
        self.start_time = time.time()
        self.shutdown_event.set()

    def register_handlers(self):
        """Register signal handlers for SIGTERM and SIGINT."""
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        logger.info("Signal handlers registered for SIGTERM and SIGINT")

    async def wait_for_shutdown(self):
        """Wait for shutdown signal or timeout."""
        try:
            await asyncio.wait_for(
                self.shutdown_event.wait(),
                timeout=self.shutdown_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"Shutdown timeout ({self.shutdown_timeout}s) reached")

    def get_elapsed_time(self) -> float:
        """Get elapsed time since shutdown started."""
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time


async def _refresh_balance_cache():
    """Refresh the cached wallet balance from CLOB."""
    if not any(m in ("live", "testnet") for m in settings.active_modes_set):
        return

    try:
        clob = clob_from_settings()
        async with clob:
            await clob.create_or_derive_api_creds()
            balance_data = await clob.get_wallet_balance()
            clob_balance = balance_data.get("usdc_balance", 0.0)

            if clob_balance >= 0:
                # Use local _balance_cache
                _balance_cache["balance"] = clob_balance
                _balance_cache["timestamp"] = time.time()
                _balance_cache["mode"] = settings.TRADING_MODE
                logger.info(f"Balance cache refreshed: ${clob_balance:.2f}")
    except Exception as e:
        logger.warning(
            f"[api.main.refresh_balance_cache] {type(e).__name__}: Failed to refresh balance cache: {e}",
            exc_info=True
        )


async def _stats_broadcaster():
    """Background task that periodically broadcasts stats to WebSocket subscribers."""
    logger.info("Stats broadcaster task started")

    await _refresh_balance_cache()

    BALANCE_REFRESH_INTERVAL = 30

    while True:
        try:
            connection_count = topic_manager.get_topic_subscriber_count("stats")
            if connection_count > 0:
                logger.info(f"Broadcasting stats to {connection_count} clients")

                now = time.time()
                if now - _balance_cache["timestamp"] > BALANCE_REFRESH_INTERVAL:
                    await _refresh_balance_cache()

                from backend.api.system import get_stats

                from backend.db.utils import get_db_session
                with get_db_session() as db:
                    # Get stats for all 3 modes
                    stats = await get_stats(db=db, mode=None)
                    await topic_manager.broadcast(
                        "stats",
                        {
                            "type": "stats_update",
                            "timestamp": time.time(),
                            "data": stats.model_dump(mode='json'),
                        }
                    )
            else:
                logger.debug("No active WebSocket connections, skipping broadcast")
        except Exception as e:
            logger.error(
                f"[api.main.stats_broadcaster] {type(e).__name__}: Stats broadcaster error: {e}",
                exc_info=True
            )
        await asyncio.sleep(1)


async def _startup_polymarket_websocket():
    """Initialize and start Polymarket WebSocket connections."""
    logger.info("Starting Polymarket WebSocket for real-time market data...")
    market_ws_task = None
    user_ws_task = None

    try:
        if settings.POLYMARKET_WS_ENABLED:
            asset_ids = []
            condition_ids = []
            from backend.db.utils import get_db_session
            with get_db_session() as db:
                active_markets = db.query(MarketWatch).all()
                for market in active_markets:
                    if market.token_id:
                        asset_ids.append(market.token_id)
                    if market.condition_id:
                        condition_ids.append(market.condition_id)

                # Fallback: load token IDs from Gamma API when MarketWatch is empty
                if not asset_ids:
                    try:
                        import httpx
                        async with httpx.AsyncClient(timeout=15.0) as client:
                            resp = await client.get(
                                f"{settings.GAMMA_API_URL}/markets",
                                params={"active": "true", "closed": "false", "limit": 100, "order": "volume", "ascending": "false"},
                            )
                            if resp.status_code == 200:
                                markets = resp.json()
                                for m in markets:
                                    tokens = m.get("clobTokenIds") or []
                                    asset_ids.extend(tokens[:2])
                                    if m.get("conditionId") and m["conditionId"] not in condition_ids:
                                        condition_ids.append(m["conditionId"])
                                logger.info(f"WS fallback: loaded {len(asset_ids)} token IDs from Gamma API")
                    except Exception as exc:
                        logger.warning(f"WS token loading from Gamma API failed: {exc}")

            if asset_ids:
                market_ws = await get_market_websocket(asset_ids)
                get_orderbook_cache()

                # Notify event bus: WS connected, strategies can use WS path
                from backend.core.event_bus import event_bus
                event_bus.set_ws_connected()

                def handle_orderbook(snapshot):
                    from backend.core.event_bus import publish_event
                    publish_event(
                        "orderbook_update",
                        {
                            "asset_id": snapshot.asset_id,
                            "bids": snapshot.bids[:5],
                            "asks": snapshot.asks[:5],
                            "timestamp": snapshot.timestamp,
                        },
                    )

                def handle_trade(trade):
                    from backend.core.event_bus import publish_event
                    publish_event(
                        "trade_executed",
                        {
                            "asset_id": trade.asset_id,
                            "price": trade.price,
                            "size": trade.size,
                            "side": trade.side,
                            "timestamp": trade.timestamp,
                        },
                    )

                # Also map WS event types for strategy dispatch
                def handle_last_trade_price(event_data):
                    asset_id = event_data.get("asset_id", "")
                    if asset_id:
                        from backend.core.event_bus import publish_event
                        publish_event("last_trade_price", event_data)

                def handle_price_change(event_data):
                    asset_id = event_data.get("asset_id", "")
                    if asset_id:
                        from backend.core.event_bus import publish_event
                        publish_event("price_change", event_data)

                market_ws.on_orderbook(handle_orderbook)
                market_ws.on_trade(handle_trade)

                market_ws_task = await _get_app().state.task_manager.create_task(
                    market_ws.connect(), name="polymarket_market_ws"
                )
                logger.info(f"Polymarket WebSocket started for {len(asset_ids)} markets")
            else:
                logger.info("No active markets found - WebSocket not started")

            if settings.POLYMARKET_USER_WS_ENABLED and condition_ids:
                if all([
                    settings.POLYMARKET_API_KEY,
                    settings.POLYMARKET_API_SECRET,
                    settings.POLYMARKET_API_PASSPHRASE,
                ]):
                    user_ws = await get_user_websocket(
                        condition_ids=condition_ids,
                        api_key=settings.POLYMARKET_API_KEY,
                        api_secret=settings.POLYMARKET_API_SECRET,
                        api_passphrase=settings.POLYMARKET_API_PASSPHRASE,
                    )

                    def _handle_user_trade(event):
                        logger.info(f"Trade fill: {event.get('id')} - {event.get('status')}")
                        from backend.core.event_bus import publish_event
                        publish_event("user_trade_fill", event)

                        try:
                            from backend.db.utils import get_db_session
                            with get_db_session() as db:
                                    trade_id = event.get("id")
                                    status = event.get("status")

                                    if status == "CONFIRMED":
                                        trade = db.query(Trade).filter(
                                            Trade.clob_order_id == trade_id
                                        ).first()
                                        if trade and not trade.settled:
                                            trade.settled = True
                                            trade.settlement_time = time.time()
                                            db.commit()
                                            logger.info(f"Trade {trade_id} confirmed on-chain")

                                            async def _refresh_task():
                                                await _refresh_balance_cache()
                                            asyncio.create_task(_refresh_task())
                        except Exception as e:
                            logger.error(
                                f"[api.main.handle_user_trade] {type(e).__name__}: Error updating trade status: {e}",
                                exc_info=True
                            )

                    user_ws.on_user_order(lambda e: logger.info(f"Order update: {e.get('id')} - {e.get('status')}"))
                    user_ws.on_user_trade(_handle_user_trade)

                    user_ws_task = await _get_app().state.task_manager.create_task(
                        user_ws.connect(), name="polymarket_user_ws"
                    )
                    logger.info(f"Polymarket User WebSocket started for {len(condition_ids)} markets")
                else:
                    logger.warning("User WebSocket enabled but API credentials missing")
            else:
                logger.info("Polymarket User WebSocket disabled in settings")
        else:
            logger.info("Polymarket WebSocket disabled in settings")
    except Exception as e:
        logger.error(
            f"[api.main.lifespan] {type(e).__name__}: Failed to start Polymarket WebSocket: {e}",
            exc_info=True
        )

    # Use local _polymarket_ws_tasks
    _polymarket_ws_tasks["market"] = market_ws_task
    _polymarket_ws_tasks["user"] = user_ws_task


async def _startup_bankroll_reconciliation():
    """Perform bankroll reconciliation at startup."""
    try:
        from backend.db.utils import get_db_session
        with get_db_session() as db:
            await reconcile_bot_state(
                db,
                modes=("live",),
                apply=True,
                commit=True,
                source="api_startup_live_reconcile",
            )
    except Exception as e:
        logger.warning(
            f"[api.main.lifespan] {type(e).__name__}: Live bankroll startup reconciliation failed: {e}",
            exc_info=True,
        )


# Global reference to app (for use in inner functions)
_app_ref = None

def _get_app():
    """Get the FastAPI app reference."""
    return _app_ref


# Global state for background tasks and caches
_balance_cache = {"balance": None, "timestamp": 0, "mode": settings.TRADING_MODE}
_polymarket_ws_tasks = {"market": None, "user": None}


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
    logger.info(f"[LIFESPAN] WebSocket managers set in {_time.time() - start_time:.2f}s")

    logger.info("=" * 60)
    logger.info("BTC 5-MIN TRADING BOT v3.0")
    logger.info("=" * 60)

    _t0 = _time.time()
    logger.info("Initializing database...")
    from backend.models.database import init_db
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
    logger.info("[LIFESPAN] Lifespan duration: {:.2f}s".format(_time.time() - start_time))

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
            logger.info(f"[LIFESPAN] Registered mode context for {_mode} (clob={'SET' if _clob else 'NONE'}, strategies={len(_configs)})")

    yield

    # --- Shutdown ---
    getattr(app.state, 'shutdown_handler', None)
    shutdown_start = time.time()

    logger.info("=" * 60)
    logger.info("GRACEFUL SHUTDOWN SEQUENCE INITIATED")
    logger.info("=" * 60)

    try:
        logger.info("1. Stopping new request acceptance...")
        app.state.shutting_down = True
        logger.info("   ✓ New requests blocked")

        logger.info("2. Waiting for active requests to complete (max 5s)...")
        active_requests = getattr(app.state, 'active_requests', 0)
        wait_start = time.time()
        while active_requests > 0 and (time.time() - wait_start) < 5.0:
            await asyncio.sleep(0.1)
            active_requests = getattr(app.state, 'active_requests', 0)
        if active_requests > 0:
            logger.warning(f"   ⚠ {active_requests} active requests still pending after 5s")
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
                        logger.exception("Failed to close WebSocket connection during shutdown")
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

        logger.info("6. Shutting down Polymarket WebSocket...")
        # Use local _polymarket_ws_tasks
        if _polymarket_ws_tasks.get("market"):
            try:
                await shutdown_market_websocket()
                _polymarket_ws_tasks["market"].cancel()
                try:
                    await _polymarket_ws_tasks["market"]
                except asyncio.CancelledError:
                    pass
                logger.info("   ✓ Polymarket market WebSocket shut down")
            except Exception as e:
                logger.warning(f"   ⚠ Error shutting down market WebSocket: {e}")

        if _polymarket_ws_tasks.get("user"):
            try:
                await shutdown_user_websocket()
                _polymarket_ws_tasks["user"].cancel()
                try:
                    await _polymarket_ws_tasks["user"]
                except asyncio.CancelledError:
                    pass
                logger.info("   ✓ Polymarket user WebSocket shut down")
            except Exception as e:
                logger.warning(f"   ⚠ Error shutting down user WebSocket: {e}")

        logger.info("7. Shutting down TaskManager...")
        try:
            task_count = len(app.state.task_manager.tasks)
            await app.state.task_manager.shutdown()
            logger.info(f"   ✓ TaskManager shut down ({task_count} tasks cancelled)")
        except Exception as e:
            logger.warning(f"   ⚠ Error shutting down TaskManager: {e}")

        logger.info("8. Stopping scheduler...")
        try:
            from backend.core.scheduler import stop_scheduler
            stop_scheduler()
            logger.info("   ✓ Scheduler stopped")
        except Exception as e:
            logger.warning(f"   ⚠ Error stopping scheduler: {e}")

        logger.info("9. Waiting for in-flight jobs (max 3s)...")
        await asyncio.sleep(3.0)
        logger.info("   ✓ Grace period complete")

        logger.info("10. Closing database connections...")
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


async def _startup_wallet_sync():
    """Perform wallet sync during startup."""
    try:
        from backend.data.polymarket_clob import clob_from_settings
        for mode in ["live"]:
            if settings.is_mode_active("live") or settings.is_mode_active("paper"):
                try:
                    clob = clob_from_settings(mode=mode)
                    from backend.db.utils import get_db_session
                    with get_db_session() as reconciler_db:
                        reconciler = WalletReconciler(clob, reconciler_db, mode)
                        result = await reconciler.full_reconciliation()
                        state = reconciler_db.query(BotState).first()
                        if state:
                            state.last_sync_at = result.last_sync_at
                            reconciler_db.commit()
                        logger.info(
                            f"Startup recovery [{mode}]: imported={result.imported_count}, "
                            f"updated={result.updated_count}, closed={result.closed_count}, "
                            f"errors={len(result.errors)}"
                        )
                except Exception as e:
                    logger.warning(
                        f"[api.main.lifespan] {type(e).__name__}: Startup recovery [{mode}] failed: {e}",
                        exc_info=True,
                    )
    except Exception as e:
        logger.warning(f"Wallet sync failed: {e}", exc_info=True)


async def _seed_strategy_configs() -> None:
    """Seed default strategy configurations into the database.

    API startup must remain available even if the bot process is holding a
    SQLite write lock. This bootstrap step is therefore best-effort: retry a
    few times on lock contention, then continue startup with a warning.
    """
    import json as _json
    logger.info("Seeding strategy configs - START")

    strategy_defaults = [
        ("copy_trader", True, 300, "paper", {"max_wallets": 20, "min_score": 30.0, "poll_interval": 300}),
        ("whale_frontrun", True, 300, "paper", {"min_size": 5000, "min_score": 0.5, "frontrun_delay_ms": 50}),
        ("weather_emos", True, 300, "paper", {"min_edge": 0.05, "max_position_usd": 100, "calibration_window_days": 40}),
        ("kalshi_arb", True, 300, "paper", {"min_edge": 0.02, "allow_live_execution": False}),
        ("btc_oracle", True, 300, "live", {"min_edge": 0.02, "max_minutes_to_resolution": 30}),
        ("btc_oracle_legacy", False, 300, "live", {}),
        ("btc_momentum", False, 300, "live", {"max_trade_fraction": 0.03}),
        ("general_scanner", False, 300, "paper", {"min_volume": 50000, "min_edge": 0.05, "max_position_usd": 150}),
        ("bond_scanner", False, 600, "paper", {"min_price": 0.92, "max_price": 0.98, "max_position_usd": 200}),
        ("realtime_scanner", False, 60, "paper", {"min_edge": 0.03, "max_position_usd": 100}),
        ("whale_pnl_tracker", True, 300, "paper", {"max_whales": 5, "min_whale_score": 0.3, "min_trades": 20, "copy_fraction": 0.10, "min_position_size": 100, "signal_cooldown_minutes": 5, "pnl_signal_threshold": 0.05}),
        ("market_maker", False, 300, "paper", {"spread": 0.02, "max_position_usd": 200}),
    ]

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        from backend.db.utils import get_db_session
        try:
            with get_db_session() as db:
                _set_startup_sqlite_busy_timeout(db, 1000)
                added = 0
                for name, enabled, interval, mode, params in strategy_defaults:
                    exists = db.query(StrategyConfig).filter(StrategyConfig.strategy_name == name).first()
                    if not exists:
                        db.add(StrategyConfig(
                            strategy_name=name,
                            enabled=enabled,
                            interval_seconds=interval,
                            mode=mode,
                            params=_json.dumps(params),
                        ))
                        added += 1
                    else:
                        changed = False
                        if exists.mode != mode:
                            exists.mode = mode
                            changed = True
                        if exists.interval_seconds != interval:
                            exists.interval_seconds = interval
                            changed = True
                        new_params = _json.dumps(params)
                        if exists.params != new_params:
                            exists.params = new_params
                            changed = True
                        if changed:
                            added += 1
                if added:
                    db.commit()
                    logger.info(f"Committed {added} strategy config changes")
                    logger.info(f"Seeded {added} strategy configs into database")
                else:
                    logger.info("No strategy config changes needed")
                return
        except OperationalError as exc:
            if "database is locked" not in str(exc).lower() or attempt == max_attempts:
                logger.warning(
                    "Strategy config seeding skipped during startup after %s attempt(s): %s",
                    attempt,
                    exc,
                    exc_info=True,
                )
                return
            backoff = 0.5 * attempt
            logger.warning(
                "Strategy config seeding hit SQLite lock on attempt %s/%s; retrying in %.1fs",
                attempt,
                max_attempts,
                backoff,
            )
            await asyncio.sleep(backoff)
