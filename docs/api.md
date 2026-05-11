# API Reference

## API Versioning

All API endpoints are versioned using the `/v1` prefix. The current version is **v1**.

**Base URL**: `http://localhost:8100/api/v1`

**Version Detection**:
1. URL path: `/api/v1/...` (primary method)
2. Accept-Version header: `Accept-Version: v1` (fallback)

**Response Headers**:
- All responses include `X-API-Version: v1` header

**Invalid Version**:
- Returns 400 Bad Request if version is invalid or unsupported

**Documentation**: See `docs/api-versioning.md` for detailed versioning strategy.

## Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/dashboard` | GET | All dashboard data in one call |
| `/api/v1/btc/price` | GET | Current BTC price + momentum |
| `/api/v1/btc/windows` | GET | Active BTC 5-min windows |
| `/api/v1/signals` | GET | Current BTC trading signals |
| `/api/v1/signals/actionable` | GET | BTC signals above threshold |
| `/api/v1/kalshi/status` | GET | Kalshi API auth status + balance |
| `/api/v1/weather/forecasts` | GET | Ensemble forecasts for all cities |
| `/api/v1/weather/markets` | GET | Weather markets (Kalshi + Polymarket) |
| `/api/v1/weather/signals` | GET | Weather trading signals (both platforms) |
| `/api/v1/trades` | GET | Trade history |
| `/api/v1/stats` | GET | Bot statistics |
| `/api/v1/trade-attempts` | GET | Trade Control Room attempt ledger with execution/risk blockers |
| `/api/v1/trade-attempts/summary` | GET | Aggregate execution rate, blockers, and recent rejected attempts |
| `/api/v1/calibration` | GET | Signal calibration data |
| `/api/v1/run-scan` | POST | Trigger BTC + weather scan |
| `/api/v1/simulate-trade` | POST | Simulate a BTC trade |
| `/api/v1/settle-trades` | POST | Check settlements |
| `/api/v1/bot/start` | POST | Start trading |
| `/api/v1/bot/stop` | POST | Pause trading |
| `/api/v1/bot/reset` | POST | Reset all trades |
| `/api/v1/events` | GET | Event log |

## Health Check Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Basic health check (load balancers) |
| `/health/ready` | GET | Readiness check (dependencies) |
| `/health/detailed` | GET | Detailed system status |

See `docs/operations/monitoring.md` for health check details.

## System Monitoring Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/system/errors` | GET | Recent error logs |
| `/api/v1/system/aggregation` | GET | Error aggregation by type/endpoint |
| `/api/v1/system/rate` | GET | Current error rate (errors/minute) |
| `/api/v1/system/cleanup` | POST | Cleanup old error logs |
| `/api/v1/system/alerts` | GET | System alerts |
| `/api/v1/system/alerts/stats` | GET | Alert statistics |
| `/api/v1/system/alerts/{id}/resolve` | POST | Resolve alert |
| `/api/v1/system/metrics` | GET | Current system metrics |
| `/api/v1/system/audit-logs` | GET | Configuration change audit trail |
| `/metrics` | GET | Prometheus metrics |

See `docs/operations/monitoring.md` for monitoring details.

`GET /api/v1/stats` and `GET /api/v1/dashboard` expose paper/testnet `bankroll` as available simulated cash, so those balance fields are never negative. The matching `paper_pnl`/`testnet_pnl` and nested `pnl` fields can be negative because they preserve cumulative learning-ledger drawdown.

`GET /api/v1/dashboard` returns live scan results directly from the in-process scan pipeline. Persistence of generated scan rows to the calibration ledger is best-effort and asynchronous, so temporary SQLite write contention may emit warnings without delaying the dashboard response.

`BotStats` now also includes explicit balance breakdown fields for realtime UI updates:
- `available_balance`: currently spendable cash for the selected mode
- `total_balance`: available cash plus marked-to-market open-position value (for live, reconciled total equity)
- `realized_pnl`: settled/realized P&L only, excluding unrealized position moves

