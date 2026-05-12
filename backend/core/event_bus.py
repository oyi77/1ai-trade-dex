"""
Event bus for SSE broadcasting, internal event-driven dispatch, and strategy-to-WS bridging.

This module provides a centralized event system for:
1. SSE subscriber queues (frontend dashboard)
2. Typed handler callbacks (backend modules)
3. Strategy subscription management (token-filtered WS event routing)
4. WS connection state tracking and life-cycle events

Strategy subscriptions enable event-driven execution:
- Strategy registers interest in specific token IDs and event types
- WS events are filtered and dispatched only to subscribed strategies
- WS disconnect triggers fallback notification to affected strategies
"""
import asyncio
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict, Any, List, Callable, Awaitable, Optional, Set

from loguru import logger

EventHandler = Callable[[str, Dict[str, Any]], Awaitable[None]]
StrategyHandler = Callable[["MarketEvent"], Awaitable[Optional[dict]]]


class MarketEvent:
    """Typed market event delivered to strategy handlers."""
    __slots__ = ("token_id", "event_type", "data", "timestamp")

    def __init__(self, token_id: str, event_type: str, data: Dict[str, Any], timestamp: Optional[float] = None):
        self.token_id = token_id
        self.event_type = event_type
        self.data = data
        self.timestamp = timestamp or time.time()


class StrategySubscription:
    """A strategy's subscription to specific tokens and event types."""
    __slots__ = ("strategy_name", "token_ids", "event_types", "handler", "fallback_handler")

    def __init__(
        self,
        strategy_name: str,
        token_ids: Set[str],
        event_types: Set[str],
        handler: StrategyHandler,
        fallback_handler: Optional[Callable[[], Awaitable[None]]] = None,
    ):
        self.strategy_name = strategy_name
        self.token_ids = token_ids
        self.event_types = event_types
        self.handler = handler
        self.fallback_handler = fallback_handler


