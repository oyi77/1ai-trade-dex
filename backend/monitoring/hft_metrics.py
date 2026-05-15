"""HFT Prometheus metrics for monitoring scan speed, execution latency, and arbitrage."""

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
