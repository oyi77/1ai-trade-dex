"""HFT Prometheus metrics for monitoring scan speed, execution latency, and arbitrage."""

import functools
import time

from prometheus_client import Counter, Histogram, Gauge

from loguru import logger

hft_latency_ms = Histogram(
    'hft_latency_ms', 'HFT execution latency',
    buckets=[5, 10, 25, 50, 100, 250, 500]
)

hft_signals_total = Counter(
    "hft_signals_total", "Total HFT signals generated",
    ["strategy", "signal_type"]
)

hft_execution_latency_seconds = Histogram(
    "hft_execution_latency_seconds", "HFT execution latency",
    ["strategy", "status"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1.0]
)

hft_market_scan_seconds = Histogram(
    "hft_market_scan_seconds", "Market scan duration",
    ["scanner"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
)

hft_circuit_breaker_open = Counter(
    "hft_circuit_breaker_open_total", "Circuit breaker openings",
    ["name", "reason"]
)

hft_arb_opportunities = Counter(
    "hft_arb_opportunities_total", "Arbitrage opportunities detected",
    ["type", "profit_bucket"]
)

hft_whale_activities = Counter(
    "hft_whale_activities_total", "Whale activities detected",
    ["action", "size_bucket"]
)

hft_execution_total = Counter(
    "hft_execution_total", "Total HFT executions",
    ["strategy", "side", "status"]
)

hft_position_pnl = Gauge(
    "hft_position_pnl_dollars", "Current PnL from HFT positions",
    ["strategy"]
)

hft_open_positions = Gauge(
    "hft_open_positions", "Number of open HFT positions",
    ["strategy"]
)

maker_fill_rate = Counter(
    "maker_fill_rate", "Maker-first order fill outcomes",
    ["market_id", "filled"]
)

# --- Track 1.1: Prometheus Metrics Instrumentation ---

signal_latency_seconds = Histogram(
    "polyedge_signal_latency_seconds",
    "Strategy signal generation latency",
    ["strategy_name"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

trade_execution_latency = Histogram(
    "polyedge_trade_execution_latency_seconds",
    "Trade execution latency (signal to order placement)",
    ["strategy", "mode"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

risk_rejection_total = Counter(
    "polyedge_risk_rejection_total",
    "Risk manager rejections by reason",
    ["strategy", "reason"],
)

signals_routed_total = Counter(
    "polyedge_signals_routed_total",
    "Signals routed by auto_trader",
    ["strategy", "outcome"],
)

settlement_outcome_total = Counter(
    "polyedge_settlement_outcome_total",
    "Settlement outcomes",
    ["outcome"],
)

order_placement_latency = Histogram(
    "polyedge_order_placement_latency_seconds",
    "Order placement latency",
    ["strategy", "side"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0],
)

circuit_breaker_state_gauge = Gauge(
    "polyedge_circuit_breaker_state",
    "Circuit breaker state (0=open, 1=half-open, 2=closed)",
    ["breaker_name"],
)

db_query_duration = Histogram(
    "polyedge_db_query_duration_seconds",
    "Database query duration",
    ["query_type"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)


def trace_latency(func):
    """Decorator that records signal generation latency to Prometheus.

    Works on both sync and async methods. Strategy name is read from
    ``self.name`` on the bound instance.
    """
    if func.__code__.co_flags & 0x80:  # CO_COROUTINE
        @functools.wraps(func)
        async def async_wrapper(self, *args, **kwargs):
            start = time.monotonic()
            try:
                return await func(self, *args, **kwargs)
            finally:
                elapsed = time.monotonic() - start
                sname = getattr(self, "name", self.__class__.__name__)
                signal_latency_seconds.labels(strategy_name=sname).observe(elapsed)
        return async_wrapper
    else:
        @functools.wraps(func)
        def sync_wrapper(self, *args, **kwargs):
            start = time.monotonic()
            try:
                return func(self, *args, **kwargs)
            finally:
                elapsed = time.monotonic() - start
                sname = getattr(self, "name", self.__class__.__name__)
                signal_latency_seconds.labels(strategy_name=sname).observe(elapsed)
        return sync_wrapper


def record_signal(strategy: str, signal_type: str):
    hft_signals_total.labels(strategy=strategy, signal_type=signal_type).inc()


def record_execution(strategy: str, side: str, status: str, latency_s: float):
    hft_execution_latency_seconds.labels(strategy=strategy, status=status).observe(latency_s)
    hft_execution_total.labels(strategy=strategy, side=side, status=status).inc()


def record_scan(scanner: str, duration_s: float):
    hft_market_scan_seconds.labels(scanner=scanner).observe(duration_s)


def record_circuit_open(name: str, reason: str = "error"):
    hft_circuit_breaker_open.labels(name=name, reason=reason).inc()


def record_arb(type_: str, profit: float):
    bucket = "high" if profit > 0.05 else "medium" if profit > 0.02 else "low"
    hft_arb_opportunities.labels(type=type_, profit_bucket=bucket).inc()


def record_whale(action: str, size: float):
    bucket = "large" if size > 100000 else "medium" if size > 50000 else "small"
    hft_whale_activities.labels(action=action, size_bucket=bucket).inc()


def record_maker_fill_rate(market_id: str, filled: bool) -> None:
    """Record whether a maker-first order was filled at maker price or escalated to taker."""
    try:
        maker_fill_rate.labels(
            market_id=market_id or "unknown",
            filled="true" if filled else "false",
        ).inc()
    except Exception:
        logger.exception("[HFT Metrics] Failed to record maker_fill_rate")


def get_hft_summary() -> dict:
    try:
        total_signals = int(hft_signals_total._value.get())
    except Exception:
        logger.exception("[HFT Metrics] Failed to read hft_signals_total counter")
        total_signals = 0

    try:
        latency_samples = list(hft_execution_latency_seconds._buckets.values())
        total_count = sum(s.get('count', 0) if isinstance(s, dict) else 0 for s in latency_samples) if latency_samples else 0
        avg_latency_ms = (hft_execution_latency_seconds._sum.get() / max(total_count, 1)) * 1000 if total_count > 0 else 0.0
    except Exception:
        logger.exception("[HFT Metrics] Failed to compute avg_latency_ms")
        avg_latency_ms = 0.0

    try:
        arb_count = int(hft_arb_opportunities._value.get())
    except Exception:
        logger.exception("[HFT Metrics] Failed to read hft_arb_opportunities counter")
        arb_count = 0

    try:
        whale_count = int(hft_whale_activities._value.get())
    except Exception:
        logger.exception("[HFT Metrics] Failed to read hft_whale_activities counter")
        whale_count = 0

    try:
        from backend.models.database import StrategyConfig
        from backend.db.utils import get_db_session
        with get_db_session() as db:
            active = db.query(StrategyConfig).filter(StrategyConfig.enabled).count()
    except Exception:
        logger.exception("[HFT Metrics] Failed to query active strategies count")
        active = 0

    return {
        "signals_per_second": round(total_signals / 60.0, 2) if total_signals > 0 else 0.0,
        "avg_latency_ms": round(avg_latency_ms, 2),
        "executor_latency_ms": round(avg_latency_ms * 0.8, 2) if avg_latency_ms > 0 else 0.0,
        "queue_size": 0,
        "active_strategies": active,
        "arb_opportunities": arb_count,
        "whale_activities": whale_count,
        "orderbook_updates_per_sec": 0.0,
    }
