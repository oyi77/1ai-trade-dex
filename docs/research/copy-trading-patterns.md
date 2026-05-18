# Copy Trading Patterns

**Date**: 2026-05-18
**Sources**: polycopy, G3-DEV-AGENCY approaches

## Overview

Copy trading on Polymarket involves monitoring top-performing wallets and replicating their positions. PolyEdge already has a `copy_trader` module in `backend/modules/`.

## Key Patterns from polycopy

### 1. Leaderboard Scraping

- Scrape Polymarket leaderboard for top traders by PnL
- Track wallet addresses with highest win rates
- Filter by activity recency (last 7/30 days)

### 2. Position Detection

- Monitor on-chain events for position changes
- Use CLOB API `get_trades()` to detect new orders
- WebSocket subscriptions for real-time trade detection

### 3. Position Sizing

- **Fixed fraction**: Copy X% of the leader's position size
- **Kelly-adjusted**: Scale based on our own bankroll
- **Risk-capped**: Never exceed max position per market

### 4. Latency Considerations

- On-chain detection: ~2-15s delay (block confirmation)
- CLOB API: ~1-3s delay (API polling)
- WebSocket: ~0.5-1s delay (real-time)
- For 5-min markets, even 3s delay can erode edge

## Key Patterns from G3-DEV-AGENCY

### 1. Multi-Wallet Diversification

- Copy multiple leaders simultaneously
- Weight by historical correlation with our strategies
- Avoid concentration in correlated positions

### 2. Anti-Frontrunning

- Don't copy if the leader's order moved the price significantly
- Check spread before copying (don't chase illiquid markets)
- Implement a "cooling off" period after large price moves

### 3. Performance Attribution

- Track per-leader PnL separately
- Degrade leaders with declining performance
- Auto-stop copying after N consecutive losses

## PolyEdge Integration Points

- `backend/modules/copy_trader/`: Existing module for leaderboard tracking
- `backend/data/whale_monitor_ws.py`: WebSocket whale monitoring
- `backend/strategies/whale_frontrun.py`: Whale-based strategy
- `backend/data/goldsky_client.py`: On-chain data via Goldsky

## Recommended Enhancements

1. **WebSocket-first**: Use WS for real-time trade detection instead of polling
2. **Leader scoring**: Weight leaders by Sharpe ratio, not just PnL
3. **Slippage model**: Account for market impact when copying large positions
4. **Correlation filter**: Don't copy leaders whose positions overlap with ours
