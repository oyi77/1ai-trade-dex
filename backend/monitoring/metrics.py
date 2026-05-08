"""Prometheus-style metrics tracking for PolyEdge trading bot."""

from time import time
from typing import Dict, Any
import threading

# Thread-safe metrics storage
_metrics_lock = threading.Lock()
_metrics: Dict[str, Any] = {
    # Trading metrics
    "trades_total": 0,
    "trades_winning": 0,
    "trades_losing": 0,
    "signals_total": 0,
    "signals_executed": 0,

    # Financial metrics (in cents)
    "pnl_total_cents": 0,
    "bankroll_cents": 1000000,  # Default $10,000

    # System metrics
    "api_requests_total": 0,
    "api_errors_total": 0,
    "api_timeouts_total": 0,
    "db_timeouts_total": 0,
    "external_api_timeouts_total": 0,
    "scans_total": 0,
    "settlements_total": 0,

    # Timing metrics (in milliseconds)
    "avg_api_latency_ms": 0,
    "last_scan_timestamp": 0,

    # Strategy status
    "strategies_active": 0,
    "strategies_paused": 0,
}


def _increment_metric(name: str, value: int = 1) -> None:
    """Thread-safe metric increment."""
    with _metrics_lock:
        _metrics[name] = _metrics.get(name, 0) + value


def _set_metric(name: str, value: Any) -> None:
    """Thread-safe metric set."""
    with _metrics_lock:
        _metrics[name] = value


# Trading metrics
def increment_trades(won: bool = False) -> None:
    """Record a new trade."""
    _increment_metric("trades_total")
    if won:
        _increment_metric("trades_winning")
    else:
        _increment_metric("trades_losing")


def increment_signals(executed: bool = False) -> None:
    """Record a new signal."""
    _increment_metric("signals_total")
    if executed:
        _increment_metric("signals_executed")


def update_pnl(pnl_cents: int) -> None:
    """Update total PNL (in cents)."""
    with _metrics_lock:
        _metrics["pnl_total_cents"] = pnl_cents


def update_bankroll(bankroll_cents: int) -> None:
    """Update current bankroll (in cents)."""
    with _metrics_lock:
        _metrics["bankroll_cents"] = bankroll_cents


# System metrics
def record_api_latency(duration_ms: float) -> None:
    """Record API request latency."""
    _increment_metric("api_requests_total")

    # Update moving average
    with _metrics_lock:
        current_avg = _metrics["avg_api_latency_ms"]
        count = _metrics["api_requests_total"]
        new_avg = ((current_avg * (count - 1)) + duration_ms) / count
        _metrics["avg_api_latency_ms"] = new_avg


def increment_api_errors() -> None:
    """Record an API error."""
    _increment_metric("api_errors_total")


def increment_timeouts(timeout_type: str = "api") -> None:
    """Record a timeout event."""
    if timeout_type == "api":
        _increment_metric("api_timeouts_total")
    elif timeout_type == "database":
        _increment_metric("db_timeouts_total")
    elif timeout_type == "external_api":
        _increment_metric("external_api_timeouts_total")


def increment_scans() -> None:
    """Record a market scan."""
    _increment_metric("scans_total")
    _set_metric("last_scan_timestamp", int(time()))


def increment_settlements() -> None:
    """Record a settlement."""
    _increment_metric("settlements_total")


def update_strategy_status(active: int, paused: int) -> None:
    """Update strategy counts."""
    with _metrics_lock:
        _metrics["strategies_active"] = active
        _metrics["strategies_paused"] = paused


# Export metrics in Prometheus format
def get_metrics() -> str:
    """
    Export all metrics in Prometheus text format.

    Returns:
        Metrics in Prometheus exposition format
    """
    with _metrics_lock:
        lines = []

        # HELP and TYPE for each metric
        lines.extend([
            "# HELP polyedge_trades_total Total number of trades executed",
            "# TYPE polyedge_trades_total counter",
            f"polyedge_trades_total {_metrics['trades_total']}",
            "",
            "# HELP polyedge_trades_winning Total number of winning trades",
            "# TYPE polyedge_trades_winning counter",
            f"polyedge_trades_winning {_metrics['trades_winning']}",
            "",
            "# HELP polyedge_trades_losing Total number of losing trades",
            "# TYPE polyedge_trades_losing counter",
            f"polyedge_trades_losing {_metrics['trades_losing']}",
            "",
            "# HELP polyedge_signals_total Total number of signals generated",
            "# TYPE polyedge_signals_total counter",
            f"polyedge_signals_total {_metrics['signals_total']}",
            "",
            "# HELP polyedge_signals_executed Total number of signals executed as trades",
            "# TYPE polyedge_signals_executed counter",
            f"polyedge_signals_executed {_metrics['signals_executed']}",
            "",
            "# HELP polyedge_pnl_total_cents Total PNL in cents",
            "# TYPE polyedge_pnl_total_cents gauge",
            f"polyedge_pnl_total_cents {_metrics['pnl_total_cents']}",
            "",
            "# HELP polyedge_bankroll_cents Current bankroll in cents",
            "# TYPE polyedge_bankroll_cents gauge",
            f"polyedge_bankroll_cents {_metrics['bankroll_cents']}",
            "",
            "# HELP polyedge_api_requests_total Total API requests",
            "# TYPE polyedge_api_requests_total counter",
            f"polyedge_api_requests_total {_metrics['api_requests_total']}",
            "",
            "# HELP polyedge_api_errors_total Total API errors",
            "# TYPE polyedge_api_errors_total counter",
            f"polyedge_api_errors_total {_metrics['api_errors_total']}",
            "",
            "# HELP polyedge_api_timeouts_total Total API request timeouts",
            "# TYPE polyedge_api_timeouts_total counter",
            f"polyedge_api_timeouts_total {_metrics['api_timeouts_total']}",
            "",
            "# HELP polyedge_db_timeouts_total Total database query timeouts",
            "# TYPE polyedge_db_timeouts_total counter",
            f"polyedge_db_timeouts_total {_metrics['db_timeouts_total']}",
            "",
            "# HELP polyedge_external_api_timeouts_total Total external API call timeouts",
            "# TYPE polyedge_external_api_timeouts_total counter",
            f"polyedge_external_api_timeouts_total {_metrics['external_api_timeouts_total']}",
            "",
            "# HELP polyedge_scans_total Total market scans",
            "# TYPE polyedge_scans_total counter",
            f"polyedge_scans_total {_metrics['scans_total']}",
            "",
            "# HELP polyedge_settlements_total Total trade settlements",
            "# TYPE polyedge_settlements_total counter",
            f"polyedge_settlements_total {_metrics['settlements_total']}",
            "",
            "# HELP polyedge_avg_api_latency_ms Average API latency in milliseconds",
            "# TYPE polyedge_avg_api_latency_ms gauge",
            f"polyedge_avg_api_latency_ms {_metrics['avg_api_latency_ms']:.2f}",
            "",
            "# HELP polyedge_last_scan_timestamp Unix timestamp of last market scan",
            "# TYPE polyedge_last_scan_timestamp gauge",
            f"polyedge_last_scan_timestamp {_metrics['last_scan_timestamp']}",
            "",
            "# HELP polyedge_strategies_active Number of active strategies",
            "# TYPE polyedge_strategies_active gauge",
            f"polyedge_strategies_active {_metrics['strategies_active']}",
            "",
            "# HELP polyedge_strategies_paused Number of paused strategies",
            "# TYPE polyedge_strategies_paused gauge",
            f"polyedge_strategies_paused {_metrics['strategies_paused']}",
        ])

        return "\n".join(lines)
