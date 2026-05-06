# AGI Enhancement Roadmap - Prediction Market Analysis Integration

**Date**: May 6, 2026  
**Source**: Analysis of https://github.com/Jon-Becker/prediction-market-analysis  
**Owner**: AGI Strategy Team

---

## QUICK START: 3 Highest-Impact Wins

### 1. Maker/Taker Role Classification (1-2 weeks, +2-3% edge)

**Current State**: We know trade outcomes but don't classify our role in the trade.

**Gap**: On CLOB exchanges, there's a structural arbitrage:
- Makers (liquidity providers) earn 2-5% baseline edge from spread capture
- Takers pay spread + slippage
- On Kalshi, makers outperform takers by ~2% on average

**Implementation**:
```python
# In backend/core/risk_manager.py or new backend/core/trade_forensics.py

class TradeRole(str, Enum):
    MAKER = "maker"      # We posted order, someone took it
    TAKER = "taker"      # We took existing order
    UNKNOWN = "unknown"  # Could not determine

# Detect maker vs taker:
def classify_trade_role(trade_attempt: TradeAttempt, order_book_snapshot) -> TradeRole:
    """
    If our order was on book before execution → MAKER
    If we crossed spread to fill → TAKER
    """
    if trade_attempt.created_at < order_book_snapshot.fetch_time:
        return TradeRole.MAKER
    return TradeRole.TAKER

# Track in BotState
@dataclass
class Trade(Base):
    role: TradeRole = TradeRole.UNKNOWN
    
# Aggregate in Control Room
maker_trades = [t for t in trades if t.role == TradeRole.MAKER]
taker_trades = [t for t in trades if t.role == TradeRole.TAKER]
maker_roi = sum(t.pnl for t in maker_trades) / sum(t.notional for t in maker_trades)
taker_roi = sum(t.pnl for t in taker_trades) / sum(t.notional for t in taker_trades)
# Display: "Makers: +1.8%, Takers: -0.9%"
```

**AGI Feedback Loop**:
- If maker ROI consistently > taker ROI → increase market-making strategy weight
- If taker ROI negative → reduce aggressive order placement, use limit orders

---

### 2. Price Bucket Calibration Tracking (1 week, +1-2% tuning)

**Current State**: We track overall win rate but don't bucket by price level.

**Gap**: Markets have systematic pricing errors that vary by price:
- Low prices (10-20¢): Consistently overpriced by 1-3% (longshot bias)
- High prices (80-90¢): Consistently underpriced by 0.5-1% (favorite bias)
- Mid prices (40-60¢): Near fair value

**Implementation**:
```python
def compute_calibration_buckets(trades: List[Trade], window_days=30):
    """Compute win rate by price bucket for recent trades."""
    recent = [t for t in trades if (now - t.timestamp).days <= window_days]
    
    # Group by price bucket (5¢ increments)
    buckets = {}
    for bucket_price in range(5, 100, 5):  # 5-10¢, 10-15¢, etc.
        bucket_trades = [
            t for t in recent 
            if bucket_price <= t.price < bucket_price + 5 and t.resolved
        ]
        if bucket_trades:
            win_rate = sum(t.won for t in bucket_trades) / len(bucket_trades)
            calibration_error = win_rate - (bucket_price / 100)
            buckets[bucket_price] = {
                'predicted': bucket_price / 100,
                'actual': win_rate,
                'error': calibration_error,
                'trades': len(bucket_trades),
                'confidence': len(bucket_trades) / 50
            }
    
    return buckets
```

---

### 3. Longshot Bias Signal (3-5 days, +1-2% alpha on selective trades)

**Current State**: No explicit detection of longshot vs favorite bias.

**Implementation**:
```python
def compute_longshot_bias(trades: List[Trade], price_threshold=30, window_days=60):
    """Measure overpricing of low-probability events."""
    recent = [t for t in trades if (now - t.timestamp).days <= window_days and t.resolved]
    
    longshot_trades = [t for t in recent if t.price < price_threshold]
    favorite_trades = [t for t in recent if t.price >= price_threshold]
    
    if not longshot_trades or not favorite_trades:
        return None
    
    longshot_win_rate = sum(t.won for t in longshot_trades) / len(longshot_trades)
    longshot_expected = (sum(t.price for t in longshot_trades) / len(longshot_trades)) / 100
    
    bias = longshot_win_rate / longshot_expected if longshot_expected > 0 else None
    # bias < 1.0 → longshots are overpriced
    
    return {
        'bias': bias,
        'strength': 1 - bias,
        'sample_size': len(longshot_trades),
        'confidence': min(len(longshot_trades) / 100, 1.0)
    }
```

