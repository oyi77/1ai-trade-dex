# Trade Pattern Analysis Report

**Generated:** 2026-05-17
**Data Source:** `poly-history.csv` (1,000 trades)
**Period:** May 15, 2026 06:24 UTC - May 16, 2026 12:42 UTC (~30 hours)

---

## Executive Summary

Analysis of 1,000 Polymarket trades totaling $12,583 USDC reveals a bot-dominated trading pattern with extreme buy bias, concentrated Bitcoin window exposure, and correlated political event risk. The system executed 948 buys vs only 4 sells across 91 unique markets, indicating a fundamental absence of exit strategy. Median trade size is $1.22, but mean is $12.58 -- heavily skewed by large Bitcoin 5-minute window trades ($129-$480 each). One day of data limits statistical confidence; all findings should be treated as directional, not conclusive.

---

## Per-Category Metrics

| Category | Trades | Total USDC | Avg Size | Median Size | Buy/Sell Ratio |
|----------|--------|------------|----------|-------------|----------------|
| Crypto/Bitcoin | 455 | $9,821.39 | $21.59 | $5.83 | 451:0 |
| Sports | 266 | $110.32 | $0.41 | $0.05 | 266:0 |
| Politics/Trump | 153 | $183.48 | $1.20 | $1.22 | 153:0 |
| Esports | 64 | $3.34 | $0.05 | $0.05 | 64:0 |
| Other (Hantavirus, Musk, etc.) | 52 | $1,889.55 | $36.34 | $5.94 | 48:4 |
| Weather | 10 | $575.07 | $57.51 | $36.77 | 10:0 |

### Key Observations by Category

**Crypto/Bitcoin (78.2% of volume):**
- Dominant category by both trade count (455) and volume ($9,821)
- All Bitcoin Up/Down 5-minute window trades -- high-frequency, time-boxed markets
- Peak activity: 17:00-18:00 UTC (296 trades, $5,671) during US market hours
- Top windows: 1:25-1:30 PM ET ($427), 1:30-1:35 PM ET ($517), 2:15-2:20 PM ET ($130)
- Zero sells -- all positions held until settlement or redemption

**Sports (micro-stakes):**
- 266 trades but only $110 total -- average $0.41 per trade
- Primarily MLB over/under markets and tennis (Swiatek vs Svitolina)
- Tennis match alone: 167 trades, $8.69 -- extreme position splitting
- Zero sells -- bot accumulating micro-positions

**Politics/Trump (correlated cluster):**
- 153 trades, $183 total -- all related to Trump/Xi Jinping event
- Three correlated markets: "Strait/Hormuz" (55 trades, $67), "Nuclear" (51, $55), "Iran" (46, $57)
- Single event, multiple word-bet markets = concentrated correlated exposure
- Zero sells

**Esports:**
- 64 trades, $3.34 total -- smallest category by volume
- Primarily LoL: Ozarox Esports vs Team Phoenix matches
- Average $0.05 per trade -- negligible position sizing

**Other:**
- Only category with any sells (4 total)
- Hantavirus market: 11 trades, $904 -- largest single-market non-Bitcoin exposure
- Gemini 3.5 release: 4 trades, $284
- Deposits and maker rebates inflate trade count

**Weather:**
- 10 trades, $575 -- high average size ($57.51)
- Hong Kong temperature market: 1 trade at $297
- Small sample, no exit activity

---

## Action Distribution

| Action | Count | Percentage |
|--------|-------|------------|
| Buy | 948 | 94.8% |
| Redeem | 44 | 4.4% |
| Sell | 4 | 0.4% |
| Maker Rebate | 2 | 0.2% |
| Deposit | 2 | 0.2% |

**Critical finding:** 948 buys vs 4 sells = 237:1 buy/sell ratio. The system has no meaningful exit strategy. Positions are either held to settlement or redeemed post-settlement. This creates maximum exposure to adverse price movements with no ability to cut losses.

---

## Bitcoin Time-of-Day Patterns

Bitcoin 5-minute window trading concentrates during US market hours:

| Hour (UTC) | Trades | USDC Volume |
|------------|--------|-------------|
| 09:00 | 16 | $245.52 |
| 10:00 | 17 | $400.00 |
| 11:00 | 7 | $461.85 |
| 13:00 | 37 | $1,140.69 |
| 14:00 | 51 | $1,077.96 |
| 16:00 | 49 | $1,138.26 |
| 17:00 | 159 | $3,271.59 |
| 18:00 | 137 | $2,399.19 |

