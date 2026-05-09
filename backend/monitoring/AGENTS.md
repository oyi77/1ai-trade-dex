<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/monitoring

## Purpose
Prometheus metrics emission, Grafana dashboard configuration, structured logging, and performance tracking. Provides observability for the trading bot — trade execution metrics, circuit breaker states, order latency, and strategy health.

## Key Files

| File | Description |
|------|-------------|
| `metrics.py` | Core Prometheus counters and gauges — `increment_trade_execution`, `increment_risk_rejection`, `record_latency` |
| `hft_metrics.py` | HFT-specific metrics — signal recording, execution latency histograms |
| `middleware.py` | FastAPI middleware for request latency tracking |
| `performance_tracker.py` | Per-strategy performance metric tracking |
| `queue_metrics.py` | Job queue depth and throughput metrics |
| `structured_logger.py` | JSON structured logging utilities |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `grafana/` | Grafana dashboard JSON configuration (see `grafana/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- **All Prometheus metrics use the `polyedge_` prefix** — e.g. `polyedge_trades_executed_total`, `polyedge_risk_rejections_total`. Maintain this convention for new metrics.
- **Metrics are emitted from `backend/core/`**, not from routers or strategies directly — import metric functions from `monitoring/metrics.py` and call them in core execution paths.
- `structured_logger.py` produces JSON logs — use it for events that need to be queryable (trade decisions, risk rejections, circuit breaker trips).
- Do not add business logic to this directory — it is observability only.

### Testing Requirements
- Test that metric counters increment on the expected code paths
- Verify structured log output format for key events

### Common Patterns
- Record a trade: `from backend.monitoring.metrics import increment_trade_execution; increment_trade_execution(strategy="btc_oracle", mode="paper")`
- Record a rejection: `from backend.monitoring.metrics import increment_risk_rejection; increment_risk_rejection(reason="size_exceeded")`
- Record HFT signal: `from backend.monitoring.hft_metrics import record_signal; record_signal(strategy, latency_ms)`

## Dependencies

### Internal
- `backend.config` — `settings` for metrics configuration

### External
- `prometheus_client` — Prometheus metrics library
- `structlog` or `logging` — structured logging