class EventBus:
    """
    Centralized event system for SSE broadcasting, internal dispatch, and strategy-to-WS bridging.
    """

    def __init__(self, history_maxlen: int = 50):
        self._subscribers: List[asyncio.Queue] = []
        self._history: deque = deque(maxlen=history_maxlen)
        self._handlers: Dict[str, List[EventHandler]] = defaultdict(list)

        # Strategy subscriptions: {strategy_name: StrategySubscription}
        self._strategy_subs: Dict[str, StrategySubscription] = {}
        # Token index: {token_id: [strategy_name, ...]}
        self._token_index: Dict[str, List[str]] = defaultdict(list)

        # WS connection state
        self._ws_connected: bool = False
        self._ws_disconnected_at: Optional[float] = None
        self._events_dispatched: int = 0
        self._dispatch_times: deque = deque(maxlen=100)

    # ── SSE subscribers (frontend) ──

    def subscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.append(queue)
        logger.debug(f"New subscriber added. Total subscribers: {len(self._subscribers)}")

    def unsubscribe(self, queue: asyncio.Queue) -> bool:
        try:
            self._subscribers.remove(queue)
            return True
        except ValueError:
            return False

    # ── Typed event handlers (backend modules) ──

    def subscribe_handler(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe_handler(self, event_type: str, handler: EventHandler) -> None:
        try:
            self._handlers[event_type].remove(handler)
        except ValueError:
            pass

    # ── Strategy subscriptions (token-filtered WS events) ──

    def subscribe_strategy(
        self,
        strategy_name: str,
        token_ids: Set[str],
        event_types: Set[str],
        handler: StrategyHandler,
        fallback_handler: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        sub = StrategySubscription(strategy_name, token_ids, event_types, handler, fallback_handler)
        self._strategy_subs[strategy_name] = sub
        for tid in token_ids:
            if strategy_name not in self._token_index[tid]:
                self._token_index[tid].append(strategy_name)
        logger.info("Strategy '%s' subscribed: %d tokens, %d event types", strategy_name, len(token_ids), len(event_types))

    def unsubscribe_strategy(self, strategy_name: str) -> None:
        sub = self._strategy_subs.pop(strategy_name, None)
        if sub:
            for tid in sub.token_ids:
                try:
                    self._token_index[tid].remove(strategy_name)
                    if not self._token_index[tid]:
                        del self._token_index[tid]
                except (ValueError, KeyError):
                    pass
            logger.info("Strategy '%s' unsubscribed", strategy_name)

    def get_strategy_tokens(self, strategy_name: str) -> Set[str]:
        sub = self._strategy_subs.get(strategy_name)
        return sub.token_ids if sub else set()

    def update_strategy_tokens(self, strategy_name: str, token_ids: Set[str]) -> None:
        sub = self._strategy_subs.get(strategy_name)
        if not sub:
            return
        removed = sub.token_ids - token_ids
        added = token_ids - sub.token_ids
        for tid in removed:
            try:
                self._token_index[tid].remove(strategy_name)
                if not self._token_index[tid]:
                    del self._token_index[tid]
            except (ValueError, KeyError):
                pass
        for tid in added:
            if strategy_name not in self._token_index[tid]:
                self._token_index[tid].append(strategy_name)
        sub.token_ids = token_ids
        logger.debug("Strategy '%s' tokens updated: +%d -%d", strategy_name, len(added), len(removed))

    def get_all_subscribed_tokens(self) -> Set[str]:
        tokens: Set[str] = set()
        for sub in self._strategy_subs.values():
            tokens.update(sub.token_ids)
        return tokens

    def get_subscription_status(self) -> List[Dict[str, Any]]:
        return [
            {
                "strategy": s.strategy_name,
                "tokens": len(s.token_ids),
                "events": list(s.event_types),
                "has_fallback": s.fallback_handler is not None,
            }
            for s in self._strategy_subs.values()
        ]

    # ── WS lifecycle ──

    def set_ws_connected(self) -> None:
        was_disconnected = not self._ws_connected
        self._ws_connected = True
        self._ws_disconnected_at = None
        if was_disconnected:
            logger.info("EventBus: WebSocket reconnected")
            self.publish("ws_reconnected", {"since": datetime.now(timezone.utc).isoformat()})
            for sub in self._strategy_subs.values():
                self.publish("ws_reconnected_strategy", {"strategy_name": sub.strategy_name})

    def set_ws_disconnected(self) -> None:
        if not self._ws_connected:
            return
        self._ws_connected = False
        self._ws_disconnected_at = time.time()
        logger.warning("EventBus: WebSocket disconnected")
        self.publish("ws_disconnected", {"since": datetime.now(timezone.utc).isoformat()})
        for sub in self._strategy_subs.values():
            self.publish("ws_disconnected_strategy", {"strategy_name": sub.strategy_name})
            if sub.fallback_handler:
                asyncio.ensure_future(sub.fallback_handler())

    @property
    def ws_connected(self) -> bool:
        return self._ws_connected

    @property
    def ws_disconnected_seconds(self) -> float:
        if self._ws_connected or self._ws_disconnected_at is None:
            return 0.0
        return time.time() - self._ws_disconnected_at

    # ── Publish (with token-filtered strategy dispatch) ──

    def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        payload = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        self._history.append(payload)

        # SSE subscribers (frontend)
        for queue in self._subscribers[:]:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass

        # Typed handlers (backend modules)
        for handler in self._handlers.get(event_type, []):
            try:
                asyncio.ensure_future(handler(event_type, data))
            except Exception as exc:
                logger.warning("Event handler failed for '%s': %s", event_type, exc)

        # Strategy dispatch (token-filtered)
        token_id = data.get("asset_id") or data.get("token_id", "")
        if token_id and token_id in self._token_index:
            self._dispatch_to_strategies(token_id, event_type, data)

    def _dispatch_to_strategies(self, token_id: str, event_type: str, data: Dict[str, Any]) -> None:
        for strategy_name in self._token_index.get(token_id, []):
            sub = self._strategy_subs.get(strategy_name)
            if not sub:
                continue
            if event_type not in sub.event_types:
                continue
            event = MarketEvent(token_id=token_id, event_type=event_type, data=data)
            try:
                t0 = time.time()
                asyncio.ensure_future(self._invoke_handler(strategy_name, sub.handler, event, t0))
            except Exception as exc:
                logger.warning("Strategy dispatch failed for '%s': %s", strategy_name, exc)

    async def _invoke_handler(self, strategy_name: str, handler: StrategyHandler, event: MarketEvent, t0: float) -> None:
        try:
            result = await handler(event)
            elapsed = (time.time() - t0) * 1000
            self._dispatch_times.append(elapsed)
            self._events_dispatched += 1
            if result:
                logger.debug("Strategy '%s' returned decision: %s (%.1fms)", strategy_name, result.get("decision", "?"), elapsed)
        except Exception as exc:
            logger.error("Strategy '%s' handler crashed: %s", strategy_name, exc, exc_info=True)

    # ── Statistics / health ──

    def get_health(self) -> Dict[str, Any]:
        times = list(self._dispatch_times)
        return {
            "ws_connected": self._ws_connected,
            "ws_disconnected_seconds": round(self.ws_disconnected_seconds, 1),
            "subscriptions": self.get_subscription_status(),
            "total_subscribed_tokens": len(self._token_index),
            "events_dispatched": self._events_dispatched,
            "dispatch_latency_p50_ms": round(self._percentile(times, 50), 1) if times else 0,
            "dispatch_latency_p99_ms": round(self._percentile(times, 99), 1) if times else 0,
        }

    @staticmethod
    def _percentile(sorted_values: List[float], pct: float) -> float:
        if not sorted_values:
            return 0.0
        values = sorted(sorted_values)
        idx = int(len(values) * pct / 100)
        return values[min(idx, len(values) - 1)]

    def get_history(self) -> List[Dict[str, Any]]:
        return list(self._history)

    def subscriber_count(self) -> int:
        return len(self._subscribers)


# Module-level instance
event_bus = EventBus()


def publish_event(event_type: str, data: Dict[str, Any]) -> None:
    event_bus.publish(event_type, data)


def subscribe_handler(event_type: str, handler: EventHandler) -> None:
    event_bus.subscribe_handler(event_type, handler)


def subscribe_strategy(
    strategy_name: str,
    token_ids: Set[str],
    event_types: Set[str],
    handler: StrategyHandler,
    fallback_handler: Optional[Callable[[], Awaitable[None]]] = None,
) -> None:
    event_bus.subscribe_strategy(strategy_name, token_ids, event_types, handler, fallback_handler)


def unsubscribe_strategy(strategy_name: str) -> None:
    event_bus.unsubscribe_strategy(strategy_name)


def get_event_history() -> List[Dict[str, Any]]:
    return event_bus.get_history()


def _broadcast_event(event_type: str, data: Dict[str, Any]) -> None:
    publish_event(event_type, data)
