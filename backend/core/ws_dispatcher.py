"""
Central WebSocket dispatcher for unified event-driven trading.

Orchestrates strategy subscription discovery, manages the shared Polymarket
WebSocket connection, dispatches real-time events through the EventBus, and
coordinates fail-safe fallback triggers on WebSocket disconnections.
"""

import asyncio
from typing import Dict, Set, List, Optional, Any
from loguru import logger

from backend.config import settings
from backend.core.event_bus import event_bus
from backend.data.polymarket_websocket import (
    PolymarketWebSocket,
    WebSocketConfig,
    ChannelType,
)
from backend.strategies.registry import STRATEGY_REGISTRY
from backend.core.ws_fallback import WsFirstExecutor


class WSDispatcher:
    """
    Central dispatcher coordinating the shared Polymarket WebSocket client
    and wiring event-driven strategies into the main signal pipeline.
    """

    def __init__(self) -> None:
        self._ws_client: Optional[PolymarketWebSocket] = None
        self._running: bool = False
        self._dispatch_task: Optional[asyncio.Task] = None
        self._strategies: Dict[str, Any] = {}
        self._subscribed_tokens: Set[str] = set()
        self._routers: List[Any] = []

    def register_router(self, router: Any) -> None:
        """Register custom orderbook/trade router adapters."""
        self._routers.append(router)
        if self._ws_client:
            router.register_with_websocket(self._ws_client)
            logger.info(f"WSDispatcher: dynamically registered router: {type(router).__name__}")

    async def start(self) -> None:
        """Initialize event-driven strategies, subscribe them, and start WebSocket stream."""
        if self._running:
            logger.warning("WSDispatcher is already running")
            return

        self._running = True
        logger.info("WSDispatcher: starting real-time WS pipeline...")

        # 1. Discover and initialize active event-driven strategies
        await self._initialize_strategies()

        # 2. Subscribe strategies to EventBus
        self._register_strategies_with_event_bus()

        # 3. Gather unified subscription tokens
        self._subscribed_tokens = event_bus.get_all_subscribed_tokens()
        limit = getattr(settings, "POLYMARKET_WS_SUBSCRIPTION_LIMIT", 100)
        tokens_list = list(self._subscribed_tokens)[:limit]

        logger.info(
            f"WSDispatcher: unified subscriptions resolved to {len(tokens_list)} tokens (limit={limit})"
        )

        if not tokens_list:
            logger.warning("WSDispatcher: no strategies registered token subscriptions. WS stream will not start.")
            # Set state to connected fallback to let periodic polling operate normally
            event_bus.set_ws_disconnected()
            return

        # 4. Initialize and start the single shared PolymarketWebSocket client
        ws_config = WebSocketConfig(
            channel=ChannelType.MARKET,
            asset_ids=tokens_list,
        )
        self._ws_client = PolymarketWebSocket(ws_config)

        # Wire any registered custom routers
        for r in self._routers:
            r.register_with_websocket(self._ws_client)
            logger.info(f"WSDispatcher: wired router: {type(r).__name__}")

        # Wire WS state change events into EventBus
        # When WS connection establishes or drops, let EventBus know to coordinate fallbacks
        async def on_connect_handler(*args, **kwargs):
            event_bus.set_ws_connected()

        async def on_disconnect_handler(*args, **kwargs):
            event_bus.set_ws_disconnected()

        # PolymarketWebSocket doesn't have direct on_connect/on_disconnect callback arrays,
        # but we can patch _connect_and_run or monitor it. Let's run a watchdog task to monitor health.
        self._dispatch_task = asyncio.create_task(self._run_ws_and_monitor())
        logger.info("WSDispatcher: WebSocket stream task scheduled")

    async def stop(self) -> None:
        """Gracefully stop the WS pipeline and disconnect WebSocket."""
        self._running = False
        logger.info("WSDispatcher: stopping WS pipeline...")

        if self._ws_client:
            self._ws_client._running = False
            if self._ws_client.ws:
                try:
                    await self._ws_client.ws.close()
                except Exception as e:
                    logger.debug(f"WSDispatcher: error closing WebSocket: {e}")
            self._ws_client = None

        if self._dispatch_task and not self._dispatch_task.done():
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
            self._dispatch_task = None

        # Clean up strategy event subscriptions
        for name in list(self._strategies.keys()):
            event_bus.unsubscribe_strategy(name)

        event_bus.set_ws_disconnected()
        logger.info("WSDispatcher: WS pipeline stopped successfully")

    async def update_subscriptions(self) -> None:
        """Scan strategies for token changes and dynamically update WebSocket subscription."""
        if not self._running or not self._ws_client:
            return

        # Discover dynamic updates
        for name, strategy in self._strategies.items():
            if hasattr(strategy, "_populate_subscribed_tokens"):
                try:
                    await strategy._populate_subscribed_tokens()
                except Exception as e:
                    logger.warning(f"WSDispatcher: failed to refresh tokens for {name}: {e}")

            tokens = getattr(strategy, "subscribed_tokens", set())
            if tokens:
                event_bus.update_strategy_tokens(name, tokens)

        new_tokens = event_bus.get_all_subscribed_tokens()
        limit = getattr(settings, "POLYMARKET_WS_SUBSCRIPTION_LIMIT", 100)
        new_tokens_list = list(new_tokens)[:limit]

        # If subscriptions changed, update WS client and trigger reconnect to apply immediately
        current_ids = set(self._ws_client.config.asset_ids)
        if set(new_tokens_list) != current_ids:
            logger.info(
                f"WSDispatcher: subscriptions changed. Updating from {len(current_ids)} to {len(new_tokens_list)} asset IDs."
            )
            self._ws_client.update_asset_ids(new_tokens_list)
            # Safely close current connection to trigger exponential backoff reset/immediate reconnect
            if self._ws_client.ws:
                logger.info("WSDispatcher: reconnecting to apply new subscriptions...")
                await self._ws_client.ws.close()

    async def _initialize_strategies(self) -> None:
        """Find and initialize all active strategies in registry."""
        from backend.db.utils import get_db_session
        from backend.models.database import StrategyConfig

        with get_db_session() as db:
            active_configs = {
                cfg.strategy_name: cfg
                for cfg in db.query(StrategyConfig).filter(StrategyConfig.enabled.is_(True)).all()
            }

        for name, strategy_cls in STRATEGY_REGISTRY.items():
            # Only load if enabled in StrategyConfig (or is a core default strategy)
            if name not in active_configs:
                continue

            try:
                strategy = strategy_cls()
                # Run async initialization if exists
                if hasattr(strategy, "_populate_subscribed_tokens"):
                    await strategy._populate_subscribed_tokens()
                elif hasattr(strategy, "subscribed_tokens") and not strategy.subscribed_tokens:
                    # Fallback for strategies that define custom setup
                    if hasattr(strategy, "setup"):
                        await strategy.setup()

                self._strategies[name] = strategy
                logger.info(
                    f"WSDispatcher: initialized strategy '{name}' with {len(getattr(strategy, 'subscribed_tokens', set()))} tokens"
                )
            except Exception as e:
                logger.exception(f"WSDispatcher: failed to initialize strategy '{name}': {e}")

    def _register_strategies_with_event_bus(self) -> None:
        """Register all initialized strategy event handlers with the central EventBus."""
        for name, strategy in self._strategies.items():
            tokens = getattr(strategy, "subscribed_tokens", set())
            events = getattr(strategy, "subscribed_events", {"last_trade_price"})

            if not tokens:
                logger.debug(f"WSDispatcher: strategy '{name}' has no active token subscriptions. Skipping registration.")
                continue

            executor = WsFirstExecutor(name)
            event_bus.subscribe_strategy(
                strategy_name=name,
                token_ids=tokens,
                event_types=events,
                handler=strategy.on_market_event,
                fallback_handler=executor.on_ws_disconnected,
            )
            logger.info(f"WSDispatcher: subscribed '{name}' to EventBus (tokens={len(tokens)})")

    async def _run_ws_and_monitor(self) -> None:
        """Run the PolymarketWebSocket connection and monitor connection state."""
        ws_client = self._ws_client
        if not ws_client:
            return

        # Start the WebSocket connection in a background task
        ws_task = asyncio.create_task(ws_client.connect())

        try:
            while self._running:
                await asyncio.sleep(1)
                # Monitor state and notify EventBus
                if ws_client.ws and ws_client.ws.open:
                    if not event_bus.ws_connected:
                        event_bus.set_ws_connected()
                        # Trigger reconnect on active strategies
                        for strat in self._strategies.values():
                            if hasattr(strat, "on_ws_reconnected"):
                                try:
                                    await strat.on_ws_reconnected()
                                except Exception as e:
                                    logger.error(f"WSDispatcher: error on WS reconnect hook for strategy: {e}")
                else:
                    if event_bus.ws_connected:
                        event_bus.set_ws_disconnected()
                        # Trigger halt on active strategies immediately
                        for strat in self._strategies.values():
                            if hasattr(strat, "on_ws_disconnected"):
                                try:
                                    await strat.on_ws_disconnected()
                                except Exception as e:
                                    logger.error(f"WSDispatcher: error on WS disconnect hook for strategy: {e}")

            # If stopped, cancel the task
            ws_task.cancel()
            try:
                await ws_task
            except asyncio.CancelledError:
                pass
        except asyncio.CancelledError:
            ws_task.cancel()
            try:
                await ws_task
            except asyncio.CancelledError:
                pass
        except Exception as e:
            logger.error(f"WSDispatcher: connection loop encountered error: {e}")
            event_bus.set_ws_disconnected()


# Module level singleton
ws_dispatcher = WSDispatcher()
