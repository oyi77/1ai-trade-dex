"""
AlertManager — Multi-channel alert system for the monitor daemon.

Channels:
- Telegram (primary, via backend.bot.telegram_bot)
- Console (logger)
- File (JSON log)

Alert deduplication: Same alert type not sent more than once per N minutes.
"""

import json
import threading
import time
from datetime import datetime, timezone

from loguru import logger
from pathlib import Path
from typing import Optional, Dict, List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALERT_LOG_DIR = Path("logs/alerts")
ALERT_LOG_FILE = ALERT_LOG_DIR / "monitor_alerts.jsonl"
ALERT_DEDUP_WINDOW = 300  # 5 minutes
MAX_ALERTS_PER_CYCLE = 10  # Don't spam

# ---------------------------------------------------------------------------
# Alert Manager
# ---------------------------------------------------------------------------


class AlertManager:
    """
    Sends alerts through configured channels with deduplication.

    Usage:
        alerts = AlertManager()
        await alerts.send_alert(title="🚨 Alert", body="Something happened", level="warning")
    """

    def __init__(self):
        self._recent_alerts: Dict[str, float] = {}  # alert_key -> timestamp
        self._lock = threading.Lock()
        self._cycle_count = 0

        # Ensure log directory exists
        ALERT_LOG_DIR.mkdir(parents=True, exist_ok=True)

    async def send_alert(
        self,
        title: str,
        body: str,
        level: str = "info",
        dedup_key: Optional[str] = None,
    ) -> bool:
        """
        Send an alert through all configured channels.

        Args:
            title: Alert title (short)
            body: Alert body (detailed)
            level: info | warning | critical
            dedup_key: Custom deduplication key (auto-generated from title if None)

        Returns:
            True if alert was sent, False if deduplicated
        """
        # Deduplication
        key = dedup_key or title[:80]
        with self._lock:
            now = time.time()
            last_sent = self._recent_alerts.get(key, 0.0)
            if (now - last_sent) < ALERT_DEDUP_WINDOW:
                logger.debug(f"[AlertManager] Deduped: {title}")
                return False
            self._recent_alerts[key] = now

        # Build alert envelope
        alert = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "title": title,
            "body": body,
            "level": level,
        }

        # ── Console ──
        log_func = {
            "info": logger.info,
            "warning": logger.warning,
            "critical": logger.error,
        }.get(level, logger.info)
        log_func(f"[ALERT][{level.upper()}] {title}\n{body}")

        # ── File (JSONL) ──
        try:
            with open(ALERT_LOG_FILE, "a") as f:
                f.write(json.dumps(alert) + "\n")
        except Exception as exc:
            logger.debug(f"[AlertManager] File log error: {exc}")

        # ── Telegram ──
        try:
            await self._send_telegram(title, body, level)
        except Exception as exc:
            logger.debug(f"[AlertManager] Telegram error: {exc}")

        return True

    def get_recent_alerts(
        self, minutes: int = 60, level: Optional[str] = None
    ) -> List[dict]:
        """Get recent alerts from the log file."""
        alerts: List[dict] = []
        cutoff = time.time() - (minutes * 60)

        try:
            if ALERT_LOG_FILE.exists():
                with open(ALERT_LOG_FILE) as f:
                    for line in f:
                        try:
                            alert = json.loads(line.strip())
                            ts = datetime.fromisoformat(
                                alert["timestamp"]
                            ).timestamp()
                            if ts >= cutoff:
                                if level is None or alert.get("level") == level:
                                    alerts.append(alert)
                        except (json.JSONDecodeError, KeyError, ValueError):
                            continue
        except Exception:
            logger.exception("Failed to read alerts from log file")

        return alerts[-50:]  # Return last 50 max

    # -----------------------------------------------------------------------
    # Telegram
    # -----------------------------------------------------------------------

    async def _send_telegram(self, title: str, body: str, level: str) -> None:
        """Send alert to Telegram via the bot module (best-effort)."""
        try:
            from backend.bot.telegram_bot import send_alert

            # Truncate body for Telegram (max 4096 chars)
            truncated_body = body[:4000] if len(body) > 4000 else body

            await send_alert(
                title=title,
                message=truncated_body,
                level=level,
            )
        except ImportError:
            logger.debug(
                "[AlertManager] telegram_bot not available (not a blocker)"
            )
        except Exception as exc:
            logger.debug(f"[AlertManager] Telegram send failed: {exc}")

    # -----------------------------------------------------------------------
    # Alert Generation Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def format_pnl_change(
        prev_value: float, curr_value: float, label: str = "PnL"
    ) -> str:
        """Format a PnL change for alert messages."""
        change = curr_value - prev_value
        direction = "📈" if change >= 0 else "📉"
        return (
            f"{direction} {label}: ${prev_value:.2f} → ${curr_value:.2f} "
            f"({change:+.2f})"
        )

    @staticmethod
    def format_strategy_summary(
        name: str, pnl: float, wr: float, trades: int, status: str
    ) -> str:
        """Format a single strategy's summary line."""
        emoji = {
            "healthy": "🟢",
            "warning": "🟡",
            "critical": "🔴",
            "disabled": "⚪",
            "inactive": "⚫",
        }.get(status, "❓")
        return f"{emoji} {name}: {trades}t | ${pnl:+.2f} | WR {wr:.1%}"
