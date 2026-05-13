import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Awaitable, Optional, Any

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker

from loguru import logger


@dataclass
class OrderbookUpdate:
    """Real-time orderbook update from WebSocket"""
    market_id: str
    bids_yes: List[Dict[str, str]]
    asks_yes: List[Dict[str, str]]
    bids_no: List[Dict[str, str]]
    asks_no: List[Dict[str, str]]
    timestamp: int

    def to_snapshot(self) -> 'OrderbookSnapshot':
        """Convert update to snapshot format"""
        timestamp = self.timestamp / 1000 if self.timestamp > 10_000_000_000 else self.timestamp
        return OrderbookSnapshot(
            market_id=self.market_id,
            best_bid_yes=float(self.bids_yes[0]['price']) if self.bids_yes else 0.0,
            best_ask_yes=float(self.asks_yes[0]['price']) if self.asks_yes else 0.0,
            best_bid_no=float(self.bids_no[0]['price']) if self.bids_no else 0.0,
            best_ask_no=float(self.asks_no[0]['price']) if self.asks_no else 0.0,
            timestamp=datetime.fromtimestamp(timestamp)
        )


@dataclass
class OrderbookSnapshot:
    """Orderbook snapshot for strategy analysis"""
    market_id: str
    best_bid_yes: float
    best_ask_yes: float
    best_bid_no: float
    best_ask_no: float
    timestamp: datetime


class OrderbookRouter:
    """Bridges WebSocket ticks to strategy handlers with queue-based dispatch."""

    def __init__(self):
        self._handlers: Dict[str, List[Callable[[OrderbookUpdate], Awaitable[None]]]] = {}
        self._snapshots: Dict[str, OrderbookSnapshot] = {}
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._dispatch_task: Optional[asyncio.Task] = None
        self._running = False

        self._circuit_breaker = CircuitBreaker(
            name="polymarket_ws",
            failure_threshold=5,
            recovery_timeout=60
        )

    async def start(self) -> None:
        """Start the dispatch loop"""
        if self._running:
            return
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        logger.info("OrderbookRouter dispatch loop started")

    async def stop(self) -> None:
        """Stop the dispatch loop"""
        if not self._running:
            return
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Error stopping OrderbookRouter dispatch loop: {e}")
            finally:
                self._dispatch_task = None
        logger.info("OrderbookRouter dispatch loop stopped")

    async def subscribe(
        self,
        market_id: str,
        handler: Callable[[OrderbookUpdate], Awaitable[None]]
    ) -> None:
        """Register handler for market updates"""
        # Count total handlers across all markets
        total_handlers = sum(len(handlers) for handlers in self._handlers.values())
        if total_handlers >= settings.POLYMARKET_WS_SUBSCRIPTION_LIMIT:
            logger.warning(
                f"ws_subscription_limit_reached: limit={settings.POLYMARKET_WS_SUBSCRIPTION_LIMIT}"
            )
            return

        if market_id not in self._handlers:
            self._handlers[market_id] = []
        self._handlers[market_id].append(handler)
        logger.debug(f"Registered handler for market {market_id}")

    async def _dispatch_loop(self) -> None:
        """Reads from queue and dispatches to registered handlers"""
        while self._running:
            try:
                update: OrderbookUpdate = await self._queue.get()
                handlers = self._handlers.get(update.market_id, [])

                for handler in handlers:
                    try:
                        await asyncio.wait_for(
                            handler(update),
                            timeout=settings.WS_HANDLER_TIMEOUT_MS / 1000.0
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            "ws_handler_timeout",
                            market_id=update.market_id,
                            timeout_ms=settings.WS_HANDLER_TIMEOUT_MS
                        )
                    except Exception as e:
                        logger.error(
                            f"ws_handler_error: market_id={update.market_id} error={e}"
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"dispatch_loop_error: {e}")
                await asyncio.sleep(1)

    async def _on_orderbook_update(self, update: Any) -> None:
        """Callback from PolymarketWebSocket - queue the update"""
        try:
            if not isinstance(update, OrderbookUpdate):
                update = self._adapt_ws_snapshot(update)

            self._snapshots[update.market_id] = update.to_snapshot()

            # Drop oldest item if queue is full
            if self._queue.full():
                self._queue.get_nowait()

            await self._queue.put(update)
        except Exception as e:
            logger.opt(exception=True).error(f"queue_orderbook_update_error: {e}")

    def _adapt_ws_snapshot(self, snapshot: Any) -> OrderbookUpdate:
        """Adapt backend.data.polymarket_websocket.OrderbookSnapshot to router format."""

        return OrderbookUpdate(
            market_id=str(getattr(snapshot, "asset_id", "") or getattr(snapshot, "market", "")),
            bids_yes=list(getattr(snapshot, "bids", []) or []),
            asks_yes=list(getattr(snapshot, "asks", []) or []),
            bids_no=[],
            asks_no=[],
            timestamp=int(getattr(snapshot, "timestamp", 0) or 0),
        )

    def get_snapshot(self, market_id: str) -> Optional[OrderbookSnapshot]:
        """Get latest snapshot for market"""
        return self._snapshots.get(market_id)

    async def _check_circuit_breaker(self) -> bool:
        """Check if circuit breaker is open"""
        if self._circuit_breaker.state == "OPEN":
            logger.critical("ws_circuit_open_scheduler_fallback_activated")
            return True
        return False

    def register_with_websocket(self, websocket_client):
        """Register this router as handler with PolymarketWebSocket"""
        websocket_client.on_orderbook(self._on_orderbook_update)
