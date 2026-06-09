# Real-Time Strategies Deployment Guide

## Overview

This guide covers deploying and operating the real-time event-driven trading strategies:
- **Copy Trader**: Mirrors trades from profitable Polymarket traders
- **Whale Tracker**: Monitors on-chain whale activity via Alchemy WebSocket

## Prerequisites

### Required API Keys
1. **Polymarket API** (for leaderboard + CLOB execution)
   - Endpoint: `https://data-api.polymarket.com/v1/leaderboard`
   - No explicit key required (rate-limited)

2. **Alchemy API** (for whale tracker only)
   - Get key from: https://www.alchemy.com
   - Set `ALCHEMY_API_KEY` environment variable
   - Supports mainnet ETH for pending transaction monitoring

### Environment Setup

```bash
# 1. Set required API keys
export ALCHEMY_API_KEY="your-alchemy-api-key-here"

# 2. Verify config is loaded
python -c "from backend.config import settings; print(f'ALCHEMY_API_KEY: {\"SET\" if settings.ALCHEMY_API_KEY else \"NOT SET\"}')"

# 3. Test imports
python -c "from backend.bot.realtime_copy_trader import RealTimeCopyTrader; from backend.bot.realtime_whale_tracker import RealTimeWhaleTracker; print('✓ All imports OK')"
```

## Deployment

### Local Development

```bash
# 1. Start the API server (real-time strategies auto-start on lifespan)
python -m uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000

# 2. Monitor logs
# Both strategies will start automatically:
# - Copy Trader: Updates leaderboard, subscribes to Polymarket WebSocket
# - Whale Tracker: Connects to Alchemy WebSocket (or polling fallback)
```

### Docker Deployment

```bash
# Build
docker build -t polyedge:latest .

# Run with environment
docker run -e ALCHEMY_API_KEY=$ALCHEMY_API_KEY -p 8000:8000 polyedge:latest

# Verify startup
curl http://localhost:8000/api/v1/health
```

### Production (K8s / Cloud)

```yaml
# kubernetes secret
kubectl create secret generic polyedge-secrets \
  --from-literal=ALCHEMY_API_KEY=$ALCHEMY_API_KEY

# deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: polyedge
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: polyedge
        image: polyedge:latest
        ports:
        - containerPort: 8000
        env:
        - name: ALCHEMY_API_KEY
          valueFrom:
            secretKeyRef:
              name: polyedge-secrets
              key: ALCHEMY_API_KEY
        - name: AGI_AUTO_PROMOTE
          value: "true"
        livenessProbe:
          httpGet:
            path: /api/v1/health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
```

## Configuration

### Copy Trader Configuration

In `backend/config.py`:
```python
COPY_TRADER_MIN_PNL = 10000           # Only copy traders with >$10k PnL
COPY_TRADER_MIN_VOLUME = 100000       # Only copy traders with >$100k volume
```

In strategy `default_params`:
```python
"min_trader_pnl": 10000,              # Minimum PnL to copy
"min_trader_volume": 100000,          # Minimum trading volume
"max_traders_to_copy": 5,             # Top 5 traders tracked
"min_trade_size_usd": 1000,           # Minimum trade size to react to
"position_size_pct": 0.05,            # Copy 5% of bankroll per trade
"cooldown_seconds": 60,               # Don't copy same trader within 60s
"max_concurrent_positions": 5,        # Max open positions
```

### Whale Tracker Configuration

```python
"min_whale_balance_usd": 100000,      # Only track whales with >$100k
"min_transfer_size_usd": 10000,       # React to transfers >$10k
"position_size_pct": 0.03,            # Copy 3% of bankroll per whale trade
"max_concurrent_positions": 3,        # Max open whale positions
"cooldown_seconds": 300,              # 5 min cooldown per whale
"alchemy_api_key": "",                # Set via ALCHEMY_API_KEY env var
```

## Operations Runbook

### Monitoring

#### Health Checks
```bash
# API health
curl http://localhost:8000/api/v1/health

# System status
curl http://localhost:8000/api/v1/system/status
```

#### Logs
```bash
# Copy Trader logs
docker logs <container> | grep "copy_trader"

# Whale Tracker logs
docker logs <container> | grep "whale_tracker"

# Real-time manager logs
docker logs <container> | grep "RealTimeManager"
```

#### Metrics (Prometheus)
```
# Copy trades executed
rate(copy_trades_executed_total[5m])

# Whale trades executed
rate(whale_trades_executed_total[5m])

# WebSocket connection failures
rate(websocket_connection_errors_total[5m])
```

### Troubleshooting

#### Copy Trader Not Executing Trades

1. **Check leaderboard cache is populated**
   ```bash
   # Logs should show: "Tracking N profitable traders"
   docker logs <container> | grep "Tracking.*profitable traders"
   ```

2. **Verify CLOB orders are being placed**
   ```bash
   # Logs should show: "Order placed:"
   docker logs <container> | grep "Order placed:"
   ```

3. **Check trade size threshold**
   ```bash
   # If no trades: increase min_trade_size_usd or check market volume
   ```

#### Whale Tracker Not Executing

1. **ALCHEMY_API_KEY not set**
   ```bash
   # Should see fallback to polling
   docker logs <container> | grep "using polling fallback"
   ```

