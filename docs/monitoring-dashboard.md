# Monitoring Dashboard Setup

**Date**: 2026-05-18
**Grafana Config**: `backend/monitoring/grafana/polyedge-dashboard.json`

## Overview

PolyEdge uses Prometheus for metrics collection and Grafana for visualization. The monitoring stack tracks trade execution, risk management, circuit breakers, and system health.

## Architecture

```
PolyEdge Backend → Prometheus metrics endpoint → Prometheus server → Grafana dashboard
```

## Grafana Dashboard

The pre-configured dashboard (`backend/monitoring/grafana/polyedge-dashboard.json`) includes:

### Panels

| Panel | Type | Metric | Description |
|-------|------|--------|-------------|
| **Live P&L** | Timeseries | `polyedge_bot_state_gauge{field="bankroll"}`, `polyedge_bot_state_gauge{field="total_pnl"}` | Real-time bankroll and total P&L tracking |
| **Circuit Breakers** | Stat | `polyedge_circuit_breaker_state` | Color-coded breaker states: OPEN (red), HALF-OPEN (yellow), CLOSED (green) |
| **Order Latency** | Timeseries | `polyedge_order_latency_seconds_avg` | Average order execution latency in seconds |
| **Strategy Health** | Table | Per-strategy metrics | Win rate, PnL, trade count per strategy |

### Additional Metrics (from `backend/monitoring/metrics.py`)

- `polyedge_trades_executed_total` — Counter: total trades by strategy/mode
- `polyedge_risk_rejections_total` — Counter: risk rejections by reason
- `polyedge_signals_recorded_total` — Counter: signals by strategy
- `polyedge_order_latency_seconds` — Histogram: order execution latency

## Setup Instructions

### 1. Install Prometheus

```bash
# Docker
docker run -d --name prometheus \
  -p 9090:9090 \
  -v ./prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus
```

### 2. Configure Prometheus

Add PolyEdge as a scrape target in `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'polyedge'
    static_configs:
      - targets: ['localhost:8000']  # FastAPI metrics endpoint
    scrape_interval: 15s
```

### 3. Install Grafana

```bash
docker run -d --name grafana \
  -p 3000:3000 \
  grafana/grafana
```

### 4. Import Dashboard

1. Open Grafana at `http://localhost:3000`
2. Go to Dashboards → Import
3. Upload `backend/monitoring/grafana/polyedge-dashboard.json`
4. Configure Prometheus as the data source

### 5. Configure Alerts (Optional)

Add Grafana alerts for critical conditions:

- **Circuit breaker OPEN**: Alert when any breaker state changes to OPEN
- **High latency**: Alert when order latency > 500ms
- **Daily loss limit**: Alert when daily PnL < -$100
- **Strategy auto-kill**: Alert when AGI disables a strategy

## Prometheus Metrics Endpoint

The FastAPI app exposes metrics at `/metrics` (configured in `backend/monitoring/metrics.py`). Verify with:

```bash
curl http://localhost:8000/metrics | grep polyedge_
```

## Key Metrics to Monitor

### Trading Health
- Bankroll trend (should be stable or growing)
- Win rate per strategy (should be > 55%)
- Trade frequency (detect if strategy stops trading)

### System Health
- Order latency (should be < 200ms)
- Circuit breaker states (should be CLOSED)
- API error rates (should be < 1%)

### Risk Management
- Daily PnL vs limits
- Position sizes vs caps
- Drawdown percentage

## Files

| File | Purpose |
|------|---------|
| `backend/monitoring/metrics.py` | Prometheus counter/gauge definitions |
| `backend/monitoring/hft_metrics.py` | HFT-specific latency histograms |
| `backend/monitoring/middleware.py` | FastAPI request latency middleware |
| `backend/monitoring/performance_tracker.py` | Per-strategy performance tracking |
| `backend/monitoring/grafana/polyedge-dashboard.json` | Grafana dashboard config |
