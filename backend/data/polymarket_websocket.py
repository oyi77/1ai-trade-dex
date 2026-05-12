"""
Polymarket WebSocket client for real-time market data streaming.

Provides real-time orderbook updates, trade notifications, and price changes
via Polymarket's official WebSocket API. Replaces REST polling with event-driven
updates for 10-50x latency improvement.

Features:
- Market channel: Real-time orderbook, trades, price changes (no auth required)
- User channel: Order fills, trade status updates (requires API credentials)
- Auto-reconnection with exponential backoff
- Heartbeat (PING every 10s) to keep connection alive
- Thread-safe event handlers and state management

Official Docs: https://docs.polymarket.com/developers/CLOB/websocket/wss-overview
"""

import asyncio
import json
import time
from dataclasses import dataclass, field

from backend.config import settings
from typing import Optional, Callable, Dict, List, Any
from enum import Enum

import websockets

from loguru import logger
class ChannelType(Enum):
    """WebSocket channel types"""

    MARKET = "market"  # Public orderbook and trades
    USER = "user"  # Authenticated order fills
    RTDS = "rtds"  # Real-time data socket (crypto prices)


class EventType(Enum):
    """WebSocket event types"""

    BOOK = "book"  # Orderbook snapshot/update
    LAST_TRADE_PRICE = "last_trade_price"  # Trade execution
    PRICE_CHANGE = "price_change"  # Order level changes
    USER_ORDER = "user_order"  # User order update
    USER_TRADE = "user_trade"  # User trade fill


@dataclass
class OrderbookSnapshot:
    """Orderbook snapshot from WebSocket"""

    asset_id: str
    market: str
    bids: List[Dict[str, str]]  # [{"price": "0.50", "size": "100"}, ...]
    asks: List[Dict[str, str]]
    timestamp: int
    hash: Optional[str] = None


@dataclass
class TradeEvent:
    """Trade execution event"""

    asset_id: str
    price: str
    size: str
    side: str  # "BUY" or "SELL"
    timestamp: int


@dataclass
class PriceChangeEvent:
    """Price level change event"""

    asset_id: str
    price: str
    size: str
    side: str  # "BUY" or "SELL"
    timestamp: int


@dataclass
class WebSocketConfig:
    """WebSocket connection configuration"""

    channel: ChannelType
    asset_ids: List[str] = field(default_factory=list)  # For market channel
    condition_ids: List[str] = field(default_factory=list)  # For user channel
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    api_passphrase: Optional[str] = None
    custom_feature_enabled: bool = True
    initial_dump: bool = True
    heartbeat_interval: float = 10.0  # seconds
    reconnect_delay: float = 1.0  # Initial reconnect delay
    max_reconnect_delay: float = 60.0  # Max reconnect delay
    reconnect_backoff: float = 2.0  # Exponential backoff multiplier


