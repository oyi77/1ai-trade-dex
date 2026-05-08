# Circuit Breaker Runbook

## How Breakers Work

PolyEdge uses the circuit breaker pattern for resilience. Each external dependency has its own breaker.

### States

| State | Behavior |
|-------|----------|
| CLOSED (2) | Normal operation. Requests pass through. Failures counted. |
| OPEN (0) | All requests rejected immediately with `CircuitOpenError`. |
| HALF-OPEN (1) | Limited probe requests allowed. Success → CLOSED. Failure → OPEN. |

### Trip Conditions

- **Failure threshold**: N consecutive failures (default: varies per breaker)
- **Recovery timeout**: Seconds before OPEN → HALF-OPEN transition

## Active Breakers

| Breaker Name | Guards | Failure Threshold | Recovery Timeout |
|--------------|--------|-------------------|------------------|
| `polymarket_clob` | CLOB order placement | 5 failures | 60s |
| `polymarket_gamma` | Gamma API market data | 5 failures | 60s |
| `kalshi` | Kalshi REST API | 5 failures | 60s |
| `coinbase` | Coinbase BTC feed | 3 failures | 30s |
| `binance` | Binance BTC klines | 3 failures | 30s |
| `kraken` | Kraken BTC feed | 3 failures | 30s |
| `execution_breaker` | Trade execution pipeline | 5 failures | 120s |

## Monitoring

```bash
# Prometheus metric
polyedge_circuit_breaker_state{breaker_name="polymarket_clob"}

# Values: 0=OPEN, 1=HALF-OPEN, 2=CLOSED
```

## Reset Procedures

### Automatic Recovery

Breakers auto-recover: OPEN → HALF-OPEN after timeout → CLOSED on probe success.

### Manual Reset

```bash
curl -X POST localhost:8000/api/admin/circuit-breaker/<name>/reset \
  -H "Authorization: Bearer $ADMIN_API_KEY"
```

### When to Manual Reset

- After confirming the underlying service is healthy
- After network issues are resolved
- After exchange maintenance windows end

## Escalation Path

1. **Breaker trips** → Check logs for failure reason
2. **Repeated trips** → External service may be down; check status pages
3. **All breakers open** → Network issue; check DNS, firewall, proxy
4. **Breaker stuck OPEN** → Manual reset or restart PM2 process
