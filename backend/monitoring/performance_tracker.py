"""Performance tracking with percentile calculations and database storage.

Observability writes are best-effort — they must never block the event loop or
stall API responses.  SQLite WAL mode (30 s busy_timeout) handles contention
internally, so we retry once with a short backoff and then drop the metric if
the write still fails.
"""

import time
import psutil
import logging
from collections import deque
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, PendingRollbackError
from backend.models.database import PerformanceMetric

logger = logging.getLogger("trading_bot")

_MAX_DB_RETRIES = 2
_RETRY_DELAY_S = 0.1


class PercentileTracker:
    """Track metrics with rolling window for percentile calculations."""
    
    def __init__(self, window_size: int = 1000):
        self.window_size = window_size
        self.values = deque(maxlen=window_size)
    
    def add(self, value: float):
        """Add a value to the tracker."""
        self.values.append(value)
    
    def get_percentiles(self) -> Dict[str, float]:
        """Calculate p50, p95, p99 percentiles."""
        if not self.values:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "count": 0}
        
        sorted_values = sorted(self.values)
        count = len(sorted_values)
        
        def percentile(p: float) -> float:
            idx = int(count * p)
            if idx >= count:
                idx = count - 1
            return sorted_values[idx]
        
        return {
            "p50": percentile(0.50),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
            "count": count,
            "min": min(sorted_values),
            "max": max(sorted_values),
            "avg": sum(sorted_values) / count
        }


def _best_effort_write(db: Session, metric: PerformanceMetric) -> None:
    """Write a PerformanceMetric row with one retry on SQLite lock contention.

    Uses the engine-level WAL busy_timeout (30 s) for the first attempt.
    Falls back to a single short retry, then silently drops the metric.
    """
    for attempt in range(_MAX_DB_RETRIES):
        try:
            db.add(metric)
            db.commit()
            return
        except (OperationalError, PendingRollbackError) as e:
            if "database is locked" in str(e).lower() and attempt < _MAX_DB_RETRIES - 1:
                db.rollback()
                time.sleep(_RETRY_DELAY_S)
                continue
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise
    logger.debug("PerformanceMetric write dropped after %d attempts", _MAX_DB_RETRIES)


class PerformanceTracker:
    """Central performance tracking with database persistence."""
    
    def __init__(self):
        self.request_tracker = PercentileTracker(window_size=1000)
        self.db_query_tracker = PercentileTracker(window_size=1000)
        self.ws_tracker = PercentileTracker(window_size=1000)
        self.process = psutil.Process()
        self._last_cleanup = time.time()
        self._cleanup_interval = 3600  # 1 hour
    
    def track_request(
        self,
        duration_ms: float,
        endpoint: str,
        method: str,
        status_code: int,
        db: Optional[Session] = None,
        user_agent: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        """Track HTTP request performance."""
        self.request_tracker.add(duration_ms)

        if db:
            try:
                _best_effort_write(db, PerformanceMetric(
                    metric_type="request",
                    endpoint=endpoint,
                    method=method,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    user_agent=user_agent,
                    error_message=error_message
                ))
            except Exception as e:
                logger.debug("Failed to store request metric: %s", e)
    
    def track_db_query(
        self,
        duration_ms: float,
        query_type: str,
        db: Optional[Session] = None
    ):
        """Track database query performance."""
        self.db_query_tracker.add(duration_ms)

        if db:
            try:
                _best_effort_write(db, PerformanceMetric(
                    metric_type="db_query",
                    query_type=query_type,
                    query_duration_ms=duration_ms
                ))
            except Exception as e:
                logger.debug("Failed to store DB query metric: %s", e)
    
    def track_websocket(
        self,
        latency_ms: float,
        message_type: str,
        db: Optional[Session] = None
    ):
        """Track WebSocket message latency."""
        self.ws_tracker.add(latency_ms)

        if db:
            try:
                _best_effort_write(db, PerformanceMetric(
                    metric_type="websocket",
                    ws_message_type=message_type,
                    ws_latency_ms=latency_ms
                ))
            except Exception as e:
                logger.debug("Failed to store WebSocket metric: %s", e)
    
    def track_system_resources(self, db: Optional[Session] = None):
        """Track memory and CPU usage."""
        try:
            memory_info = self.process.memory_info()
            memory_mb = memory_info.rss / (1024 * 1024)
            memory_percent = self.process.memory_percent()
            cpu_percent = self.process.cpu_percent(interval=0.1)

            if db:
                try:
                    _best_effort_write(db, PerformanceMetric(
                        metric_type="system",
                        memory_usage_mb=memory_mb,
                        memory_percent=memory_percent,
                        cpu_percent=cpu_percent
                    ))
                except Exception as e:
                    logger.debug("Failed to store system metric: %s", e)

            return {
                "memory_mb": memory_mb,
                "memory_percent": memory_percent,
                "cpu_percent": cpu_percent
            }
        except Exception as e:
            logger.debug("Failed to track system resources: %s", e)
            return None
    
    def get_metrics_summary(self) -> Dict:
        """Get current metrics summary with percentiles."""
        request_stats = self.request_tracker.get_percentiles()
        db_stats = self.db_query_tracker.get_percentiles()
        ws_stats = self.ws_tracker.get_percentiles()
        system_stats = self.track_system_resources()
        
        return {
            "request_duration": {
                "p50_ms": round(request_stats["p50"], 2),
                "p95_ms": round(request_stats["p95"], 2),
                "p99_ms": round(request_stats["p99"], 2),
                "avg_ms": round(request_stats["avg"], 2) if request_stats["count"] > 0 else 0,
                "count": request_stats["count"]
            },
            "db_query_time": {
                "p50_ms": round(db_stats["p50"], 2),
                "p95_ms": round(db_stats["p95"], 2),
                "p99_ms": round(db_stats["p99"], 2),
                "avg_ms": round(db_stats["avg"], 2) if db_stats["count"] > 0 else 0,
                "count": db_stats["count"]
            },
            "websocket_latency": {
                "p50_ms": round(ws_stats["p50"], 2),
                "p95_ms": round(ws_stats["p95"], 2),
                "p99_ms": round(ws_stats["p99"], 2),
                "avg_ms": round(ws_stats["avg"], 2) if ws_stats["count"] > 0 else 0,
                "count": ws_stats["count"]
            },
            "system": system_stats or {
                "memory_mb": 0,
                "memory_percent": 0,
                "cpu_percent": 0
            }
        }
    
    def cleanup_old_metrics(self, db: Session, days: int = 30):
        """Remove metrics older than specified days."""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            deleted = db.query(PerformanceMetric).filter(
                PerformanceMetric.timestamp < cutoff
            ).delete()
            db.commit()
            logger.info(f"Cleaned up {deleted} old performance metrics (older than {days} days)")
            return deleted
        except Exception as e:
            logger.debug("Failed to cleanup old metrics: %s", e)
            db.rollback()
            return 0
    
    def maybe_cleanup(self, db: Session):
        """Periodically cleanup old metrics."""
        now = time.time()
        if now - self._last_cleanup > self._cleanup_interval:
            self.cleanup_old_metrics(db)
            self._last_cleanup = now


# Global tracker instance
_performance_tracker: Optional[PerformanceTracker] = None


def get_performance_tracker() -> PerformanceTracker:
    """Get or create the global performance tracker."""
    global _performance_tracker
    if _performance_tracker is None:
        _performance_tracker = PerformanceTracker()
    return _performance_tracker