---

## BLOCKCHAIN EVENT INDEXING (Week 3-4)

**Why**: Direct CLOB OrderFilled events enable maker/taker identity recovery.

```python
from web3 import Web3

CLOB_CONTRACT = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
ORDER_FILLED_TOPIC = "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"

def index_clob_events(from_block: int, to_block: int) -> List[dict]:
    """Fetch OrderFilled events from CLOB contract."""
    w3 = Web3(Web3.HTTPProvider(os.getenv('POLYGON_RPC')))
    
    logs = w3.eth.get_logs({
        'address': CLOB_CONTRACT,
        'topics': [ORDER_FILLED_TOPIC],
        'fromBlock': from_block,
        'toBlock': to_block
    })
    
    trades = []
    for log in logs:
        decoded = decode_order_filled_event(log)
        trades.append({
            'maker': decoded['maker'],
            'taker': decoded['taker'],
            'block': log['blockNumber'],
            'timestamp': get_block_timestamp(log['blockNumber']),
            'amount': decoded['makerAmountFilled'],
            'price': compute_price(decoded)
        })
    
    return trades
```

---

## PARQUET + DUCKDB MIGRATION (Week 3)

**Why**: 100x faster aggregation queries, 10x smaller storage.

```python
import duckdb
import pandas as pd

def snapshot_trades_to_parquet(trades: List[Trade], date: datetime):
    df = pd.DataFrame([
        {
            'id': t.id,
            'timestamp': t.timestamp,
            'market_id': t.market_id,
            'price': t.price,
            'side': t.side,
            'size': t.size,
            'resolved': t.resolved,
            'outcome': t.outcome,
            'pnl': t.pnl,
            'role': t.role.value
        }
        for t in trades
    ])
    
    path = f"data/trades/{date.strftime('%Y-%m-%d')}.parquet"
    df.to_parquet(path, compression='snappy', index=False)

# Fast backtest queries
def backtest_maker_advantage_by_category(category: str):
    con = duckdb.connect()
    
    result = con.execute(f"""
        SELECT 
            DATE_TRUNC('day', timestamp) AS date,
            role,
            AVG(pnl / (price * size)) AS roi,
            COUNT(*) AS trades
        FROM 'data/trades/2026-*.parquet'
        WHERE category = '{category}'
          AND resolved = true
        GROUP BY date, role
        ORDER BY date DESC
    """).df()
    
    return result
```

---

## TEMPORAL STRATEGY ROUTING (Week 4)

```python
def get_hour_of_day_strategy_weight(hour_et: int) -> dict:
    """Route capital by time of day based on historical data."""
    
    HOURLY_EDGES = {
        9: {'maker_edge': 0.035, 'retail_activity': 'high'},
        10: {'maker_edge': 0.032, 'retail_activity': 'high'},
        14: {'maker_edge': 0.018, 'retail_activity': 'low'},
        23: {'maker_edge': 0.008, 'retail_activity': 'very_low'},
    }
    
    if hour_et in HOURLY_EDGES:
        return HOURLY_EDGES[hour_et]
    
    return {'maker_edge': 0.02, 'retail_activity': 'medium'}
```

---

## SUCCESS METRICS

| Feature | Metric | Baseline | Target | Timeline |
|---------|--------|----------|--------|----------|
| Maker/Taker Tracking | Edge differential | Unknown | +2% maker vs -1% taker | Week 2 |
| Calibration Feedback | Model accuracy improvement | ~52% | ~54% | Week 3 |
| Longshot Signal | Selective trade ROI | N/A | +1-2% on signal trades | Week 1 |
| Blockchain Indexing | Event gap detection | N/A | <5 trades gap vs Data API | Week 4 |
| Parquet Backtest | Query speed | ~5s per query | <100ms per query | Week 3 |
| Temporal Routing | Hour-of-day alpha | N/A | +1% on high-retail hours | Week 4 |

---

## EXECUTION PRIORITY

1. **Week 1**: Maker/Taker classification + Longshot bias signal
2. **Week 2**: Price bucket calibration tracking
3. **Week 3**: Parquet migration + blockchain indexing (parallel)
4. **Week 4**: Temporal routing + category models

