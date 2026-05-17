# Trading History & Analysis — PolyEdge Wallet

**Wallet**: `0xad85c2f3942561afa448cbbd5811a5f7e2e3c6bd`
**Analysis Date**: 2026-05-17
**Data Source**: Polymarket Data API (`/activity` endpoint)
**Total Records**: 2,715 (2,427 trades + 280 redeems + 8 maker rebates)

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Total Spent | $19,660.06 |
| Total Redeemed | $18,242.32 |
| **Net P&L** | **-$1,417.75** |
| Markets Traded | 449 |
| Open Positions Value | $691.36 |
| Profile P&L (Polymarket) | -$86.14 |
| Trading Period | Apr 16 — May 17, 2026 |

---

## Daily P&L (On-Chain)

| Date | Trades | Redeems | Spent | Redeemed | Net |
|------|--------|---------|-------|----------|-----|
| 2026-04-16 | 22 | 0 | $33.20 | $0.00 | -$33.20 |
| 2026-04-17 | 16 | 2 | $15.52 | $14.63 | -$0.90 |
| 2026-04-18 | 0 | 2 | $0.00 | $5.00 | +$5.00 |
| 2026-04-20 | 0 | 3 | $0.00 | $10.23 | +$10.23 |
| 2026-04-22 | 0 | 24 | $0.00 | $0.00 | $0.00 |
| 2026-04-26 | 180 | 26 | $643.58 | $721.79 | +$78.21 |
| 2026-04-27 | 0 | 1 | $0.00 | $0.00 | $0.00 |
| 2026-05-01 | 26 | 8 | $163.00 | $260.43 | +$97.43 |
| 2026-05-02 | 20 | 3 | $240.62 | $104.36 | -$136.26 |
| 2026-05-03 | 40 | 6 | $277.05 | $258.99 | -$18.06 |
| 2026-05-08 | 112 | 20 | $1,222.75 | $1,346.95 | +$124.20 |
| 2026-05-09 | 0 | 1 | $0.00 | $9.84 | +$9.84 |
| 2026-05-12 | 277 | 77 | $1,753.21 | $2,071.07 | +$317.86 |
| 2026-05-13 | 116 | 22 | $1,924.45 | $2,263.36 | +$338.90 |
| **2026-05-14** | **255** | **24** | **$2,887.25** | **$1,909.12** | **-$978.13** |
| **2026-05-15** | **708** | **43** | **$5,512.71** | **$5,016.13** | **-$496.58** |
| **2026-05-16** | **331** | **3** | **$1,475.59** | **$802.93** | **-$672.66** |
| 2026-05-17 | 324 | 15 | $3,511.13 | $3,447.49 | -$63.64 |
| **TOTAL** | **2,427** | **280** | **$19,660.06** | **$18,242.32** | **-$1,417.75** |

### Key Observations

- **Profitable period**: Apr 26 — May 13 (net +$1,038)
- **Disaster period**: May 14-16 (net -$2,148 in 3 days)
- **May 17**: Calmed down, only -$64 loss
- **Profile P&L** (-$86) differs from on-chain net (-$1,418) because profile includes open position value ($691)

---

## Dual-Side Betting Analysis

The bot frequently buys BOTH Up AND Down on the same market in the same time window.

| Type | Markets | Spent | % of Total |
|------|---------|-------|------------|
| Single-side | 354 | $11,044 | 56.2% |
| **Dual-side** | **103** | **$8,616** | **43.8%** |

### Why This Loses

On a binary market (Up/Down), buying both sides means:
- One side wins, one side loses
- Net = win_payout - (up_cost + down_cost)
- Since market prices sum to ~$1.00, the house edge + fees guarantee a loss
- **Dual-side betting is guaranteed negative EV**

### Example: BTC 5-min May 17, 10:30-10:35AM

- Bought Up: 14x, cost ~$270
- Bought Down: 19x, cost ~$263
- Total committed: $533
- One side redeems ~$477 (93.45 tokens)
- Net loss: ~$56 per window

---

## Category Breakdown

### BTC 5-Minute Markets

| Metric | Value |
|--------|-------|
| Trades | 1,346 |
| Spent | $15,693.88 |
| Redeemed | $15,683.45 |
| Net | -$10.43 |
| Pattern | Dual-side (both Up and Down) |

**Analysis**: BTC 5-min is 80% of all spending. Net is nearly flat (-$10) because dual-side betting cancels out — but wastes gas, fees, and capital allocation. The bot has ZERO edge on these markets.

### Eurovision Markets

| Metric | Value |
|--------|-------|
| Trades | 123 |
| Spent | $473.18 |
| Redeemed | $480.45 |
| Net | +$7.27 |
| Markets | Bulgaria win, Finland top 3/5 |

**Analysis**: Small profitable edge. Bulgaria win bet ($50) paid $430 on redeem. Finland bets were micro-stakes ($0.05 each) — 84 trades for $4.70 total, noise.

### Esports (LoL, Dota)

| Metric | Value |
|--------|-------|
| Trades | 132 |
| Spent | $21.94 |
| Redeemed | $0.00 |
| Net | -$21.94 |

**Analysis**: All micro-stakes ($0.05 each). HLE vs KT Rolster, JD Gaming, PARIVISION. No redeems yet — may be pending resolution or losses.

