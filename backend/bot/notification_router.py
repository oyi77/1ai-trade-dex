"""
Notification router for PolyEdge.

Routes events to configured channels (Telegram, Discord, Email).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import httpx

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.utils.redaction import redact_sensitive

from loguru import logger

webhook_breaker = CircuitBreaker("webhook", failure_threshold=3, recovery_timeout=300.0)


class NotificationChannel(str, Enum):
    TELEGRAM = "telegram"
    DISCORD = "discord"
    EMAIL = "email"


class EventType(str, Enum):
    TRADE_EXECUTED = "trade_executed"
    SIGNAL_GENERATED = "signal_generated"
    DRAWDOWN_ALERT = "drawdown_alert"
    WHALE_DETECTED = "whale_detected"
    SETTLEMENT = "settlement"
    ERROR = "error"


@dataclass
class NotificationConfig:
    channel: NotificationChannel
    enabled: bool = True
    event_types: list[EventType] = field(default_factory=list)  # empty = all events
    webhook_url: Optional[str] = None  # for Discord
    smtp_config: Optional[dict] = None  # for email


class NotificationRouter:
    """Routes events to all matching enabled channels."""

    def __init__(self) -> None:
        self._channels: list[NotificationConfig] = []
        self._load_defaults()

    def _load_defaults(self) -> None:
        """Register channels from settings."""
        if settings.TELEGRAM_BOT_TOKEN:
            self._channels.append(
                NotificationConfig(
                    channel=NotificationChannel.TELEGRAM,
                    enabled=True,
                    event_types=[],  # all events
                )
            )

    def register_channel(self, config: NotificationConfig) -> None:
        """Add or replace a channel configuration."""
        # Replace existing config for the same channel type if present
        self._channels = [c for c in self._channels if c.channel != config.channel]
        self._channels.append(config)

    async def notify(
        self,
        event_type: EventType,
        message: str,
        details: dict = None,
    ) -> None:
        """Route notification to all matching enabled channels."""
        details = details or {}
        for config in self._channels:
            if not config.enabled:
                continue
            # empty event_types means all events
            if config.event_types and event_type not in config.event_types:
                continue
            try:
                if config.channel == NotificationChannel.TELEGRAM:
                    await self._send_telegram(message)
                elif config.channel == NotificationChannel.DISCORD:
                    if config.webhook_url:
                        await self._send_discord(config.webhook_url, message)
                    else:
                        logger.warning("Discord channel configured without webhook_url")
                elif config.channel == NotificationChannel.EMAIL:
                    await self._send_email(config.smtp_config or {}, message)
            except Exception as exc:
                logger.error(
                    "Failed to send notification via %s: %s",
                    config.channel,
                    exc,
                )

    async def _send_telegram(self, message: str) -> None:
        """Send message via existing Telegram bot."""
        from backend.bot.notifier import get_bot

        bot = get_bot()
        if bot is None:
            logger.debug("Telegram bot not initialised; skipping notification")
            return
        try:
            await bot.send_error_alert(message, context="notification_router")
        except Exception as exc:
            logger.error("Telegram send failed: %s", exc)

    async def _send_discord(self, webhook_url: str, message: str) -> None:
        """POST message to a Discord webhook URL."""
        async def _post_discord() -> None:
            payload = {"content": message}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(webhook_url, json=payload)
                resp.raise_for_status()

        try:
            await webhook_breaker.call(_post_discord)
        except CircuitOpenError:
            logger.warning("Discord webhook circuit open, skipping notification")
        except Exception as exc:
                logger.error("Discord webhook failed: %s", redact_sensitive(str(exc)))

    async def _send_email(self, config: dict, message: str) -> None:
        """Email notifications are intentionally de-scoped.

        Telegram and Discord channels are the supported notification methods.
        See IMPLEMENTATION_GAPS.md.
        """
        logger.warning(
            "Email notification channel is de-scoped; dropping message (to=%s subject=%s)",
            config.get("to"),
            config.get("subject", "PolyEdge Alert"),
        )
        return
