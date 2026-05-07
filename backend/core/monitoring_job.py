"""Background monitoring job for system health checks."""

import logging

from backend.core.alert_manager import AlertManager, get_system_metrics
from backend.core.circuit_breaker_pybreaker import (
    db_breaker,
    polymarket_breaker,
    kalshi_breaker,
    redis_breaker
)

logger = logging.getLogger("monitoring_job")


async def run_monitoring_check():
    """
    Run periodic system monitoring checks and trigger alerts.

    Checks:
    - Circuit breaker states
    - Error rate
    - Memory usage
    - Disk space
    - Database connection pool
    """
    from backend.db.utils import get_db_session
    try:
        with get_db_session() as db:
            manager = AlertManager(db)

            metrics = get_system_metrics()

            manager.check_memory_usage(metrics["memory_percent"])
            manager.check_disk_space(metrics["disk_percent_free"])
            manager.check_connection_pool(
                metrics["pool_size"],
                metrics["active_connections"]
            )

            manager.check_circuit_breaker("database", db_breaker.current_state)
            manager.check_circuit_breaker("polymarket_api", polymarket_breaker.current_state)
            manager.check_circuit_breaker("kalshi_api", kalshi_breaker.current_state)
            manager.check_circuit_breaker("redis", redis_breaker.current_state)

            manager.check_error_rate()

            logger.debug(
                f"Monitoring check complete: "
                f"memory={metrics['memory_percent']:.1f}%, "
                f"disk_free={metrics['disk_percent_free']:.1f}%, "
                f"connections={metrics['active_connections']}/{metrics['pool_size']}"
            )

    except Exception as e:
        logger.error(f"Monitoring check failed: {e}")
        if db:
            manager = AlertManager(db)
            manager.record_error()
