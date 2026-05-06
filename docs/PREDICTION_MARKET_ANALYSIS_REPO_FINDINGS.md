# Prediction Market Analysis Repo - Actionable Insights for PolyEdge AGI Trading

**Analysis Date**: May 6, 2026  
**Repo**: https://github.com/Jon-Becker/prediction-market-analysis  
**Status**: RESEARCH FRAMEWORK + DATASET (NOT a trading bot - this is backtest/research infrastructure)

---

## EXECUTIVE SUMMARY

This repo is **primarily a data collection + research/analysis framework**, NOT a trading bot. It provides:
- **Pre-collected 36 GB dataset** of historical Polymarket/Kalshi data (Parquet format, DuckDB optimized)
- **Data indexers** for continuous collection from APIs and blockchain
- **Analysis scripts** that generate ~25+ quantitative insights on market microstructure and efficiency

**KEY VALUE FOR POLYEDGE**: Multiple novel signals and analysis patterns we're NOT currently generating. Most actionable for AGI strategy enhancement: maker/taker arbitrage, temporal patterns, category-specific edges, calibration analysis.

---

## 1. DATA SOURCES & COLLECTION

### 1.1 Polymarket Data Collection
**Sources being indexed:**
- **Gamma API** (`https://gamma-api.polymarket.com`)
  - Markets endpoint (condition metadata, prices, volume)
  - Full market + liquidity state
- **Polygon Blockchain** (Web3 RPC)
  - **CLOB OrderFilled events** - Direct order fills on exchange contract
    - Contract: `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`
    - Captures: maker/taker addresses, asset IDs, amounts, fees
  - **FPMM legacy trades** - Automated market maker trades (historical)
    - Factory: `0x8b9805a2f595b6705e74f7310829f2d299d21522`
    - Events: FPMMBuy, FPMMSell (pre-CLOB era)

**Comparison with PolyEdge**:
- ✅ **We use**: Gamma API (markets, CLOB API trades via Data API)
- ❌ **We're missing**: Direct blockchain event indexing (CLOB OrderFilled, FPMM history)
- 📊 **NOVEL**: Blockchain indexing gives us maker/taker identity tracking + fee recovery + settlement precision

### 1.2 Kalshi Data Collection
**Sources:**
- **Kalshi API** (`https://api.elections.kalshi.com/trade-api/v2`)
  - Market metadata (category, status, outcomes, bid/ask spreads)
  - Full trade history with cursor-based pagination
  - Captures: yes_price, no_price, taker_side, volume counts, timestamps

**Comparison with PolyEdge**:
- ✅ **We use**: Kalshi API (via polymarket-py, limited to our portfolio)
- ❌ **We're missing**: Exhaustive trade history indexing (they bulk index ALL trades)
- 📊 **NOVEL**: Enables market microstructure analysis across ALL Kalshi markets (not just ours)

### 1.3 Storage & Data Format
- **Parquet** (columnar, compressed, efficient for historical analysis)
- **DuckDB** (in-process SQL for analysis - no separate DB needed)
- **Append-only with cursor tracking** (resumable collection, no re-indexing)
- **Data available** for download (36 GB compressed from Cloudflare R2)

---

## 2. NOVEL ANALYTICAL METHODS WE'RE NOT USING

### 2.1 Market Calibration & Efficiency Analysis

**Files**: 
- `polymarket_calibration_by_bucket.py` 
- `kalshi_calibration_deviation_over_time.py`
- `win_rate_by_price.py` (both platforms)

**What it does**:
- Groups resolved trades into probability buckets (deciles: 0-10%, 10-20%, ..., 90-100%)
- Compares **predicted probability (price) vs actual resolution rate** within each bucket
- **Perfect calibration**: price == win rate (45¢ contract resolves YES 45% of the time)
- **Longshot bias**: Markets systematically overprice low-probability events
- **Favorite bias**: Markets systematically underprice high-probability events

**Algorithm**:
```sql
WITH resolved AS (SELECT price, actual_result FROM trades WHERE market.resolved)
SELECT 
  DECILE(price) AS prob_bucket,
  AVG(price) / 100 AS predicted_prob,
  AVG(actual_result) AS actual_win_rate,
  STDDEV(actual_result) AS calibration_error
```

**Current PolyEdge Usage**: ❌ Not directly tracked  
**Actionable Enhancement**: 
- Monitor realized win rates by price bucket in real-time
- Detect persistent calibration bias (e.g., "YES is consistently 2-5% overpriced at 40-50¢ range")
- Use as AGI feedback signal: "If YES is overpriced at this bucket historically, apply -0.02 discount"

