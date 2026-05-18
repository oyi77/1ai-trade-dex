# py-clob-client Open Issues Analysis

**Date**: 2026-05-18
**Source**: https://github.com/Polymarket/py-clob-client
**Total Open Issues**: ~103

## Issues Affecting PolyEdge

### High Impact

| Issue | Description | Impact on PolyEdge |
|-------|-------------|-------------------|
| Rate limiting on order placement | CLOB API returns 429 under high load | Direct: our oracle strategy fires many orders in short windows |
| WebSocket disconnection handling | WS client doesn't auto-reconnect reliably | Affects `polymarket_websocket.py` real-time price feeds |
| `get_order_book` stale data | Order book snapshots can be stale by seconds | Affects edge calculation in crypto_oracle |
| Decimal precision | Price rounding issues with certain market types | Affects order fill accuracy |

### Medium Impact

| Issue | Description | Impact on PolyEdge |
|-------|-------------|-------------------|
| `create_and_post_order` timeout | Order creation can hang on slow networks | Affects executor reliability |
| `get_trades` pagination | Trade history pagination incomplete | Affects P&L reconciliation |
| Auth token refresh | Token expiry not handled gracefully | Affects long-running bot sessions |
| `get_markets` filtering | Market list endpoint returns inconsistent results | Affects market scanner |

### Low Impact (Research Only)

| Issue | Description | Impact on PolyEdge |
|-------|-------------|-------------------|
| Documentation gaps | Missing docs for several endpoints | Development friction |
| Test coverage | Some client methods lack tests | N/A (we test our code) |
| Python 3.12+ compat | Some type hint issues on newer Python | Minimal (we use 3.11+) |

## Mitigations Already in Place

1. **Circuit breaker**: `backend/core/circuit_breaker.py` wraps CLOB calls
2. **Rate limiter**: `backend/core/external_rate_limiter.py` throttles API calls
3. **Retry logic**: Built into `polymarket_clob.py` with exponential backoff
4. **WebSocket reconnect**: `polymarket_websocket.py` has reconnect with backoff

## Recommended Actions

1. **Pin py-clob-client version** in requirements.txt to avoid surprise regressions
2. **Monitor upstream issues** for rate limiting fixes before going live
3. **Test WebSocket reconnection** under network partition scenarios
4. **Add CLOB response validation** to catch schema changes early
