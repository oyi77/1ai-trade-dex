<!-- Parent: ../../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/monitoring/grafana

## Purpose

Grafana dashboard configurations for monitoring PolyEdge trading bot performance. Provides visualization panels for P&L tracking, circuit breaker status, order latency, strategy health, and system metrics.

## Key Files

| File | Description |
|------|-------------|
| `polyedge-dashboard.json` | Complete Grafana dashboard configuration with timeseries panels for Live P&L, Circuit Breakers, Order Latency, Strategy Health tables, and system metrics |

## For AI Agents

### Working In This Directory
- Dashboard configuration uses standard Grafana JSON format
- Panels display real-time trading metrics with Prometheus-style queries
- Color-coded status indicators for circuit breaker states
- Responsive grid layout with configurable panel sizing

### Testing Requirements
- Validate JSON schema compliance with Grafana specifications
- Test panel queries match available Prometheus metrics
- Verify responsive layout across different screen sizes
- Check color mappings for status indicators (OPEN/HALF-OPEN/CLOSED)

### Common Patterns
- Dashboard queries use Prometheus metric names from `polyedge_` prefix
- Panel titles reflect the specific business metric being displayed
- Grid positions use relative coordinates (h: height, w: width, x: column, y: row)
- Field configurations set appropriate units (currencyUSD, seconds, percentages)

## Dependencies

### Internal
- `backend.monitoring.metrics` - Prometheus-style metrics exported from the trading bot

### External
- `grafana` - Dashboard visualization platform
- `prometheus` - Metrics collection and query engine