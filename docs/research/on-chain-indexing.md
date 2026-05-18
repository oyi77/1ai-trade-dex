# On-Chain Data Indexing for Polymarket

**Date**: 2026-05-18
**Approach**: The Graph subgraph indexing

## Problem

Polymarket trades and settlements happen on-chain (Polygon/Matic). To analyze historical trading patterns, whale movements, and settlement outcomes, we need efficient on-chain data access. Raw RPC calls are too slow for real-time use.

## The Graph Protocol

The Graph is a decentralized indexing protocol for querying blockchain data using GraphQL.

### How It Works

1. **Subgraph**: A manifest that defines which on-chain events to index
2. **Indexer**: Node that processes blockchain data into the subgraph
3. **Query**: GraphQL endpoint that serves indexed data

### Polymarket Subgraphs

Polymarket has existing subgraphs on The Graph's hosted service:

- **CTF (Conditional Token Framework)**: Token transfers, positions, redemptions
- **Exchange**: Order fills, trades, fees
- **NegRisk**: Negative risk market operations

### GraphQL Query Example

```graphql
{
  positions(
    first: 100
    where: { user: "0x..." }
    orderBy: timestamp
    orderDirection: desc
  ) {
    market {
      question
      outcome
    }
    size
    price
    timestamp
  }
}
```

## PolyEdge Integration

### Current State

- `backend/data/goldsky_client.py`: Already uses Goldsky (The Graph indexer) for on-chain data
- `backend/data/whale_monitor_ws.py`: WebSocket-based whale monitoring

### Recommended Enhancements

1. **Historical trade analysis**: Query CTF subgraph for resolved market outcomes
2. **Whale position tracking**: Monitor large position changes in real-time
3. **Settlement verification**: Cross-reference on-chain settlements with CLOB API data
4. **Market maker analysis**: Track LP positions and withdrawal patterns

### Implementation

```python
# Using existing goldsky_client.py pattern
from backend.data.goldsky_client import GoldskyClient

client = GoldskyClient()
query = """
{
  positions(first: 100, where: { market: "0x..." }) {
    user
    size
    outcome
    timestamp
  }
}
"""
result = await client.query(query)
```

## Alternatives Considered

| Approach | Pros | Cons |
|----------|------|------|
| **The Graph** | Decentralized, GraphQL, existing subgraphs | Latency (eventual consistency), query rate limits |
| **Direct RPC** | Real-time, no third party | Slow for historical, expensive |
| **Goldsky** | Fast, managed infrastructure | Vendor lock-in, cost |
| **Dune Analytics** | SQL queries, community dashboards | Not real-time, API limits |

## Recommendation

Continue using Goldsky (The Graph indexer) for real-time data. Add Dune Analytics for historical analysis (see `dune-analytics.md`). Use direct RPC only for settlement verification.
