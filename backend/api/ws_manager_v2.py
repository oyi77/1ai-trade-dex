"""Topic-based WebSocket manager for selective broadcasting.

Enables clients to subscribe to specific topics and receive only messages
relevant to those topics. Replaces the broadcast-to-all pattern with
topic-based subscriptions for better scalability and selective updates.
"""

import asyncio
import logging
from collections import defaultdict
from typing import Dict, Set, Any, Optional

from fastapi import WebSocket

from backend.config import settings
from backend.core.redis_pubsub import RedisPublisher, RedisSubscriber

logger = logging.getLogger(__name__)


class TopicWebSocketManager:
    """Manages WebSocket connections with topic-based subscriptions.

    Clients can subscribe to multiple topics and receive only messages
    broadcast to those topics. Automatic cleanup on disconnect.

    Supports Redis pub/sub for multi-instance deployments with graceful
    fallback to in-memory when Redis unavailable.
    """

    def __init__(self):
        self.subscriptions: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

        self.redis_publisher: Optional[RedisPublisher] = None
        self.redis_subscriber: Optional[RedisSubscriber] = None
        self.redis_enabled = False

    async def initialize_redis(self):
        """Initialize Redis pub/sub if enabled in config."""
        if not settings.REDIS_ENABLED:
            logger.info("Redis pub/sub disabled (REDIS_ENABLED=False)")
            return

        try:
            self.redis_publisher = RedisPublisher(settings.REDIS_URL)
            connected = await self.redis_publisher.connect()

            if connected:
                self.redis_subscriber = RedisSubscriber(settings.REDIS_URL)
                if await self.redis_subscriber.connect():
                    await self._subscribe_all_topics()
                    self.redis_subscriber.start_listening()
                    self.redis_enabled = True
                    logger.info("Redis pub/sub initialized successfully")
                else:
                    await self.redis_publisher.close()
                    self.redis_publisher = None
                    logger.warning("Redis subscriber failed, falling back to in-memory")
            else:
                logger.warning("Redis publisher failed, falling back to in-memory")
        except Exception as e:
            logger.warning(f"Redis initialization failed: {e}. Using in-memory fallback")
            self.redis_enabled = False

    async def _subscribe_all_topics(self):
        """Subscribe Redis listener to all active topics."""
        if not self.redis_subscriber:
            return

        async with self._lock:
            for topic in self.subscriptions.keys():
                await self.redis_subscriber.subscribe(topic, self._handle_redis_message)

    async def _handle_redis_message(self, topic: str, message: Dict[str, Any]):
        """Handle incoming Redis pub/sub message by broadcasting to local subscribers."""
        logger.debug(f"Received Redis message on topic '{topic}'")
        await self._broadcast_local(topic, message)

    async def shutdown_redis(self):
        """Shutdown Redis connections gracefully."""
        if self.redis_subscriber:
            await self.redis_subscriber.close()
            self.redis_subscriber = None

        if self.redis_publisher:
            await self.redis_publisher.close()
            self.redis_publisher = None

        self.redis_enabled = False
        logger.info("Redis pub/sub shutdown complete")

    async def subscribe(self, websocket: WebSocket, topic: str):
        """Subscribe a WebSocket client to a topic.

        Args:
            websocket: The WebSocket connection
            topic: Topic name to subscribe to
        """
        async with self._lock:
            is_new_topic = topic not in self.subscriptions or not self.subscriptions[topic]
            self.subscriptions[topic].add(websocket)

        if is_new_topic and self.redis_subscriber:
            await self.redis_subscriber.subscribe(topic, self._handle_redis_message)

        logger.debug(
            f"Client subscribed to '{topic}'. "
            f"Topic subscribers: {len(self.subscriptions[topic])}"
        )

    async def unsubscribe(self, websocket: WebSocket, topic: str):
        """Unsubscribe a WebSocket client from a topic.

        Args:
            websocket: The WebSocket connection
            topic: Topic name to unsubscribe from
        """
        async with self._lock:
            self.subscriptions[topic].discard(websocket)
            # Clean up empty topic sets
            if not self.subscriptions[topic]:
                del self.subscriptions[topic]
        logger.debug(f"Client unsubscribed from '{topic}'")

    async def broadcast(self, topic: str, message: Dict[str, Any]):
        """Broadcast a message to all subscribers of a topic.

        Args:
            topic: Topic name to broadcast to
            message: JSON-serializable message to send

        Note:
            - Publishes to Redis if enabled (cross-instance)
            - Falls back to local broadcast if Redis unavailable
            - Automatically removes stale connections on send failure
            - Non-blocking: uses asyncio.create_task for concurrent sends
        """
        if self.redis_enabled and self.redis_publisher:
            published = await self.redis_publisher.publish(topic, message)
            if not published:
                logger.warning(f"Redis publish failed for '{topic}', falling back to local")
                self.redis_enabled = False
                await self._broadcast_local(topic, message)
        else:
            await self._broadcast_local(topic, message)

    async def _broadcast_local(self, topic: str, message: Dict[str, Any]):
        """Broadcast message to local WebSocket subscribers only."""
        if topic not in self.subscriptions or not self.subscriptions[topic]:
            logger.debug(f"No subscribers for topic '{topic}'")
            return

        subscribers = list(self.subscriptions[topic])
        logger.debug(f"Broadcasting to {len(subscribers)} subscribers on '{topic}'")

        tasks = []
        for websocket in subscribers:
            from backend.api.main import app
            if hasattr(app.state, 'task_manager'):
                task = await app.state.task_manager.create_task(
                    self._send_to_client(websocket, topic, message),
                    name=f"ws_send_{topic}"
                )
            else:
                task = asyncio.create_task(
                    self._send_to_client(websocket, topic, message)
                )
            tasks.append(task)

        if tasks:
            await asyncio.wait(tasks, timeout=1.0)

    async def _send_to_client(
        self, websocket: WebSocket, topic: str, message: Dict[str, Any]
    ):
        """Send message to a single client, handling errors gracefully.

        Args:
            websocket: The WebSocket connection
            topic: Topic being broadcast to (for cleanup)
            message: Message to send
        """
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.debug(
                f"WS stale connection removed from '{topic}': {e}"
            )
            # Remove from all topics on send failure
            await self.disconnect(websocket)

    async def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket client from all topic subscriptions.

        Args:
            websocket: The WebSocket connection to disconnect
        """
        async with self._lock:
            topics_to_clean = []
            for topic, subscribers in self.subscriptions.items():
                if websocket in subscribers:
                    subscribers.discard(websocket)
                    topics_to_clean.append(topic)
                    logger.debug(
                        f"Removed client from '{topic}'. "
                        f"Remaining subscribers: {len(subscribers)}"
                    )

            # Clean up empty topic sets
            for topic in topics_to_clean:
                if not self.subscriptions[topic]:
                    del self.subscriptions[topic]

    def get_topic_subscriber_count(self, topic: str) -> int:
        """Get the number of subscribers for a topic.

        Args:
            topic: Topic name

        Returns:
            Number of subscribers, or 0 if topic doesn't exist
        """
        return len(self.subscriptions.get(topic, set()))

    def get_all_topics(self) -> Dict[str, int]:
        """Get all active topics and their subscriber counts.

        Returns:
            Dict mapping topic names to subscriber counts
        """
        return {topic: len(subs) for topic, subs in self.subscriptions.items()}


# Global instance
topic_manager = TopicWebSocketManager()
