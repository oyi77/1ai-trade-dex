"""Redis pub/sub for cross-instance WebSocket communication.

Enables WebSocket messages to be broadcast across multiple backend instances
via Redis pub/sub. Falls back gracefully to in-memory when Redis unavailable.
"""

import asyncio
import json
import logging
from typing import Any, Callable, Dict, Optional

import redis.asyncio as redis
from backend.core.circuit_breaker_pybreaker import redis_breaker

logger = logging.getLogger(__name__)


class RedisPublisher:
    """Publishes WebSocket messages to Redis for cross-instance broadcasting.

    Usage:
        publisher = RedisPublisher(redis_url="redis://localhost:6379")
        await publisher.connect()
        await publisher.publish("signals", {"type": "new_signal", "data": {...}})
        await publisher.close()
    """

    def __init__(self, redis_url: str):
        """Initialize Redis publisher.

        Args:
            redis_url: Redis connection URL (e.g., redis://localhost:6379)
        """
        self.redis_url = redis_url
        self.client: Optional[redis.Redis] = None
        self.connected = False

    async def connect(self) -> bool:
        """Connect to Redis server.

        Returns:
            True if connected successfully, False otherwise
        """
        async def _connect():
            self.client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
            )
            await self.client.ping()
            return True

        try:
            await redis_breaker.call(_connect)
            self.connected = True
            logger.info(f"Redis publisher connected to {self.redis_url}")
            return True
        except Exception as e:
            logger.warning(f"Failed to connect Redis publisher: {e}")
            self.connected = False
            return False

    async def publish(self, topic: str, message: Dict[str, Any]) -> bool:
        """Publish a message to a Redis channel.

        Args:
            topic: Topic/channel name (e.g., "signals", "trades")
            message: JSON-serializable message to publish

        Returns:
            True if published successfully, False otherwise
        """
        if not self.connected or not self.client:
            return False

        async def _publish():
            channel = f"ws:{topic}"
            payload = json.dumps(message)
            await self.client.publish(channel, payload)
            logger.debug(f"Published to Redis channel '{channel}': {len(payload)} bytes")
            return True

        try:
            return await redis_breaker.call(_publish)
        except Exception as e:
            logger.error(f"Failed to publish to Redis channel '{topic}': {e}")
            self.connected = False
            return False

    async def close(self):
        """Close Redis connection."""
        if self.client:
            try:
                await self.client.aclose()
                logger.info("Redis publisher closed")
            except Exception as e:
                logger.warning(f"Error closing Redis publisher: {e}")
            finally:
                self.connected = False
                self.client = None