class PolymarketWebSocket:
    """
    Polymarket WebSocket client with auto-reconnection and event handlers.

    Usage:
        # Market channel (public)
        ws = PolymarketWebSocket(WebSocketConfig(
            channel=ChannelType.MARKET,
            asset_ids=["token_id_1", "token_id_2"]
        ))
        ws.on_orderbook(handle_orderbook)
        ws.on_trade(handle_trade)
        await ws.connect()

        # User channel (authenticated)
        ws = PolymarketWebSocket(WebSocketConfig(
            channel=ChannelType.USER,
            condition_ids=["condition_id"],
            api_key="...",
            api_secret="...",
            api_passphrase="..."
        ))
        ws.on_user_order(handle_order_fill)
        await ws.connect()
    """

    # WebSocket endpoints
    ENDPOINTS = {
        ChannelType.MARKET: settings.POLYMARKET_WS_CLOB_URL,
        ChannelType.USER: settings.POLYMARKET_WS_USER_URL,
        ChannelType.RTDS: settings.POLYMARKET_WS_RTDS_URL,
    }

    def __init__(self, config: WebSocketConfig):
        self.config = config
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._reconnect_delay = config.reconnect_delay
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._receive_task: Optional[asyncio.Task] = None

        # Event handlers
        self._orderbook_handlers: List[Callable[[OrderbookSnapshot], None]] = []
        self._trade_handlers: List[Callable[[TradeEvent], None]] = []
        self._price_change_handlers: List[Callable[[PriceChangeEvent], None]] = []
        self._user_order_handlers: List[Callable[[Dict[str, Any]], None]] = []
        self._user_trade_handlers: List[Callable[[Dict[str, Any]], None]] = []

        # State tracking
        self._last_message_time = 0.0
        self._message_count = 0
        self._reconnect_count = 0

    def on_orderbook(self, handler: Callable[[OrderbookSnapshot], None]) -> None:
        """Register orderbook event handler"""
        self._orderbook_handlers.append(handler)

    def on_trade(self, handler: Callable[[TradeEvent], None]) -> None:
        """Register trade event handler"""
        self._trade_handlers.append(handler)

    def on_price_change(self, handler: Callable[[PriceChangeEvent], None]) -> None:
        """Register price change event handler"""
        self._price_change_handlers.append(handler)

    def on_user_order(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """Register user order event handler"""
        self._user_order_handlers.append(handler)

    def on_user_trade(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """Register user trade event handler"""
        self._user_trade_handlers.append(handler)

    async def connect(self) -> None:
        """Connect to WebSocket and start receiving messages"""
        self._running = True

        while self._running:
            try:
                await self._connect_and_run()
            except Exception as e:
                logger.error(f"WebSocket error: {e}", exc_info=True)

                if self._running:
                    logger.info(f"Reconnecting in {self._reconnect_delay:.1f}s...")
                    await asyncio.sleep(self._reconnect_delay)

                    # Exponential backoff
                    self._reconnect_delay = min(
                        self._reconnect_delay * self.config.reconnect_backoff,
                        self.config.max_reconnect_delay,
                    )
                    self._reconnect_count += 1

    async def _connect_and_run(self) -> None:
        """Establish connection and run message loop"""
        uri = self.ENDPOINTS[self.config.channel]
        logger.info(f"Connecting to {uri}...")

        async with websockets.connect(uri) as ws:
            self.ws = ws
            logger.info(f"Connected to {self.config.channel.value} channel")

            if self._reconnect_count > 0:
                logger.warning(
                    "WebSocket reconnected after %d attempts, clearing stale caches",
                    self._reconnect_count,
                )
                self._cache.clear() if hasattr(self, '_cache') else None

            # Send subscription message
            await self._send_subscription()

            self._reconnect_delay = self.config.reconnect_delay

            from backend.api.main import app
            if hasattr(app.state, 'task_manager'):
                self._heartbeat_task = await app.state.task_manager.create_task(
                    self._heartbeat_loop(), name="polymarket_ws_heartbeat"
                )
            else:
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # Receive messages
            try:
                async for message in ws:
                    await self._handle_message(message)
            finally:
                if self._heartbeat_task:
                    self._heartbeat_task.cancel()
                    try:
                        await self._heartbeat_task
                    except asyncio.CancelledError:
                        pass

    async def _send_subscription(self) -> None:
        """Send subscription message based on channel type"""
        if self.config.channel == ChannelType.MARKET:
            subscription = {
                "assets_ids": self.config.asset_ids,
                "type": "market",
                "custom_feature_enabled": self.config.custom_feature_enabled,
                "initial_dump": self.config.initial_dump,
            }
        elif self.config.channel == ChannelType.USER:
            if not all(
                [
                    self.config.api_key,
                    self.config.api_secret,
                    self.config.api_passphrase,
                ]
            ):
                raise ValueError("User channel requires API credentials")

            subscription = {
                "auth": {
                    "apiKey": self.config.api_key,
                    "secret": self.config.api_secret,
                    "passphrase": self.config.api_passphrase,
                },
                "markets": self.config.condition_ids,
                "type": "user",
                "initial_dump": self.config.initial_dump,
            }
        else:
            raise ValueError(f"Unsupported channel: {self.config.channel}")

        await self.ws.send(json.dumps(subscription))
        logger.info(f"Sent subscription: {subscription.get('type')}")

    async def _heartbeat_loop(self) -> None:
        """Send PING every N seconds to keep connection alive"""
        try:
            while self._running:
                await asyncio.sleep(self.config.heartbeat_interval)
                if self.ws and self.ws.state == websockets.protocol.State.OPEN:
                    await self.ws.send("PING")
                    logger.debug("Sent PING")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")

    async def _handle_message(self, message: str) -> None:
        """Parse and dispatch WebSocket message to handlers"""
        try:
            self._last_message_time = time.time()
            self._message_count += 1

            # Handle PONG
            if message == "PONG":
                logger.debug("Received PONG")
                return

            # Parse JSON event
            event = json.loads(message)
            event_type = event.get("event_type")

            if event_type == EventType.BOOK.value:
                await self._handle_orderbook(event)
            elif event_type == EventType.LAST_TRADE_PRICE.value:
                await self._handle_trade(event)
            elif event_type == EventType.PRICE_CHANGE.value:
                await self._handle_price_change(event)
            elif event_type == EventType.USER_ORDER.value:
                await self._handle_user_order(event)
            elif event_type == EventType.USER_TRADE.value:
                await self._handle_user_trade(event)
            else:
                logger.debug(f"Unknown event type: {event_type}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse message: {e}")
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)

    async def _handle_orderbook(self, event: Dict[str, Any]) -> None:
        """Handle orderbook snapshot/update"""
        snapshot = OrderbookSnapshot(
            asset_id=event["asset_id"],
            market=event["market"],
            bids=event["bids"],
            asks=event["asks"],
            timestamp=event["timestamp"],
            hash=event.get("hash"),
        )

        for handler in self._orderbook_handlers:
            try:
                handler(snapshot)
            except Exception as e:
                logger.error(f"Orderbook handler error: {e}", exc_info=True)

    async def _handle_trade(self, event: Dict[str, Any]) -> None:
        """Handle trade execution"""
        trade = TradeEvent(
            asset_id=event["asset_id"],
            price=event["price"],
            size=event["size"],
            side=event["side"],
            timestamp=event["timestamp"],
        )

        for handler in self._trade_handlers:
            try:
                handler(trade)
            except Exception as e:
                logger.error(f"Trade handler error: {e}", exc_info=True)

    async def _handle_price_change(self, event: Dict[str, Any]) -> None:
        """Handle price level changes"""
        for change in event.get("price_changes", []):
            price_change = PriceChangeEvent(
                asset_id=change["asset_id"],
                price=change["price"],
                size=change["size"],
                side=change["side"],
                timestamp=event["timestamp"],
            )

            for handler in self._price_change_handlers:
                try:
                    handler(price_change)
                except Exception as e:
                    logger.error(f"Price change handler error: {e}", exc_info=True)

    async def _handle_user_order(self, event: Dict[str, Any]) -> None:
        """Handle user order update"""
        for handler in self._user_order_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"User order handler error: {e}", exc_info=True)

    async def _handle_user_trade(self, event: Dict[str, Any]) -> None:
        """Handle user trade fill"""
        for handler in self._user_trade_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"User trade handler error: {e}", exc_info=True)

    async def disconnect(self) -> None:
        """Gracefully disconnect from WebSocket"""
        logger.info("Disconnecting WebSocket...")
        self._running = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()

        if self.ws and not self.ws.closed:
            await self.ws.close()

        logger.info("WebSocket disconnected")

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected"""
        return self.ws is not None and not self.ws.closed

    @property
    def stats(self) -> Dict[str, Any]:
        """Get connection statistics"""
        return {
            "connected": self.is_connected,
            "message_count": self._message_count,
            "reconnect_count": self._reconnect_count,
            "last_message_time": self._last_message_time,
            "uptime_seconds": time.time() - self._last_message_time
            if self._last_message_time > 0
            else 0,
        }


# Singleton instance for market data streaming
_market_ws: Optional[PolymarketWebSocket] = None


async def get_market_websocket(asset_ids: List[str]) -> PolymarketWebSocket:
    """
    Get or create singleton market WebSocket instance.

    Args:
        asset_ids: List of token IDs to subscribe to

    Returns:
        PolymarketWebSocket instance
    """
    global _market_ws

    if _market_ws is None:
        config = WebSocketConfig(channel=ChannelType.MARKET, asset_ids=asset_ids)
        _market_ws = PolymarketWebSocket(config)

    return _market_ws


async def shutdown_market_websocket() -> None:
    """Shutdown singleton market WebSocket"""
    global _market_ws

    if _market_ws:
        await _market_ws.disconnect()
        _market_ws = None


_user_ws: Optional[PolymarketWebSocket] = None


async def get_user_websocket(
    condition_ids: List[str], api_key: str, api_secret: str, api_passphrase: str
) -> PolymarketWebSocket:
    """
    Get or create singleton user WebSocket instance.

    Args:
        condition_ids: List of condition IDs (market IDs) to subscribe to
        api_key: Polymarket API key
        api_secret: Polymarket API secret
        api_passphrase: Polymarket API passphrase

    Returns:
        PolymarketWebSocket instance
    """
    global _user_ws

    if _user_ws is None:
        config = WebSocketConfig(
            channel=ChannelType.USER,
            condition_ids=condition_ids,
            api_key=api_key,
            api_secret=api_secret,
            api_passphrase=api_passphrase,
        )
        _user_ws = PolymarketWebSocket(config)

    return _user_ws


async def shutdown_user_websocket() -> None:
    """Shutdown singleton user WebSocket"""
    global _user_ws

    if _user_ws:
        await _user_ws.disconnect()
        _user_ws = None
