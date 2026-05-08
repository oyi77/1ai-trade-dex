"""SourceHealthMonitor — per-source circuit breaker and health tracking."""
from __future__ import annotations
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict

from backend.mesh.base import SourceState, HealthStatus
from backend.mesh.registry import list_active, quarantine, release

logger = logging.getLogger("trading_bot.mesh.health")

SUCCESS_RATE_WINDOW = 20
DEGRADED_SUCCESS_THRESHOLD = 0.90
FAILED_SUCCESS_THRESHOLD = 0.50
CONSECUTIVE_FAILURE_THRESHOLD = 5
RECOVERY_PROBE_INTERVAL = 60
RECOVERY_SUCCESSES_NEEDED = 3


class SourceHealthMonitor:
    def __init__(self):
        self._windows: Dict[str, list] = defaultdict(list)
        self._states: Dict[str, SourceState] = {}
        self._consecutive_failures: Dict[str, int] = defaultdict(int)
        self._recovery_counts: Dict[str, int] = defaultdict(int)
        self._last_probe: Dict[str, float] = {}
        self._latencies: Dict[str, list] = defaultdict(list)

    def record(self, source_id: str, success: bool, latency_ms: float = 0.0):
        window = self._windows[source_id]
        window.append(success)
        if len(window) > SUCCESS_RATE_WINDOW:
            window.pop(0)
        if success:
            self._consecutive_failures[source_id] = 0
        else:
            self._consecutive_failures[source_id] += 1
        self._latencies[source_id].append(latency_ms)
        if len(self._latencies[source_id]) > 100:
            self._latencies[source_id] = self._latencies[source_id][-100:]
        self._evaluate(source_id)

    def _evaluate(self, source_id: str):
        window = self._windows.get(source_id, [])
        if not window:
            return
        rate = sum(window) / len(window)
        consecutive = self._consecutive_failures.get(source_id, 0)
        current = self._states.get(source_id, SourceState.HEALTHY)

        new_state = current
        if consecutive >= CONSECUTIVE_FAILURE_THRESHOLD or rate < FAILED_SUCCESS_THRESHOLD:
            new_state = SourceState.FAILED
        elif rate < DEGRADED_SUCCESS_THRESHOLD:
            new_state = SourceState.DEGRADED
        elif current in (SourceState.FAILED, SourceState.DEGRADED):
            self._recovery_counts[source_id] = self._recovery_counts.get(source_id, 0) + 1
            if self._recovery_counts[source_id] >= RECOVERY_SUCCESSES_NEEDED:
                new_state = SourceState.HEALTHY
                self._recovery_counts[source_id] = 0
                release(source_id)
        else:
            new_state = SourceState.HEALTHY

        if new_state != current:
            self._states[source_id] = new_state
            if new_state == SourceState.FAILED:
                quarantine(source_id, f"auto-circuit: rate={rate:.1%}, consec={consecutive}")
                logger.warning(f"Source '{source_id}' → FAILED (rate={rate:.1%}, consec={consecutive})")
            elif new_state == SourceState.DEGRADED:
                logger.info(f"Source '{source_id}' → DEGRADED (rate={rate:.1%})")
            elif new_state == SourceState.HEALTHY:
                logger.info(f"Source '{source_id}' → HEALTHY (recovered)")

    def get_health(self, source_id: str) -> HealthStatus:
        window = self._windows.get(source_id, [])
        rate = sum(window) / len(window) if window else 1.0
        lats = self._latencies.get(source_id, [0])
        p95 = sorted(lats)[int(len(lats) * 0.95)] if len(lats) >= 20 else max(lats) if lats else 0
        return HealthStatus(
            source_id=source_id,
            state=self._states.get(source_id, SourceState.HEALTHY),
            success_rate=rate,
            p95_latency_ms=p95,
            consecutive_failures=self._consecutive_failures.get(source_id, 0),
            last_check=datetime.now(timezone.utc),
        )

    def get_all_health(self) -> Dict[str, HealthStatus]:
        return {sid: self.get_health(sid) for sid in list_active()}

    def source_weight(self, source_id: str) -> float:
        state = self._states.get(source_id, SourceState.HEALTHY)
        if state == SourceState.HEALTHY:
            return 1.0
        if state == SourceState.DEGRADED:
            return 0.5
        return 0.0

    def global_risk_multiplier(self) -> float:
        sources = list_active()
        if not sources:
            return 1.0
        failed = sum(1 for s in sources if self._states.get(s) == SourceState.FAILED)
        degraded = sum(1 for s in sources if self._states.get(s) == SourceState.DEGRADED)
        unhealthy_ratio = (failed + degraded * 0.5) / len(sources)
        if unhealthy_ratio >= 0.5:
            return 0.0
        if unhealthy_ratio >= 0.3:
            return 0.5
        return 1.0
