"""MiroFish service lifecycle management — powered by built-in debate engine.

Manages the debate engine state machine:
- RUNNING: Active Bull/Bear/Judge debate via Groq/Claude LLMs
- PAUSED: Temporarily suspended (preserves state)
- STOPPED: Fully disabled

State transitions:
- STOPPED → RUNNING (start)
- RUNNING → PAUSED (pause)
- RUNNING → STOPPED (stop)
- PAUSED → RUNNING (resume/start)
- Any → RUNNING (restart)
"""

import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ServiceState(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class MiroFishService:
    """Singleton service managing MiroFish integration lifecycle."""

    def __init__(self):
        self._state = ServiceState.STOPPED
        self._state_changed_at: float = time.time()
        self._started_at: Optional[float] = None
        self._last_signal_fetch: Optional[float] = None
        self._total_signals_fetched: int = 0
        self._error_message: Optional[str] = None

    @property
    def state(self) -> ServiceState:
        return self._state

    def is_active(self) -> bool:
        """Whether the service should be fetching signals."""
        return self._state == ServiceState.RUNNING

    def start(self) -> Dict[str, Any]:
        """Start the MiroFish service."""
        if self._state == ServiceState.RUNNING:
            return self._build_status(message="Already running")

        prev = self._state.value
        self._state = ServiceState.RUNNING
        self._transition(prev)
        self._started_at = time.time()
        self._error_message = None

        try:
            from backend.services.mirofish_monitor import get_monitor
            monitor = get_monitor()
            monitor.reset()
        except Exception as e:
            logger.warning(f"Could not reset monitor on start: {e}")

        logger.info(f"MiroFish service started (was {prev})")
        return self._build_status(message=f"Started (was {prev})")

    def stop(self) -> Dict[str, Any]:
        """Stop the MiroFish service."""
        if self._state == ServiceState.STOPPED:
            return self._build_status(message="Already stopped")

        prev = self._state.value
        self._state = ServiceState.STOPPED
        self._transition(prev)
        self._started_at = None
        self._error_message = None

        logger.info(f"MiroFish service stopped (was {prev})")
        return self._build_status(message=f"Stopped (was {prev})")

    def pause(self) -> Dict[str, Any]:
        """Pause the MiroFish service."""
        if self._state == ServiceState.PAUSED:
            return self._build_status(message="Already paused")

        if self._state == ServiceState.STOPPED:
            return self._build_status(message="Cannot pause — service is stopped. Use start first.")

        prev = self._state.value
        self._state = ServiceState.PAUSED
        self._transition(prev)

        logger.info(f"MiroFish service paused (was {prev})")
        return self._build_status(message=f"Paused (was {prev})")

    def restart(self) -> Dict[str, Any]:
        """Restart the MiroFish service — resets monitor and client."""
        prev = self._state.value
        self._state = ServiceState.RUNNING
        self._transition(prev)
        self._started_at = time.time()
        self._error_message = None
        self._total_signals_fetched = 0
        self._last_signal_fetch = None

        try:
            from backend.services.mirofish_monitor import get_monitor, reset_monitor
            reset_monitor()
        except Exception as e:
            logger.warning(f"Could not reset monitor on restart: {e}")

        logger.info(f"MiroFish service restarted (was {prev}, monitor reset)")
        return self._build_status(message=f"Restarted (was {prev}, circuit breaker reset)")

    def record_signal_fetch(self, count: int = 0):
        """Record a signal fetch event."""
        if count < 0:
            count = 0

        self._last_signal_fetch = time.time()
        self._total_signals_fetched += count
        self._error_message = None

    def record_error(self, error: str):
        """Record an error that doesn't change state."""
        self._error_message = error

    def get_status(self) -> Dict[str, Any]:
        """Get full service status."""
        uptime = None
        if self._started_at and self._state == ServiceState.RUNNING:
            uptime = time.time() - self._started_at

        last_fetch = None
        if self._last_signal_fetch:
            last_fetch = datetime.fromtimestamp(
                self._last_signal_fetch, tz=timezone.utc
            ).isoformat()

        started_at = None
        if self._started_at:
            started_at = datetime.fromtimestamp(
                self._started_at, tz=timezone.utc
            ).isoformat()

        from backend.config import settings as app
        engine_type = "builtin_debate_engine"
        if app.MIROFISH_ENABLED and app.MIROFISH_API_URL:
            engine_type = "external_mirofish_api"

        return {
            "state": self._state.value,
            "started_at": started_at,
            "uptime_seconds": round(uptime, 1) if uptime else None,
            "last_signal_fetch": last_fetch,
            "total_signals_fetched": self._total_signals_fetched,
            "error_message": self._error_message,
            "engine": engine_type,
            "engine_url": app.MIROFISH_API_URL if engine_type == "external_mirofish_api" else None,
        }

    def _transition(self, prev: str):
        """Record state transition."""
        self._state_changed_at = time.time()
        logger.info(
            f"MiroFish service state: {prev} → {self._state.value} "
            f"at {datetime.now(timezone.utc).isoformat()}"
        )

    def _build_status(self, message: str) -> Dict[str, Any]:
        status = self.get_status()
        status["message"] = message
        return status


_service_instance: Optional[MiroFishService] = None


def get_mirofish_service() -> MiroFishService:
    """Get or create the singleton MiroFish service manager."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MiroFishService()
    return _service_instance