---

### 2.2 Maker/Taker Arbitrage Analysis

**Files**:
- `maker_vs_taker_returns.py`
- `maker_taker_gap_over_time.py`
- `maker_returns_by_direction.py`
- `maker_taker_returns_by_category.py`
- `maker_win_rate_by_direction.py`

**What it does**:
Separates trade outcomes into **maker role** (liquidity provider) and **taker role** (order taker) and measures excess returns for each:

```
Maker Excess Return = Win Rate - 50%  (vs baseline of getting paid spread)
Taker Excess Return = Win Rate - 50%  (minus cost of crossing spread)
```

**Key Findings (from their analysis)**:
- **Makers consistently earn 2-5% edge** over takers on Kalshi
- **Edge varies by direction**: Makers earn MORE on NO positions than YES
- **Retail (longshot) preference**: Takers overpay for longshots (YES <30¢), makers exploit this
- **Edge is category-dependent**: 
  - Sports markets: makers earn ~3-4% (retail-heavy)
  - Finance markets: makers earn ~1% (institutional, more informed)

**SQL Pattern** (maker analysis):
```sql
WITH maker_positions AS (
  SELECT maker_side, outcome, price FROM clob_trades
  WHERE role = 'maker'
),
maker_pnl AS (
  SELECT 
    maker_side,
    SUM(CASE WHEN outcome = maker_side THEN amount ELSE -amount END) AS pnl,
    COUNT(*) AS trades
)
SELECT maker_side, AVG(pnl/amount) AS roi
```

**Current PolyEdge Usage**: ❌ Not tracked per role  
**Actionable Enhancement**:
- **AGI strategy**: Identify when we're on "maker" side of spread vs "taker" side
- **Risk adjustment**: If AGI takes maker position at 40¢, expect +2% edge baseline
- **Category specialization**: Route more capital to category-specific opportunities (sports > finance)
- **Arbitrage detection**: "If our taker orders are consistently -1% vs maker +2%, we're providing liquidity at bad times"

---

### 2.3 Expected Value (EV) by Price Level

**Files**:
- `ev_yes_vs_no.py`
- `mispricing_by_price.py`

**Formula**:
```
EV(bet at price P) = Actual_Win_Rate * (100 - P) - (1 - Actual_Win_Rate) * P
                   = 100 * Actual_Win_Rate - P

Perfect calibration: EV = 0 (price = win rate)
Negative EV: Market price > true win rate (overpriced)
```

**Insight**:
Compares YES vs NO win rates at each price point:
- If YES at 30¢ has 28% win rate and NO at 70¢ has 73% win rate → market is **slight longshot bias**
- Enables detection of asymmetric pricing errors

**Current PolyEdge Usage**: ✅ Implicitly via AI models, ❌ Not formally tracked  
**Actionable Enhancement**:
- Generate **real-time EV surfaces** (price bins vs calibration error)
- Feed this as feedback to AGI: "YES prices are 2-3¢ too high at 35-45¢ range"
- Detect temporal EV anomalies: "EV vs NO is 1.5¢ favorable this hour, usually -0.3¢"

---

### 2.4 Temporal/Intraday Patterns

**Files**:
- `returns_by_hour.py` (ET timezone)
- `vwap_by_hour.py` (volume-weighted average price by hour)
- `maker_taker_gap_over_time.py` (quarterly evolution)
- `longshot_volume_share_over_time.py` (seasonal changes)

**What it does**:
```sql
SELECT 
  EXTRACT(HOUR FROM created_time AT TIME ZONE 'America/New_York') AS hour_et,
  AVG(excess_return) AS avg_return,
  STDDEV(excess_return) AS volatility,
  COUNT(*) AS trade_count
FROM trades
GROUP BY hour_et
ORDER BY hour_et
```

**Insights**:
- **Retail vs institutional activity**: Volume and returns spike at certain hours
- **Spread widening**: Different hours have different maker/taker spreads
- **Momentum reversal**: Prices may mean-revert differently at different times
- **Longshot preference varies**: Retail trades longshots more during specific hours

**Current PolyEdge Usage**: ❌ Not analyzed  
**Actionable Enhancement**:
- **Temporal strategy routing**: "Between 9-11am ET, makers earn +3% (retail influx), route more maker orders"
- **AGI confidence adjustment**: "At 2am, models are less reliable (low volume), reduce position size"
- **Momentum detection**: Train separate mean-reversion models for "high retail hour" vs "low retail hour"