### Political Markets

| Metric | Value |
|--------|-------|
| Trades | 199 |
| Spent | $338.22 |
| Pattern | Trump/Xi "Will Trump say Iran/Nuclear/Strait" |

**Analysis**: 199 small buys on Trump/Xi word markets. $1-$5 each. If Trump said those words, pays out. If not, total loss.

### Sports

| Metric | Value |
|--------|-------|
| Trades | 42 |
| Spent | $98.99 |
| Markets | Rangers/Astros O/U, Orioles/Nationals, Sinner/Medvedev, Chelsea/ManCity |

**Analysis**: Mixed results. Tennis (Sinner vs Medvedev) had $77 in buys. Baseball O/U had micro-stakes.

### Other Notable Markets

| Market | Trades | Spent | Notes |
|--------|--------|-------|-------|
| MrBeast video views | 5 | $96.50 | Binary bet on view count |
| BTC reach $81k May 17 | 8 | $15.10 | Small directional bet |
| ETH above $2,200 | ~30 | $15 | Micro-stakes DCA |
| Hantavirus US | ~15 | $350 | Binary bet |
| Elon Musk tweet count | ~10 | $40 | Range bet |

---

## Biggest Single-Day Losses

### May 14: -$978.13

- Spent $2,887 on 255 trades
- Only $1,909 redeemed
- **Cause**: Aggressive dual-side BTC 5-min betting at scale

### May 16: -$672.66

- Spent $1,476 on 331 trades
- Only $803 redeemed
- **Cause**: Same pattern, high volume low edge

### May 15: -$496.58

- Spent $5,513 (highest volume day)
- $5,016 redeemed
- **Cause**: 708 trades, mostly dual-side BTC

---

## Biggest Single-Day Wins

### May 13: +$338.90

- $1,924 spent, $2,263 redeemed
- Good directional calls

### May 12: +$317.86

- $1,753 spent, $2,071 redeemed
- Strong win rate

### Apr 26: +$78.21

- First significant trading day
- $644 spent, $722 redeemed

---

## Root Causes of Losses

### 1. Dual-Side Betting (43.8% of spending)

The bot buys both Up AND Down on the same 5-minute BTC market. This is guaranteed negative EV — one side always loses. Across 103 markets, $8,616 committed with near-zero net return.

**Fix**: Block same-market opposite-direction trades in duplicate guard.

### 2. Zero Edge on BTC 5-Min

`crypto_oracle.py` edge calculation always returns 0:
```python
edge = abs(oracle_implied - market_mid) - min_edge
# oracle_implied = market_mid + min_edge
# edge = abs(min_edge) - min_edge = 0
```

With zero edge, direction selection is random (momentum flip). Result: coin-flip betting.

**Fix**: Compute real edge from BTC spot price vs market strike.

### 3. model_probability = 1.0/0.0

`crypto_oracle.py:804` sets absolute certainty:
```python
"model_probability": 1.0 if direction == "yes" else 0.0
```

Kelly sizing with p=1.0 = maximum bet every time. No risk scaling.

**Fix**: Use bounded probability estimate (0.05-0.95).

### 4. No Per-Market Position Cap

Bot can open 20+ positions on the same market across multiple 5-min windows. Today's data shows 38x on a single market (2273697 down).

**Fix**: Max 1 position per market event.

### 5. Finland/Eurovision DCA Spam

84 micro-trades ($0.05 each) on Finland Eurovision markets. Bot DCA-ing into a market that likely already resolved. Wasted gas and attention.

**Fix**: Skip markets within 1 hour of resolution.

---

## Strategy Performance (On-Chain)

| Category | Trades | Spent | Net | Assessment |
|----------|--------|-------|-----|------------|
| BTC 5-min | 1,346 | $15,694 | -$10 | Zero edge, wasted capital |
| Eurovision | 123 | $473 | +$7 | Small edge, good |
| Esports | 132 | $22 | -$22 | Noise, no edge |
| Political | 199 | $338 | TBD | Pending resolution |
| Sports | 42 | $99 | TBD | Mixed |
| Other | 585 | $3,034 | TBD | Mixed |

---

## Recommendations

### Immediate (P0)

1. **Fix duplicate guard** — Block same-market trades (any direction) within 5 min
2. **Fix edge calculation** — `crypto_oracle.py:696` and `universal_scanner.py:387`
3. **Cap positions** — Max 1 per market event
4. **Fix model_probability** — Use bounded estimates

### Short-term (P1)

5. **Kill btc_oracle** — 40% WR, -$1,251 lifetime. Already auto-killed once.
6. **Reduce BTC 5-min exposure** — Even with fixed edge, 5-min markets are noise
7. **Add stale-market filter** — Skip markets <1h to resolution

### Medium-term (P2)

8. **Implement real edge computation** — BTC spot vs market strike distance
9. **Add position concentration limits** — Max $X per market category
10. **Build backtesting pipeline** — Validate strategies before live

---

## Data Files

- `daily_pnl.csv` — Daily P&L breakdown
- `market_analysis.csv` — Per-market trade analysis
- `dual_side_markets.csv` — Markets with dual-side betting
- This file — `README.md`
