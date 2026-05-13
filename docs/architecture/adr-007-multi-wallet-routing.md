# ADR-007: Multi-Wallet Routing

**Status:** Accepted  
**Date:** 2026-05-13

## Context

PolyEdge initially supported a single wallet per market provider. Users operating multiple trading accounts — for capital segregation, risk isolation, or regulatory separation — had no way to route signals to different wallets based on strategy or policy.

The system needed a routing layer that:
1. Maps each strategy to one or more wallets with configurable allocation weights
2. Supports both Polymarket (CLOB, private-key-based) and Kalshi (REST API key-based) wallets from a single config surface
3. Does not break existing single-wallet code paths
4. Stores credentials encrypted at rest, never in environment variables or source code

## Decision

Introduce a `TradingWallet` ORM model and a `WalletAllocation` join table that binds strategies to wallets with per-row weight and exposure caps.

### Routing Logic

When a strategy produces a signal, the execution router:
1. Queries `WalletAllocation` for all enabled rows matching `strategy_name`
2. Scales the proposed order size by each row's `weight`
3. Caps each leg at `max_exposure_usd` if set
4. Dispatches one order per wallet concurrently via `asyncio.gather`

Strategies with no `WalletAllocation` rows fall back to the legacy `POLYMARKET_PRIVATE_KEY` / `KALSHI_API_KEY` environment-variable path — preserving backward compatibility.

### Credential Storage

Private keys and API secrets are stored Fernet-encrypted in `TradingWallet.encrypted_private_key` / `encrypted_api_secret`. The encryption key is sourced from `WALLET_ENCRYPTION_KEY` in the environment and never persisted to the database.

### Schema

| Table | Purpose |
|---|---|
| `trading_wallets` | One row per wallet: chain, address, encrypted credentials, paper flag |
| `wallet_allocations` | N↔N: strategy → wallet with weight + exposure cap |

## Consequences

**Positive**
- Strategies can fan out to N wallets with a single config change
- Paper wallets (`is_paper=True`) can be included in the routing table for shadow testing alongside live wallets
- Credential management is centralised and encrypted; no more scattered env vars per wallet

**Negative**
- Concurrent order dispatch increases database write contention on `trades` table — mitigated by per-wallet row inserts rather than bulk upserts
- Adding wallets to `WalletAllocation` after a strategy is live requires a DB write; there is no UI for this in v1 (admin API only)

## Alternatives Considered

**Environment variable fan-out** (e.g. `WALLET_1_KEY`, `WALLET_2_KEY`): rejected — no per-strategy routing, no allocation weights, operationally fragile.

**Separate deployments per wallet**: rejected — multiplies infrastructure cost and eliminates cross-wallet signal sharing.