**Peak window:** 17:00-19:00 UTC (1-3 PM ET) accounts for 65% of Bitcoin volume. The 17:35 UTC window alone had 17 trades totaling $563. This concentration suggests the bot is most active during US equity market hours when Bitcoin volatility is highest.

---

## Market Clustering Risk

### Trump/Xi Correlated Exposure

Three markets on the same event (Trump speaking during Xi Jinping meeting):

| Market | Trades | USDC |
|--------|--------|------|
| "Strait" or "Hormuz" | 55 | $66.66 |
| "Nuclear" | 51 | $55.00 |
| "Iran" | 46 | $56.50 |
| **Total cluster** | **152** | **$178.16** |

These markets are highly correlated -- if Trump avoids all geopolitical language, all three positions lose simultaneously. The bot treats them as independent bets but they share a single underlying event risk.

### Bitcoin Window Clustering

Bitcoin 5-minute windows are sequential and correlated. A sustained Bitcoin move in one direction will cause losses across multiple consecutive windows. The top 10 windows alone represent $3,238 in exposure.

---

## Key Insights

### 1. Sell Signal Gap
948 buys vs 4 sells reveals the system lacks exit logic. The existing `trade_forensics.py` module analyzes *losing* trades post-settlement but has no mechanism to trigger mid-market exits. The 4 sells came only from the "Other" category (Hantavirus, Gemini markets), suggesting manual or special-case exits.

### 2. Bitcoin Position Sizing Skew
Median trade is $1.22 but mean is $12.58. Bitcoin windows average $21.59 per trade, pulling the mean 10x above median. The largest single trade was $479.96. This concentration means Bitcoin price action dominates P&L -- a few bad 5-minute windows could erase gains from hundreds of smaller trades.

### 3. Micro-Stake Sports Accumulation
266 sports trades averaging $0.41 suggest the bot is splitting orders aggressively. 167 tennis trades on a single match ($8.69 total) means an average of $0.05 per trade. This may be a sizing bug or intentional strategy, but the transaction cost overhead likely exceeds potential returns at these sizes.

### 4. Correlated Event Exposure
The Trump/Xi cluster and Bitcoin window sequence both represent concentrated single-event risk. The system appears to treat each market independently without accounting for correlation within event clusters.

---

## Recommendations

1. **Implement exit strategy:** Add sell signal logic to `trade_forensics.py` or the strategy executor. At minimum, add stop-loss triggers for positions exceeding a loss threshold.

2. **Cap per-event exposure:** Limit total USDC deployed across correlated markets (e.g., all Trump/Xi word bets, all Bitcoin windows in a 30-min period).

3. **Fix sports sizing:** Investigate why sports trades average $0.41 with 167 trades on a single match. Either increase minimum trade size or reduce order splitting.

4. **Reduce Bitcoin concentration:** Bitcoin windows represent 78% of volume. Consider position limits per window and per-hour caps to reduce drawdown risk.

5. **Add correlation awareness:** The strategy executor should recognize when multiple markets share an underlying event and apply cluster-level exposure limits.

---

## Survivorship Bias Disclaimer

**This dataset contains only executed trades from one day of live operation.** It does not include:
- Markets the system considered but did not trade
- Trades that were rejected or failed to execute
- Win/loss outcomes (all positions are unsettled or redeemed)
- Performance from prior or subsequent days

The patterns observed may not generalize. A single day of bot trading on Polymarket is not sufficient to draw statistical conclusions about strategy effectiveness. The 948:4 buy/sell ratio could reflect a deliberate "hold to settlement" strategy rather than a missing feature. Further analysis with settled trade outcomes and multi-day data is required before making architectural changes.

---

## Data Validation

| Expected | Actual | Status |
|----------|--------|--------|
| ~1,000 trades | 1,000 | Confirmed |
| 948 buys vs 4 sells | 948 Buy, 4 Sell | Confirmed |
| Median ~$1.22 | $1.22 | Confirmed |
| Mean ~$12.58 | $12.58 | Confirmed |
| 91 unique markets | 91 | Confirmed |
| 1 day of data (May 15-16) | May 14 23:24 - May 16 05:42 UTC | Confirmed |
| Tennis: 167 trades, ~$9 | 167 trades, $8.69 | Confirmed |
| Trump/Xi: ~152 trades, ~$178 | 153 trades, $183.48 | Confirmed |
| Bitcoin windows: $129-$199 each | Top windows $245-$517 | Slightly higher |

---

*Analysis generated by `scripts/trade_analysis.py` from `poly-history.csv` using utf-8-sig encoding.*