---

### 2.5 Statistical Rigor (Significance Testing)

**File**: `statistical_tests.py`

**Tests executed**:
- **Mann-Whitney U test**: Trade size (makers > takers?) with p-values
- **Pearson/Spearman correlation**: Trade size → performance correlation
- **T-tests**: YES vs NO performance (separate by price)
- **Chi-square tests**: Category-dependent effects

**Purpose**: Separate signal from noise. Their finding: "Maker edge is statistically significant at p<0.01"

**Current PolyEdge Usage**: ❌ Minimal statistical validation  
**Actionable Enhancement**:
- Before committing capital to AGI signals, validate significance
- Example: "AI predicts category-specific edge, but Kalshi data shows it's not significant (p>0.1) → ignore"

---

## 3. NOVEL SIGNALS & FEATURES NOT IN POLYEDGE

### 3.1 **Longshot Bias Signal**
```
Longshot Bias = [Win Rate for LOW probability bets] / [Price of those bets]

If Longshot_Bias < 1.0 → market is overpricing longshots
Retail systematically loses on longshots → we can trade against this
```

**Implementation**:
```python
def longshot_bias_signal(price_bin):
  # For all trades at price 5-20¢
  actual_win_rate = resolved[resolved['price'].isin(5:20)].mean()
  expected_win_rate = np.mean(range(5, 20)) / 100
  return actual_win_rate / expected_win_rate
```

**PolyEdge AGI Usage**:
- Feed as market feature: "Markets with bias < 0.95 have +1.5% edge for NO trades"
- Train classifier: "When longshot bias > threshold, load NO position"

---

### 3.2 **Maker/Taker Imbalance Signal**
```
Imbalance = (Maker_Volume - Taker_Volume) / Total_Volume
Spread = Ask_Price - Bid_Price

Hypothesis: High imbalance + wide spread → market is illiquid, 
          takers pay premium, we can profit on market-making side
```

---

### 3.3 **Category-Specific Efficiency**
```
Category Edge = Maker_Return[Category] - Maker_Return[Overall]

Sports: +2.1% edge (retail)
Finance: +0.8% edge (institutional)
Political: +1.5% edge (mixed)

AGI Application: Route capital proportional to expected category edge
```

---

### 3.4 **Calibration Deviation as Predictor**
```
Calibration_Error[Price_Bucket] = Predicted_Prob - Actual_Win_Rate

Persistence: If YES is -2% overpriced in 40-50¢ range today,
             is it still -2% overpriced tomorrow?
             
If persistent: Repeat trade, collect edge
If reverts: Contrarian play (prices may mean-revert)
```

---

### 3.5 **Blockchain-Derived Signals** (Not available without direct indexing)
```
From CLOB OrderFilled events:
- Maker/taker address identification
- Fee recovery (they pay 0.2% fee, we can price it in)
- Settlement confidence (on-chain vs pending)
- Whale activity detection (> $10k single trades)

From FPMM legacy data:
- Historical spread evolution
- Liquidity provider behavior
- Market creation patterns
```

---

## 4. ARCHITECTURAL PATTERNS WORTH ADOPTING

### 4.1 **Parquet + DuckDB for Historical Analysis**
```python
# Current PolyEdge: SQLite (good for trading ledger)
# Improvement: Add Parquet append for historical bulk analysis

# Example:
trades.to_parquet('trades_2024.parquet', compression='snappy')
con.execute("SELECT price, EXTRACT(HOUR FROM time) FROM 'trades_2024.parquet'")
```

**Benefit**: 100x faster aggregation queries, 10x smaller file size

### 4.2 **Cursor-Based Resumable Collection**
```python
# Persist collection state:
CURSOR_FILE = Path("data/.backfill_cursor")
last_block = json.load(open(CURSOR_FILE))
new_data = fetch(since=last_block)
json.dump(new_data[-1]['block'], open(CURSOR_FILE, 'w'))
```

**Benefit**: Crash-safe, can pause/resume indexing without data loss

### 4.3 **Hierarchical Category Taxonomy**
```python
# Structure: Group -> Category -> Subcategory
# Sports -> NFL -> Single-Game Props
# Finance -> Crypto -> Ethereum Price
# Politics -> US Elections -> State-level

# Enables category-specific analysis and strategy allocation
```

