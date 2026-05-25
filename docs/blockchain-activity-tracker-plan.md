# Blockchain Activity Tracker — Plan

## Goal
Real-time tracking of all wallet activities via blockchain + exchange APIs.
Events: deposit, withdrawal, trade_open, trade_closed, buy, sell, redeem, transfer.

## Architecture

```
backend/core/activity/
├── __init__.py
├── tracker.py          # ActivityTracker — event dispatcher
├── sources/           # Per-platform activity sources
│   ├── __init__.py
│   ├── aster_source.py   # Aster WebSocket (fills, balance)
│   ├── hyperliquid_source.py  # HL WebSocket (user_fills)
│   ├── lighter_source.py # Lighter WebSocket
│   ├── polymarket_source.py  # CLOB API (fills, orders)
│   ├── polymarket_onchain.py  # Polygon scanner (deposit/withdrawal)
│   └── base.py         # BaseActivitySource
├── models.py          # ActivityEvent dataclass
├── event_handler.py    # Process events → update bankroll/positions
└── reconciler.py      # Match on-chain events to DB trades
```

## ActivityEvent Model

```python
@dataclass
class ActivityEvent:
    id: str                    # UUID
    source: str                # 'aster' | 'hyperliquid' | 'lighter' | 'polymarket' | 'polygon'
    event_type: str            # 'deposit' | 'withdrawal' | 'trade_open' | 'trade_closed' | 'buy' | 'sell' | 'redeem' | 'transfer'
    wallet_address: str
    platform: str              # 'aster' | 'hyperliquid' | 'polymarket' | etc.
    amount: float
    token: str                 # 'USDC' | 'ETH' | 'MATIC' | etc.
    tx_hash: Optional[str]
    timestamp: datetime
    raw_data: dict            # Original event data
    trade_id: Optional[str]   # Link to DB Trade if matched
```

## Per-Platform Data Sources

### Aster
- **WS**: `subscribe("fills", wallet_address)` — trade_open, trade_closed, buy, sell
- **WS**: `subscribe("balances", wallet_address)` — deposit, withdrawal (balance delta)
- **RPC**: Polygon scanner for historical deposit/withdrawal

### Hyperliquid
- **WS**: `subscribe("userFills", wallet_address)` — fills, positions
- **WS**: `subscribe("userEvents")` — balance updates
- **L1**: ETH RPC for deposits/withdrawals

### Lighter
- **WS**: balance updates + fill events
- **L2**: Ethereum scanner for deposit/withdrawal

### Polymarket
- **CLOB API**: `/fills` endpoint — trade_open, trade_closed
- **Polygon scanner**: USDC deposit/withdrawal on Polygon

### Cross-chain (all platforms)
- **Etherscan/Polygonscan API**: fetch transfer history by wallet
- **web3.py**: subscribe to Transfer events (ERC20, native)

## Event Flow

```
Blockchain/Exchange WS → ActivitySource → ActivityTracker.dispatch()
    → ActivityHandler.process()
        → BankrollAllocator.update_from_activity()
        → PositionTracker.update_open_positions()
        → TradeReconciler.match_to_db_trade()
        → AuditLogger.log_activity()
```

## Reconciler Logic

Match on-chain fill to DB Trade:
1. Look for Trade with matching `external_order_id` or `tx_hash`
2. If not found: create Trade with `status=pending`, link to ActivityEvent
3. When trade_closed event arrives: update Trade status to `closed`, record PnL

## Implementation Steps

| Step | What | File |
|------|------|------|
| 1 | ActivityEvent dataclass + models | `backend/core/activity/models.py` |
| 2 | BaseActivitySource abstract class | `backend/core/activity/sources/base.py` |
| 3 | ActivityTracker dispatcher | `backend/core/activity/tracker.py` |
| 4 | Aster WS source | `backend/core/activity/sources/aster_source.py` |
| 5 | Hyperliquid WS source | `backend/core/activity/sources/hyperliquid_source.py` |
| 6 | Polymarket source (CLOB + on-chain) | `backend/core/activity/sources/polymarket_source.py` |
| 7 | ActivityHandler | `backend/core/activity/event_handler.py` |
| 8 | Reconciler (match events to trades) | `backend/core/activity/reconciler.py` |
| 9 | Wire into orchestrator.start() | lifespan + orchestrator |
| 10 | Dashboard API endpoint | `/api/v1/activity` |

## Database Extension

```sql
CREATE TABLE activity_events (
    id UUID PRIMARY KEY,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    platform TEXT NOT NULL,
    amount FLOAT NOT NULL,
    token TEXT NOT NULL,
    tx_hash TEXT,
    timestamp TIMESTAMPTZ NOT NULL,
    raw_data JSONB,
    trade_id UUID REFERENCES trades(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_activity_wallet ON activity_events(wallet_address);
CREATE INDEX idx_activity_type ON activity_events(event_type);
CREATE INDEX idx_activity_timestamp ON activity_events(timestamp DESC);
```

## Notes

- Activity sources run as async tasks within orchestrator
- Each source manages its own WebSocket connection with auto-reconnect
- Rate limit: Etherscan free tier = 5 calls/sec, cache responses
- Balance reconciliation: compare on-chain balance vs DB bankroll, flag discrepancies
- All events logged to audit logger for compliance