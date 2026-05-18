# Dune Analytics for Polymarket Data

**Date**: 2026-05-18

## Overview

Dune Analytics is a community-driven blockchain analytics platform that lets you query on-chain data using SQL. It's ideal for historical analysis of Polymarket trading patterns, volume, and settlement outcomes.

## Key Capabilities

### 1. Historical Volume Analysis

```sql
-- Daily trading volume on Polymarket CTF
SELECT
    date_trunc('day', evt_block_time) AS day,
    COUNT(*) AS trade_count,
    SUM(amount_usd) AS volume_usd
FROM polymarket_evt_trade
WHERE evt_block_time >= '2026-01-01'
GROUP BY 1
ORDER BY 1
```

### 2. Top Trader Analysis

```sql
-- Top 50 traders by volume
SELECT
    trader,
    COUNT(*) AS trades,
    SUM(amount_usd) AS total_volume,
    AVG(amount_usd) AS avg_trade_size
FROM polymarket_evt_trade
WHERE evt_block_time >= NOW() - INTERVAL '30' DAY
GROUP BY 1
ORDER BY 3 DESC
LIMIT 50
```

### 3. Settlement Outcomes

```sql
-- Market resolution analysis
SELECT
    question,
    outcome,
    total_volume,
    resolution_time
FROM polymarket_markets
WHERE resolved = true
ORDER BY total_volume DESC
```

### 4. Crypto 5-Min Market Analysis

```sql
-- BTC 5-min market performance
SELECT
    date_trunc('hour', evt_block_time) AS hour,
    COUNT(*) AS markets_resolved,
    AVG(CASE WHEN outcome = 'Yes' THEN 1 ELSE 0 END) AS yes_rate
FROM polymarket_evt_trade t
JOIN polymarket_markets m ON t.market_id = m.id
WHERE m.slug LIKE 'btc-updown-5m-%'
GROUP BY 1
ORDER BY 1
```

## PolyEdge Integration

### Use Cases

1. **Strategy backtesting**: Fetch historical settlement data for backtesting
2. **Whale detection**: Identify wallets with consistently high PnL
3. **Volume analysis**: Detect unusual volume spikes before price moves
4. **Market efficiency**: Measure bid-ask spread evolution over time

### API Access

```python
import httpx

DUNE_API = "https://api.dune.com/api/v1"
DUNE_API_KEY = settings.DUNE_API_KEY  # Add to config.py

async def query_dune(query_id: int) -> dict:
    """Execute a Dune query and return results."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{DUNE_API}/query/{query_id}/results",
            headers={"X-Dune-API-Key": DUNE_API_KEY},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()
```

### Existing Community Queries

Dune has community dashboards for Polymarket:

- Polymarket daily volume and users
- Top traders leaderboard
- Market resolution statistics
- Crypto binary market analysis

## Setup

1. Create Dune Analytics account (free tier available)
2. Get API key from https://dune.com/settings/api
3. Add `DUNE_API_KEY` to `backend/config.py`
4. Use existing community queries or create custom ones

## Limitations

- **Not real-time**: Data lags by ~15 minutes
- **Rate limits**: Free tier has query limits
- **Historical only**: Not suitable for live trading signals
- **Data freshness**: Depends on blockchain confirmation times

## Recommendation

Use Dune for **offline analysis and backtesting data**, not for live trading. Combine with Goldsky (real-time) and CLOB API (order book) for a complete data stack.