class RedisSubscriber:
    """Subscribes to Redis channels and forwards messages to callback handlers.

    Usage:
        async def handle_message(topic: str, message: dict):
            print(f"Received on {topic}: {message}")

        subscriber = RedisSubscriber(redis_url="redis://localhost:6379")
        await subscriber.connect()
        await subscriber.subscribe("signals", handle_message)
        await subscriber.listen()  # Blocks until stopped
        await subscriber.close()
    """

    def __init__(self, redis_url: str):
        """Initialize Redis subscriber.

        Args:
            redis_url: Redis connection URL (e.g., redis://localhost:6379)
        """
        self.redis_url = redis_url
        self.client: Optional[redis.Redis] = None
        self.pubsub: Optional[redis.client.PubSub] = None
        self.connected = False
        self.handlers: Dict[str, Callable] = {}
        self._listen_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def connect(self) -> bool:
        """Connect to Redis server.

        Returns:
            True if connected successfully, False otherwise
        """
        async def _connect():
            self.client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
            )
            await self.client.ping()
            self.pubsub = self.client.pubsub()
            return True

        try:
            await redis_breaker.call(_connect)
            self.connected = True
            logger.info(f"Redis subscriber connected to {self.redis_url}")
            return True
        except Exception as e:
            logger.warning(f"Failed to connect Redis subscriber: {e}")
            self.connected = False
            return False

    async def subscribe(self, topic: str, handler: Callable[[str, Dict[str, Any]], None]):
        """Subscribe to a Redis channel with a message handler.

        Args:
            topic: Topic/channel name (e.g., "signals", "trades")
            handler: Async callback function(topic, message)
        """
        if not self.connected or not self.pubsub:
            logger.warning(f"Cannot subscribe to '{topic}': not connected")
            return

        try:
            channel = f"ws:{topic}"
            await self.pubsub.subscribe(channel)
            self.handlers[channel] = handler
            logger.info(f"Subscribed to Redis channel '{channel}'")
        except Exception as e:
            logger.error(f"Failed to subscribe to Redis channel '{topic}': {e}")

    async def unsubscribe(self, topic: str):
        """Unsubscribe from a Redis channel.

        Args:
            topic: Topic/channel name
        """
        if not self.connected or not self.pubsub:
            return

        try:
            channel = f"ws:{topic}"
            await self.pubsub.unsubscribe(channel)
            self.handlers.pop(channel, None)
            logger.info(f"Unsubscribed from Redis channel '{channel}'")
        except Exception as e:
            logger.error(f"Failed to unsubscribe from Redis channel '{topic}': {e}")

    async def listen(self):
        """Start listening for messages (blocking until stopped).

        Call this after subscribing to topics. Runs until stop() is called.
        """
        if not self.connected or not self.pubsub:
            logger.warning("Cannot listen: not connected")
            return

        logger.info("Redis subscriber listening for messages...")
        self._stop_event.clear()

        try:
            while not self._stop_event.is_set():
                try:
                    # Use get_message with timeout to allow periodic stop checks
                    message = await asyncio.wait_for(
                        self.pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=1.0
                    )

                    if message and message["type"] == "message":
                        channel = message["channel"]
                        data = message["data"]

                        # Parse JSON payload
                        try:
                            payload = json.loads(data)
                        except json.JSONDecodeError as e:
                            logger.error(f"Invalid JSON from Redis channel '{channel}': {e}")
                            continue

                        # Call handler
                        handler = self.handlers.get(channel)
                        if handler:
                            # Extract topic from channel (remove "ws:" prefix)
                            topic = channel.replace("ws:", "", 1)
                            try:
                                if asyncio.iscoroutinefunction(handler):
                                    await handler(topic, payload)
                                else:
                                    handler(topic, payload)
                            except Exception as e:
                                logger.error(f"Error in handler for '{channel}': {e}")
                        else:
                            logger.warning(f"No handler for Redis channel '{channel}'")

                except asyncio.TimeoutError:
                    # Normal timeout, continue loop
                    continue
                except Exception as e:
                    logger.error(f"Error receiving Redis message: {e}")
                    await asyncio.sleep(1)  # Back off on error

        except asyncio.CancelledError:
            logger.info("Redis subscriber listen task cancelled")
        finally:
            logger.info("Redis subscriber stopped listening")

    def start_listening(self):
        """Start listening in background task.

        Returns:
            The asyncio Task running the listener
        """
        if self._listen_task and not self._listen_task.done():
            logger.warning("Listener already running")
            return self._listen_task

        self._listen_task = asyncio.create_task(self.listen())
        return self._listen_task

    async def stop(self):
        """Stop listening for messages."""
        self._stop_event.set()
        if self._listen_task and not self._listen_task.done():
            try:
                await asyncio.wait_for(self._listen_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Listener task did not stop gracefully, cancelling")
                self._listen_task.cancel()
                try:
                    await self._listen_task
                except asyncio.CancelledError:
                    pass

    async def close(self):
        """Close Redis connection."""
        await self.stop()

        if self.pubsub:
            try:
                await self.pubsub.aclose()
            except Exception as e:
                logger.warning(f"Error closing Redis pubsub: {e}")
            finally:
                self.pubsub = None

        if self.client:
            try:
                await self.client.aclose()
                logger.info("Redis subscriber closed")
            except Exception as e:
                logger.warning(f"Error closing Redis subscriber: {e}")
            finally:
                self.connected = False
                self.client = None