For live mode, `total_pnl` / `account_pnl` follow the public Polymarket account/profile PnL semantics when the upstream profile PnL API is available. `realized_pnl` remains the local settled-trade ledger PnL so realized and account-level PnL are not conflated.

The nested `paper`, `testnet`, and `live` objects expose the same `available_balance`, `total_balance`, `realized_pnl`, and `account_pnl` fields per mode.

## Trade Control Room Endpoints

These endpoints back the dashboard **Control Room** tab. They are intentionally separate from `Trade` history: `Trade` contains executed positions, while `TradeAttempt` records every candidate execution path that reached the strategy executor, including risk rejections and sizing blockers. For AI-sized strategies, compare `requested_size` with `adjusted_size` and `risk_reason` to see how much autonomy was allowed before deterministic risk mandates clipped or rejected the attempt.

### `GET /api/v1/trade-attempts`

Returns paginated attempt rows ordered newest-first by default.

**Query parameters:**
- `mode`: `paper`, `testnet`, `live`, or omitted for all modes
- `status`: `EXECUTED`, `REJECTED`, `BLOCKED`, `FAILED`, or omitted for all statuses
- `strategy`: exact strategy name
- `reason_code`: exact machine-readable blocker code
- `market`: substring match against `market_ticker`
- `since`, `until`: ISO timestamps
- `sort`, `order`, `limit`, `offset`: pagination/sorting controls

**Response shape:**
```json
{
  "items": [
    {
      "attempt_id": "uuid",
      "correlation_id": "uuid",
      "strategy": "general_scanner",
      "mode": "live",
      "market_ticker": "2086090",
      "status": "REJECTED",
      "phase": "risk_gate",
      "reason_code": "REJECTED_DRAWDOWN_BREAKER",
      "reason": "24h loss exceeds limit",
      "bankroll": 170.1,
      "current_exposure": 0,
      "requested_size": 50,
      "adjusted_size": 0,
      "risk_allowed": false,
      "trade_id": null
    }
  ],
  "total": 1
}
```

### `GET /api/v1/trade-attempts/summary`

Returns aggregate operator data for the Control Room header: total attempts, executed attempts, blocked/rejected/failed attempts, execution rate, top blocker reason codes, and recent blockers.

## WebSocket Endpoints

| Endpoint | Protocol | Description |
|----------|----------|-------------|
| `/ws/markets` | WS | Market data updates (topic: "markets") |
| `/ws/whales` | WS | Whale trader activity (topic: "whales") |
| `/ws/events` | WS | Trading events (topic: "events") |
| `/ws/activities` | WS | Activity log (topic: "activities") |
| `/ws/brain` | WS | AI analysis (topic: "brain") |
| `/ws/dashboard-data` | WS | Dashboard stats incl. realtime balance/P&L breakdown (topic: "stats") |

Realtime endpoints (`/api/events/stream`, `/api/v1/events/stream`, and `/ws/*`) require the same admin authentication model as REST:
- Preferred: valid `admin_session` httpOnly cookie (from `/api/v1/admin/auth/login`)
- Legacy fallback: `token=<ADMIN_API_KEY>` query parameter

When `ADMIN_API_KEY` is unset, realtime endpoints are open for local/dev mode.

**Subscription Protocol**:
```json
// Client sends after connection
{"action": "subscribe", "topic": "markets"}

// Server responds
{"type": "subscribed", "topic": "markets"}
```

## Rate Limiting

All endpoints are rate limited to prevent abuse:

**Rate Limit Tiers**:
- High-frequency: 100 requests/minute
- Medium-frequency: 50 requests/minute
- Low-frequency: 20 requests/minute

**Response Headers**:
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Requests remaining
- `X-RateLimit-Reset`: Unix timestamp when limit resets

**429 Response**:
```json
{
  "detail": "Rate limit exceeded. Try again in 60 seconds.",
  "retry_after": 60
}
```

See `docs/operations/scalability.md` for rate limiting details.

## Authentication

Admin endpoints require authentication via cookie login (`POST /api/v1/admin/auth/login`) and CSRF for mutating requests.  
Legacy `Authorization: Bearer <ADMIN_API_KEY>` remains supported for backward compatibility on REST endpoints.
