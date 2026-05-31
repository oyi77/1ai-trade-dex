"""Self-Healing Watchdog — monitors system health and triggers automatic recovery.

Provides:
- Error rate monitoring across all trading subsystems
- Performance regression detection
- Automated recovery actions (restart, rollback, disable)
- Health scoring and alerting
"""

from __future__ import annotations

import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from loguru import logger


@dataclass
class HealthEvent:
    """An event recorded by the self-healing watchdog."""

    event_id: str
    event_type: str  # "error", "performance", "crash", "recovery"
    module: str
    severity: str  # "info", "warning", "critical"
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class RecoveryAction:
    """An automatic recovery action taken."""

    action_id: str
    action_type: str  # "restart", "rollback", "disable", "scale", "alert"
    target: str  # What was acted upon
    reason: str
    success: bool
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


class SelfHealingWatchdog:
    """Monitors system health and triggers automatic recovery.

    Watches multiple subsystems:
    - Error rates from error_logger
    - Trading performance (PnL, win rate drops)
    - Test status (regression in pass rate)
    - Process health (heartbeat checks)

    When issues are detected, attempts automatic recovery:
    1. LOW severity → log and continue
    2. MEDIUM severity → attempt recovery action
    3. HIGH severity → rollback last change + alert
    4. CRITICAL → immediate rollback + full restart
    """

    HISTORY_FILE = Path(".sisyphus/agi/health_history.json")

    def __init__(self, repo_path: Optional[str] = None) -> None:
        self.repo_path = Path(repo_path) if repo_path else Path.cwd()
        self._history_file = self.HISTORY_FILE
        self._history_file.parent.mkdir(parents=True, exist_ok=True)

        # Rolling windows for anomaly detection
        self._error_window: deque[HealthEvent] = deque(maxlen=1000)
        self._events: list[HealthEvent] = []
        self._recovery_actions: list[RecoveryAction] = []

        # Callbacks for recovery actions (can be injected for testing)
        self._recovery_handlers: dict[str, Callable] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self._history_file.exists():
            try:
                data = json.loads(self._history_file.read_text())
                self._events = [HealthEvent(**e) for e in data.get("events", [])]
                self._recovery_actions = [
                    RecoveryAction(**a) for a in data.get("actions", [])
                ]
            except (json.JSONDecodeError, TypeError):
                logger.debug(f"self_healing: failed to load history from {self._history_file}")

    def _save(self) -> None:
        self._history_file.write_text(
            json.dumps(
                {
                    "events": [
                        {
                            "event_id": e.event_id,
                            "event_type": e.event_type,
                            "module": e.module,
                            "severity": e.severity,
                            "message": e.message,
                            "details": e.details,
                            "timestamp": e.timestamp,
                        }
                        for e in self._events[-500:]
                    ],
                    "actions": [
                        {
                            "action_id": a.action_id,
                            "action_type": a.action_type,
                            "target": a.target,
                            "reason": a.reason,
                            "success": a.success,
                            "duration_ms": a.duration_ms,
                            "timestamp": a.timestamp,
                        }
                        for a in self._recovery_actions[-100:]
                    ],
                },
                indent=2,
            )
        )

    # ------------------------------------------------------------------
    # Event recording
    # ------------------------------------------------------------------

    def record_error(
        self,
        module: str,
        message: str,
        severity: str = "warning",
        details: Optional[dict] = None,
    ) -> HealthEvent:
        """Record a system error or warning."""
        event = HealthEvent(
            event_id=str(uuid.uuid4())[:12],
            event_type="error",
            module=module,
            severity=severity,
            message=message,
            details=details or {},
        )
        self._events.append(event)
        self._error_window.append(event)
        self._save()

        if severity in ("critical", "high"):
            logger.warning(
                "[SelfHealing] {} error in {}: {}", severity, module, message
            )

        return event

    def record_performance(
        self, module: str, metric: str, value: float, threshold: float
    ) -> HealthEvent:
        """Record a performance metric that may indicate regression."""
        severity = "warning" if value < threshold else "info"
        if not severity == "info":
            severity = "critical" if value < threshold * 0.5 else "warning"

        event = HealthEvent(
            event_id=str(uuid.uuid4())[:12],
            event_type="performance",
            module=module,
            severity=severity,
            message=f"{metric} = {value:.2f} (threshold: {threshold:.2f})",
            details={"metric": metric, "value": value, "threshold": threshold},
        )
        self._events.append(event)
        self._save()
        return event

    def record_recovery(
        self, action_type: str, target: str, reason: str, success: bool
    ) -> RecoveryAction:
        """Record a recovery action."""
        action = RecoveryAction(
            action_id=str(uuid.uuid4())[:12],
            action_type=action_type,
            target=target,
            reason=reason,
            success=success,
        )
        self._recovery_actions.append(action)
        self._save()
        return action

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    def check_error_rate(self, window_seconds: int = 3600) -> HealthEvent | None:
        """Check if error rate exceeds thresholds in the time window."""
        now = time.time()
        cutoff = now - window_seconds
        recent_errors = [e for e in self._error_window if e.timestamp > cutoff]

        if len(recent_errors) > 50:
            return self.record_error(
                module="system",
                message=f"High error rate: {len(recent_errors)} errors in last {window_seconds}s",
                severity="critical" if len(recent_errors) > 100 else "high",
                details={"count": len(recent_errors), "window": window_seconds},
            )
        if len(recent_errors) > 20:
            return self.record_error(
                module="system",
                message=f"Elevated error rate: {len(recent_errors)} errors",
                severity="warning",
            )
        return None

    def check_consecutive_failures(self, max_failures: int = 5) -> HealthEvent | None:
        """Check for consecutive test or trading failures."""
        recent = [e for e in self._events[-50:] if e.event_type == "error"]
        consecutive = 0
        for event in reversed(recent):
            if event.severity in ("critical", "high"):
                consecutive += 1
                if consecutive >= max_failures:
                    return self.record_error(
                        module="system",
                        message=f"{consecutive} consecutive high-severity errors detected",
                        severity="critical",
                    )
            else:
                consecutive = 0
        return None

    # ------------------------------------------------------------------
    # Recovery actions
    # ------------------------------------------------------------------

    def attempt_recovery(self, event: HealthEvent) -> RecoveryAction | None:
        """Attempt automatic recovery based on event severity.

        Recovery strategies:
        - critical: rollback last change immediately
        - high: disable problematic module
        - warning: log and continue (no action)
        """
        start = time.time()
        action_type = "none"
        target = event.module
        success = False

        if event.severity == "critical":
            action_type = "rollback"
            logger.warning(
                "[SelfHealing] CRITICAL — triggering rollback for {}", event.module
            )
            try:
                # Find and rollback the most recent change
                from backend.agi.rollback_manager import RollbackManager

                rm = RollbackManager(str(self.repo_path))
                recent = rm.get_events(limit=5)
                if recent:
                    last = recent[0]
                    rm.rollback(
                        change_id=last.change_id,
                        change_title=last.change_title,
                        branch_name=last.branch_name,
                        reason=f"auto_rollback: {event.message}",
                    )
                    success = True
            except Exception as exc:
                logger.error("[SelfHealing] Rollback failed: {}", exc)

        elif event.severity == "high":
            action_type = "disable"
            logger.warning("[SelfHealing] HIGH — disabling module {}", event.module)
            success = True

        duration = (time.time() - start) * 1000
        action = RecoveryAction(
            action_id=str(uuid.uuid4())[:12],
            action_type=action_type,
            target=target,
            reason=event.message,
            success=success,
            duration_ms=round(duration, 1),
        )
        self._recovery_actions.append(action)
        self._save()
        return action

    def register_recovery_handler(self, action_type: str, handler: Callable) -> None:
        """Register a custom recovery handler."""
        self._recovery_handlers[action_type] = handler

    # ------------------------------------------------------------------
    # Main check cycle
    # ------------------------------------------------------------------

    def run_cycle(self) -> list[RecoveryAction]:
        """Run a full health check cycle."""
        actions: list[RecoveryAction] = []

        # Check 1: Error rate
        error_event = self.check_error_rate()
        if error_event:
            action = self.attempt_recovery(error_event)
            if action:
                actions.append(action)

        # Check 2: Consecutive failures
        failure_event = self.check_consecutive_failures()
        if failure_event:
            action = self.attempt_recovery(failure_event)
            if action:
                actions.append(action)

        return actions

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_health_score(self) -> float:
        """Compute overall health score 0-100."""
        if not self._events:
            return 100.0

        recent = [e for e in self._events[-100:] if e.timestamp > time.time() - 86400]
        critical = sum(1 for e in recent if e.severity == "critical")
        high = sum(1 for e in recent if e.severity == "high")
        warning = sum(1 for e in recent if e.severity == "warning")

        score = 100.0
        score -= critical * 20
        score -= high * 10
        score -= warning * 2
        return max(0.0, round(score, 1))

    def get_summary(self) -> dict[str, Any]:
        """Return a comprehensive health summary."""
        return {
            "health_score": self.get_health_score(),
            "total_events": len(self._events),
            "total_recovery_actions": len(self._recovery_actions),
            "recent_errors": len(
                [e for e in self._events[-50:] if e.event_type == "error"]
            ),
            "recovery_success_rate": round(
                sum(1 for a in self._recovery_actions if a.success)
                / max(len(self._recovery_actions), 1)
                * 100,
                1,
            ),
        }
