"""Queue latency and throughput metrics for the job queue.

Tracks per-job-type latency percentiles (p50, p95, p99), queue depth, timeout rate,
and error rate. Metrics are computed over a rolling window in memory and exposed via
get_metrics_snapshot() for monitoring/logging.
"""
import time
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, Deque, Optional
from threading import Lock

logger = logging.getLogger("trading_bot.queue_metrics")

WINDOW_SIZE = 1000  # rolling window of recent samples per job type


@dataclass
class JobTypeMetrics:
    latencies_ms: Deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW_SIZE))
    total: int = 0
    timeouts: int = 0
    errors: int = 0
    successes: int = 0


class QueueMetrics:
    """Thread-safe queue metrics aggregator."""

    def __init__(self):
        self._lock = Lock()
        self._by_type: Dict[str, JobTypeMetrics] = defaultdict(JobTypeMetrics)
        self._depth: int = 0

    def record_job_completion(self, job_type: str, latency_ms: float, status: str) -> None:
        """Record a finished job. status in {success, timeout, error}."""
        with self._lock:
            m = self._by_type[job_type]
            m.latencies_ms.append(latency_ms)
            m.total += 1
            if status == "success":
                m.successes += 1
            elif status == "timeout":
                m.timeouts += 1
            elif status == "error":
                m.errors += 1

    def update_depth(self, depth: int) -> None:
        with self._lock:
            self._depth = depth

    def percentiles(self, job_type: str) -> Dict[str, float]:
        with self._lock:
            samples = list(self._by_type[job_type].latencies_ms)
        if not samples:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
        samples_sorted = sorted(samples)
        def pct(p):
            k = max(0, min(len(samples_sorted) - 1, int(round((p / 100) * (len(samples_sorted) - 1)))))
            return samples_sorted[k]
        return {"p50": pct(50), "p95": pct(95), "p99": pct(99)}

    def _percentiles_unlocked(self, samples: list) -> Dict[str, float]:
        """Compute percentiles from an already-copied sample list (no lock needed)."""
        if not samples:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
        samples_sorted = sorted(samples)
        def pct(p):
            k = max(0, min(len(samples_sorted) - 1, int(round((p / 100) * (len(samples_sorted) - 1)))))
            return samples_sorted[k]
        return {"p50": pct(50), "p95": pct(95), "p99": pct(99)}

    def get_metrics_snapshot(self) -> Dict:
        with self._lock:
            snapshot = {
                "depth": self._depth,
                "by_type": {},
            }
            for jt, m in self._by_type.items():
                samples = list(m.latencies_ms)
                pcts = self._percentiles_unlocked(samples)
                timeout_rate = (m.timeouts / m.total) if m.total > 0 else 0.0
                error_rate = (m.errors / m.total) if m.total > 0 else 0.0
                snapshot["by_type"][jt] = {
                    "total": m.total,
                    "successes": m.successes,
                    "timeouts": m.timeouts,
                    "errors": m.errors,
                    "timeout_rate": round(timeout_rate, 4),
                    "error_rate": round(error_rate, 4),
                    **pcts,
                }
        return snapshot

    def log_snapshot(self) -> None:
        snap = self.get_metrics_snapshot()
        logger.info(f"queue_metrics depth={snap['depth']} types={snap['by_type']}")


_global_metrics: Optional[QueueMetrics] = None


def get_queue_metrics() -> QueueMetrics:
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = QueueMetrics()
    return _global_metrics


class JobTimer:
    """Context manager that records latency on exit."""
    def __init__(self, job_type: str):
        self.job_type = job_type
        self.start = 0.0
        self.status = "error"  # default if not explicitly set

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        latency_ms = (time.perf_counter() - self.start) * 1000
        get_queue_metrics().record_job_completion(self.job_type, latency_ms, self.status)
        return False