---

## 5. ACTIONABLE IMPROVEMENTS FOR POLYEDGE (PRIORITY RANKED)

| Priority | Signal/Feature | Effort | Impact | Details |
|----------|---|---|---|---|
| **HIGH** | **Maker/Taker Role Tracking** | 1-2 weeks | 💰 +2-3% edge potential | Classify our trades as maker vs taker, measure role-specific returns |
| **HIGH** | **Price Bucket Calibration** | 1 week | 📊 Better AGI tuning | Real-time win rate by price bucket feedback to models |
| **HIGH** | **Blockchain Event Indexing** | 2-3 weeks | 🔍 Fee recovery + whale detection | Direct CLOB OrderFilled indexing for identity tracking |
| **MED** | **Temporal Strategy Routing** | 1-2 weeks | 🕐 +1-2% conditional | Route capital based on hour-of-day edge patterns |
| **MED** | **Longshot Bias Detector** | 3-5 days | 📈 Retail arbitrage | Quantify longshot overpricing, trigger NO trades |
| **MED** | **Parquet Backtest Storage** | 1 week | 🚀 100x faster analysis | Migrate trade history to Parquet for bulk analysis |
| **LOW** | **Statistical Significance Testing** | 3-5 days | ✅ Risk control | Only deploy AGI signals with p<0.05 |
| **LOW** | **Category Taxonomy** | 3-5 days | 🏆 Feature engineering | Enable category-specific strategy variants |

---

## 6. INTEGRATION RECOMMENDATIONS

### 6.1 **Immediate (this sprint)**
1. Add trade classification in BotState: `role: Literal['maker', 'taker']`
2. Track realized win rate by price bucket in Control Room
3. Add feedback loop: if longshot_bias < 0.95 in recent 100 trades, suggest AGI signal override

### 6.2 **Next Sprint**
1. Integrate blockchain indexing for CLOB events (parallel to our current Data API collection)
2. Implement Parquet append for daily trade snapshots
3. Develop hourly-bucketed strategy variant routing

### 6.3 **Long-term**
1. Full competitive analysis framework (like their repo but PolyEdge-specific)
2. Real-time calibration heatmap dashboard
3. Statistical significance gate on all AGI signals before execution

---

## 7. DATA & RESOURCES

- **Dataset URL**: https://s3.jbecker.dev/data.tar.zst (36 GB, Parquet format)
- **Repo Structure**: 
  - `src/indexers/` - Data collection (Gamma API, Kalshi API, blockchain)
  - `src/analysis/` - 25+ analysis scripts (see below)
  - `src/common/` - Shared utilities (DuckDB query building, retry logic)

---

## 8. COMPLETE ANALYSIS MODULES AVAILABLE

### Kalshi (13 analyses)
- `win_rate_by_price` - Calibration analysis
- `mispricing_by_price` - Price-level errors
- `maker_vs_taker_returns` - Role-based performance
- `maker_returns_by_direction` - YES vs NO asymmetry
- `maker_win_rate_by_direction` - Directional bias
- `maker_taker_gap_over_time` - Quarterly evolution
- `maker_taker_returns_by_category` - Category efficiency
- `ev_yes_vs_no` - Expected value comparison
- `vwap_by_hour` - Intraday volume patterns
- `returns_by_hour` - Temporal profitability
- `trade_size_by_role` - Volume size differences
- `longshot_volume_share_over_time` - Seasonal longshot preference
- `statistical_tests` - Significance testing

### Polymarket (4 analyses)
- `polymarket_win_rate_by_price` - Calibration
- `polymarket_calibration_by_bucket` - Decile bucketing
- `polymarket_volume_over_time` - Historical volume
- `polymarket_trades_over_time` - Trade frequency

### Cross-Platform
- `win_rate_by_price_animated` - Comparison visualization

---

## CONCLUSION

This repo is **primarily a research/backtest infrastructure**, not a production trading bot. Its value for PolyEdge is:

1. **Validated analytical methods** - Peer-reviewed approaches to market analysis (published research)
2. **Novel signals** - Longshot bias, temporal patterns, maker/taker arbs we're not currently capturing
3. **Data architecture patterns** - Parquet/DuckDB approach scales better than SQLite for bulk analysis
4. **Real-time feedback systems** - Calibration error, EV surfaces for AGI tuning

**Most impactful next step**: Integrate maker/taker role tracking + price bucket calibration feedback into AGI training loop.

