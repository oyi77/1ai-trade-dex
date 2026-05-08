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

    # Trade execution pipeline metrics
    "trade_execution_total": 0,
    "risk_rejection_total": 0,
    "order_latency_ms_total": 0.0,
    "order_latency_count": 0,
    "settlement_by_status": {},
    "circuit_breaker_states": {},
    "strategy_health_metrics": {},
    "bot_state_fields": {},
    "maker_edge_capture_rate": 0.0,
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
    with _metrics_lock:
        _metrics["strategies_active"] = active
        _metrics["strategies_paused"] = paused


def increment_trade_execution(strategy: str = "", result: str = "") -> None:
    _increment_metric("trade_execution_total")


def increment_risk_rejection(strategy: str = "", reason: str = "") -> None:
    _increment_metric("risk_rejection_total")


def observe_order_latency(latency_ms: float) -> None:
    with _metrics_lock:
        total = _metrics["order_latency_ms_total"] + latency_ms
        count = _metrics["order_latency_count"] + 1
        _metrics["order_latency_ms_total"] = total
        _metrics["order_latency_count"] = count


def increment_settlement_by_status(status: str) -> None:
    with _metrics_lock:
        by_status = _metrics.get("settlement_by_status", {})
        by_status[status] = by_status.get(status, 0) + 1
        _metrics["settlement_by_status"] = by_status


def set_circuit_breaker_state(breaker_name: str, state: int) -> None:
    with _metrics_lock:
        states = _metrics.get("circuit_breaker_states", {})
        states[breaker_name] = state
        _metrics["circuit_breaker_states"] = states


def set_strategy_health(strategy: str, metric_name: str, value: float) -> None:
    with _metrics_lock:
        health = _metrics.get("strategy_health_metrics", {})
        key = f"{strategy}_{metric_name}"
        health[key] = value
        _metrics["strategy_health_metrics"] = health


def set_bot_state(field: str, value: float) -> None:
    with _metrics_lock:
        fields = _metrics.get("bot_state_fields", {})
        fields[field] = value
        _metrics["bot_state_fields"] = fields


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
            "",
            "# HELP polyedge_trade_execution_total Total trade executions",
            "# TYPE polyedge_trade_execution_total counter",
            f"polyedge_trade_execution_total {_metrics['trade_execution_total']}",
            "",
            "# HELP polyedge_risk_rejection_total Total risk manager rejections",
            "# TYPE polyedge_risk_rejection_total counter",
            f"polyedge_risk_rejection_total {_metrics['risk_rejection_total']}",
            "",
            "# HELP polyedge_order_latency_seconds_avg Average order placement latency in seconds",
            "# TYPE polyedge_order_latency_seconds_avg gauge",
            f"polyedge_order_latency_seconds_avg {_metrics['order_latency_ms_total'] / _metrics['order_latency_count'] / 1000:.6f}" if _metrics['order_latency_count'] > 0 else "polyedge_order_latency_seconds_avg 0",
            "",
            "# HELP polyedge_settlement_by_status_total Settlements by status",
            "# TYPE polyedge_settlement_by_status_total counter",
        ])

        for status, count in _metrics.get("settlement_by_status", {}).items():
            lines.append(f'polyedge_settlement_by_status_total{{status="{status}"}} {count}')

        lines.extend([
            "",
            "# HELP polyedge_circuit_breaker_state Circuit breaker state (0=open 1=half-open 2=closed)",
            "# TYPE polyedge_circuit_breaker_state gauge",
        ])
        for name, state in _metrics.get("circuit_breaker_states", {}).items():
            lines.append(f'polyedge_circuit_breaker_state{{breaker_name="{name}"}} {state}')

        lines.extend([
            "",
            "# HELP polyedge_strategy_health_gauge Strategy health metric value",
            "# TYPE polyedge_strategy_health_gauge gauge",
        ])
        for key, value in _metrics.get("strategy_health_metrics", {}).items():
            parts = key.split("_", 1)
            strategy = parts[0] if len(parts) > 0 else "unknown"
            metric = parts[1] if len(parts) > 1 else "value"
            lines.append(f'polyedge_strategy_health_gauge{{strategy="{strategy}",metric="{metric}"}} {value:.4f}')

        lines.extend([
            "",
            "# HELP polyedge_bot_state_gauge Bot state field value",
            "# TYPE polyedge_bot_state_gauge gauge",
        ])
        for field, value in _metrics.get("bot_state_fields", {}).items():
            lines.append(f'polyedge_bot_state_gauge{{field="{field}"}} {value:.4f}')

        lines.append("")

        return "\n".join(lines)
