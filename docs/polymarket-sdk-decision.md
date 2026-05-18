# Polymarket SDK Decision (G-29/G-32)

## Decision: Use py-clob-client, Not polymarket-sdk

**Date**: 2026-05-18
**Status**: Accepted

### Context

The project needs to interact with Polymarket's CLOB (Central Limit Order Book) API for order placement, cancellation, and market data. Two SDK options exist:

1. **py-clob-client** (currently used) — The official Polymarket CLOB client maintained by the Polymarket team. Handles EIP-712 signing, L2 HMAC authentication, tick-size resolution, and order building internally.

2. **polymarket-sdk** — A higher-level SDK wrapping multiple Polymarket APIs (Gamma, CLOB, Data).

### Decision

We continue using **py-clob-client** (aliased as `py_clob_client_v2` in our codebase) because:

- It directly handles the critical auth flow (EIP-712 L1 key derivation + L2 HMAC-SHA256 per-request headers)
- It is the SDK referenced by Polymarket's official CLOB API documentation
- We have already built extensive infrastructure around it (`backend/data/polymarket_clob.py` — 1150 LOC)
- The `polymarket-sdk` adds an abstraction layer without meaningful benefit for our use case (we interact with CLOB directly)

### Known Issues with py-clob-client (G-32)

| Issue | Workaround |
|-------|------------|
| `OrderArgs.size` must be in USDC, not shares — confusing naming | Always convert shares to USDC before passing to `place_order()` |
| Tick-size resolution can fail silently for non-standard markets | Validate tick size via `get_tick_size()` before order placement |
| EIP-712 signing can timeout on slow hardware | Use 30s timeout on `ClobClient` init |
| `get_order_book()` returns empty for expired markets | Check `market.active` before fetching order book |
| Rate limiting is not handled by the SDK itself | Our `TokenBucketRateLimiter` in `strategy_executor.py` handles this |

### G-31: Builder Leaderboard API

The Polymarket Builder Leaderboard API (`/builder-leaderboard`) provides whale trader data for the copy trading strategy. This is accessed via `backend/data/polymarket_clob.py` through the Data API host, not through the CLOB SDK.

## References

- `backend/data/polymarket_clob.py` — Main CLOB client wrapper (1150 LOC)
- `backend/core/external_rate_limiter.py` — Rate limiting for CLOB API calls
- `backend/strategies/crypto_oracle.py` — Primary consumer of CLOB market data
