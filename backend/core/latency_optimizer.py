"""HFT Latency Optimizer — enforces latency budgets and manages cache invalidation."""

import time
from typing import Optional, Any
from dataclasses import dataclass

from loguru import logger
@dataclass
class LatencyBudget:
    scan_ms: float
    signal_gen_ms: float
    risk_check_ms: float
    execution_ms: float
    total_ms: float
    hard_limit_ms: float


class LatencyOptimizer:
    """
    HFT latency optimizer with budget enforcement.

    Zero Gaps:
    - Latency budget: enforce hard limit per stage
    - Cache invalidation: TTL-based with staleness detection
    """

    def __init__(self):
        self.budget = LatencyBudget(
            scan_ms=1000.0,
            signal_gen_ms=50.0,
            risk_check_ms=5.0,
            execution_ms=50.0,
            total_ms=1100.0,
            hard_limit_ms=5000.0,
        )
        self._cache: dict[str, tuple[Any, float]] = {}
        self._cache_ttl = 1.0

    def check_budget(self, stage: str, elapsed_ms: float) -> tuple[bool, float]:
        """Check if elapsed time is within budget for stage."""
        limits = {
            "scan": self.budget.scan_ms,
            "signal_gen": self.budget.signal_gen_ms,
            "risk_check": self.budget.risk_check_ms,
            "execution": self.budget.execution_ms,
        }
        limit = limits.get(stage, self.budget.total_ms)
        ok = elapsed_ms <= limit
        headroom = limit - elapsed_ms
        return ok, headroom

    def enforce_hard_limit(self, elapsed_ms: float) -> bool:
        """Hard stop if latency exceeds hard_limit_ms."""
        if elapsed_ms > self.budget.hard_limit_ms:
            logger.error(f"[latency_optimizer] HARD LIMIT EXCEEDED: {elapsed_ms:.1f}ms > {self.budget.hard_limit_ms}ms")
            return False
        return True

    def cache_get(self, key: str) -> Optional[Any]:
        """Get cached value if fresh."""
        if key not in self._cache:
            return None
        value, timestamp = self._cache[key]
        if time.time() - timestamp > self._cache_ttl:
            del self._cache[key]
            return None
        return value

    def cache_set(self, key: str, value: Any) -> None:
        """Set cached value."""
        self._cache[key] = (value, time.time())

    def cache_invalidate(self, key: str) -> None:
        """Invalidate a cache entry."""
        self._cache.pop(key, None)

    def cache_invalidate_prefix(self, prefix: str) -> int:
        """Invalidate all keys with given prefix."""
        to_delete = [k for k in self._cache if k.startswith(prefix)]
        for k in to_delete:
            del self._cache[k]
        return len(to_delete)