2. **Verify whale wallet configuration**
   ```bash
   # Should show tracked whales
   docker logs <container> | grep "Tracking.*whale wallets"
   ```

3. **Check Alchemy connection**
   ```bash
   # WebSocket errors will be logged
   docker logs <container> | grep "Alchemy WebSocket"
   ```

#### WebSocket Connection Issues

1. **Connection drops frequently**
   - Copy Trader will retry up to 3 times with 5s backoff
   - Whale Tracker falls back to polling (10s interval)
   - Check network connectivity and firewall rules

2. **High latency**
   - Leaderboard fetches have 10s timeout
   - If API is slow, increase timeout in code
   - Consider using CDN or caching proxy

### Graceful Shutdown

Real-time strategies are integrated with FastAPI lifespan. Shutdown sequence:

```
1. API receives shutdown signal
2. RealTimeStrategyManager.stop_all() called
3. WebSocket connections closed gracefully
4. Tasks cancelled
5. Process exits
```

On SIGTERM/SIGINT:
```bash
# Graceful shutdown (30s timeout)
kill -TERM <pid>

# Forced shutdown
kill -9 <pid>
```

### Scaling Considerations

#### Single-Instance (Current)
- One copy trader instance
- One whale tracker instance
- Leaderboard updated every 5 minutes (10s timeout)
- Scales to ~50 profitable traders

#### Multi-Instance (Future)
- Load-balance WebSocket subscriptions across instances
- Share leaderboard cache via Redis
- Use distributed task queue for order execution
- Add circuit breakers for API failures

## Performance

### Latency

| Component | Latency | Notes |
|-----------|---------|-------|
| Leaderboard fetch | <1s (10s timeout) | Cached 5 min, updated on startup |
| WebSocket subscribe | <100ms | Polymarket/Alchemy WS |
| Trade detection | <500ms | Filter by trader/whale |
| CLOB order execution | <2s | API call + confirmation |
| **Total copy-to-execution** | **<3s** | Near real-time |

### Resource Usage

- **Memory**: ~200MB (leaderboard cache + WS buffers)
- **CPU**: <5% (async event loop)
- **Network**: ~1KB/s per active market

### Throughput

- **Copy trades**: ~10-50 per day (market dependent)
- **Whale trades**: ~5-20 per day (whale activity dependent)
- **API calls**: ~1 leaderboard/5min + WebSocket events

## Security Considerations

### API Keys
- ✅ ALCHEMY_API_KEY stored in environment variables
- ✅ Never commit keys to git
- ✅ Rotate keys quarterly
- ⚠️ No rate limiting on copy trading (implement if needed)

### Order Execution
- ✅ Paper mode (simulation) by default
- ✅ Position size limits (5% per trade)
- ✅ Cooldown periods (60-300s per trader/whale)
- ⚠️ No slippage protection (orders are limit-priced)
- ⚠️ No stop-loss protection (add if needed)

### WebSocket Security
- ✅ WSS (encrypted) for Alchemy
- ✅ WS for Polymarket (on-chain data, public)
- ⚠️ No authentication on Polymarket WebSocket

## Testing

### Unit Tests
```bash
pytest backend/tests/test_realtime_strategies.py -v
# Expected: 8 passing tests
```

### Integration Tests
```bash
pytest backend/tests/ -k "realtime" -v
# Tests copy trader leaderboard, whale tracker initialization, etc.
```

### Manual Testing
```bash
# 1. Start API
python -m uvicorn backend.api.main:app

# 2. Monitor logs
tail -f logs/app.log | grep -E "copy_trader|whale_tracker"

# 3. Trigger leaderboard update
curl http://localhost:8000/api/v1/admin/update-leaderboard

# 4. Check health
curl http://localhost:8000/api/v1/health
```

## Maintenance

### Weekly
- [ ] Review trade execution logs
- [ ] Check error rates
- [ ] Verify WebSocket connectivity

### Monthly
- [ ] Update leaderboard thresholds based on market conditions
- [ ] Review PnL and adjust position sizing
- [ ] Rotate API keys

### Quarterly
- [ ] Security audit
- [ ] Performance profiling
- [ ] Disaster recovery drill

## Support & Debugging

### Log Levels
- **DEBUG**: Detailed WebSocket messages, TX parsing
- **INFO**: Strategy actions (trades, connections)
- **WARNING**: API failures, reconnection attempts
- **ERROR**: Critical failures, shutdown

### Enable Debug Logging
```bash
export LOGLEVEL=DEBUG
python -m uvicorn backend.api.main:app
```

### Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| No trades executed | Leaderboard empty | Wait 5min for update, check API |
| WebSocket disconnects | Network issues | Check firewall, retry logic |
| High latency | Slow API | Increase timeout, use caching |
| Memory leak | Unbounded cache | Restart weekly or add eviction |
| Whale tracker not tracking | ALCHEMY_API_KEY not set | Export env var and restart |

## References

- [Polymarket API Docs](https://docs.polymarket.com)
- [Alchemy WebSocket Docs](https://docs.alchemy.com)
- [FastAPI Lifespan](https://fastapi.tiangolo.com/advanced/events/)
