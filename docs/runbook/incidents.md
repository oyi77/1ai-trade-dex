# Incident Response

## Severity Levels

| Level | Description | Response Time |
|-------|-------------|---------------|
| Critical | Money loss, stuck trades, exchange connectivity down | Immediate |
| High | Strategy failures, data feed down, dashboard unreachable | < 30 min |
| Medium | Performance degradation, stale data, warning alerts | < 4 hours |
| Low | Cosmetic issues, non-blocking errors | Next business day |

## Alert Sources

- **Telegram bot**: `ALERT_BOT_TOKEN` + `ALERT_CHAT_ID` — critical + high alerts
- **Dashboard**: `/api/health` endpoint — system status
- **Prometheus**: `polyedge_risk_rejection_total`, `polyedge_circuit_breaker_state`
- **Grafana**: Dashboard at port 3000 (monitoring profile)

## Triage Flow

1. **Check health endpoint**: `curl localhost:8100/api/health`
2. **Check PM2**: `pm2 status` — are all 3 processes running?
3. **Check logs**: `pm2 logs --lines 100`
4. **Check circuit breakers**: Are any breakers OPEN?
5. **Check Redis**: `redis-cli ping` — queue operational?
6. **Check exchange connectivity**: Polymarket CLOB + Kalshi API reachable?

## Common Incident Playbooks

### Stuck Trades

```bash
# Check pending trades
curl localhost:8100/api/trades?settled=false

# Force settlement check
curl -X POST localhost:8100/api/admin/settle -H "Authorization: Bearer $ADMIN_API_KEY"
```

### Strategy Killed

```bash
# Check strategy health
curl localhost:8100/api/admin/strategies

# Re-enable (if justified)
curl -X PATCH localhost:8100/api/admin/strategies/<name>/enable -H "Authorization: Bearer $ADMIN_API_KEY"
```

### Exchange API Down

```bash
# Check circuit breaker state
curl localhost:8100/api/health | jq '.circuit_breakers'

# Wait for automatic recovery (HALF_OPEN → CLOSED)
# Or manual reset:
curl -X POST localhost:8100/api/admin/circuit-breaker/<name>/reset -H "Authorization: Bearer $ADMIN_API_KEY"
```

## Postmortem Template

```markdown
## Incident: [Title]
- **Date**: YYYY-MM-DD
- **Duration**: X hours Y minutes
- **Severity**: Critical/High/Medium/Low
- **Impact**: [What was affected]

### Timeline
- HH:MM — Alert triggered
- HH:MM — Investigation started
- HH:MM — Root cause identified
- HH:MM — Fix deployed
- HH:MM — Service restored

### Root Cause
[Technical explanation]

### Fix
[What was done to resolve]

### Prevention
[Changes to prevent recurrence]
```
