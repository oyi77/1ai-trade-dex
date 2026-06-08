# PolyEdge Paper Trading Performance Report
**Generated:** 2026-06-08 20:15 WIB

## Executive Summary

**Overall Status:** ⚠️ **PERFORMANCE CONCERNING — Review Needed**

- Paper trading shows a **-3,919 PnL** over 5,310 trades (28.3% win rate)
- Live trading at -$293.57 over 578 trades (46.7% win rate)
- Total **832,644 trade attempts** with only **2.7% execution rate**
- Most attempts blocked by risk controls (good) but performance is negative

---

## Performance Breakdown

### Overall Metrics
| Metric | Value |
|--------|-------|
| **Live Bankroll** | $18.71 (started at $6.88) |
| **Total P&L** | **-$293.57** |
| **Total Trades** | 578 (260 wins, 46.7% WR) |
| **Bot Running** | ❌ False (last ran May 26) |
| **Last Run** | 2026-05-26T13:42:42 |

### Per-Mode Performance
| Mode | Bankroll | Trades | Wins | Win Rate | PnL |
|------|----------|--------|------|----------|-----|
| **Paper** | $0.00 | 5,310 | 1,505 | 28.3% | **-$3,919.19** |
| **Live** | $18.71 | 578 | 260 | 46.7% | **-$293.57** |
| **Testnet** | $100.00 | 0 | 0 | — | $0.00 |

---

## Strategy Performance Leaderboard

### 🏆 Top Performers (Profitable)
| Strategy | Trades | Win % | PnL | Status |
|----------|--------|-------|-----|--------|
| **bond_scanner** | 399 | **80.9%** | **+$1,140.74** | ✅ Profitable |
| **longshot_bias** | 618 | **98.5%** | **+$717.46** | ✅ Profitable |
| **weather_emos** | 22 | 50.0% | +$197.81 | ✅ Profitable |

### 📉 Losing Strategies
| Strategy | Trades | Win % | PnL | Status |
|----------|--------|-------|-----|--------|
| news_frontrun | 7 | 42.9% | -$2.64 | ⚠️ Minor loss |
| cex_pm_leadlag | 249 | 49.0% | -$58.83 | ⚠️ Small loss |
| line_movement_detector | 256 | 89.8% | **-$424.90** | ❌ High WR but losses |
| crypto_oracle | 669 | 48.4% | **-$1,630.62** | ❌ Big loser |
| arb_scanner | 384 | 0.0% | **-$1,772.40** | ❌ Zero wins |
| **cross_platform_arb** | 100 | 0.0% | **-$2,493.22** | ❌ Worst loser |

### 🔍 Key Observations

1. **line_movement_detector** is interesting: 89.8% win rate but **loses $424.90**
   - Means: wins are small, losses are catastrophic (asymmetric payoffs)
2. **bond_scanner** is the best: 80.9% WR + $1,140 profit (best risk-adjusted)
3. **longshot_bias** has near-perfect 98.5% WR with $717 profit (high confidence bias)
4. **arb_scanner** & **cross_platform_arb** have ZERO wins — completely broken

---

## Trade Execution Analysis

### Trade Attempts (Total: 832,644)
- **Executed:** 22,284 (2.7%)
- **Blocked:** 809,550 (97.3%)
- **Execution rate very low** — most signals get filtered

### By Status
| Status | Count |
|--------|-------|
| REJECTED | 466,251 |
| BLOCKED | 304,205 |
| FAILED | 39,094 |
| EXECUTED | 22,284 |
| RISK_APPROVED | 810 |

### By Mode
| Mode | Count |
|------|-------|
| Paper | 516,037 |
| Live | 249,109 |
| Testnet | 67,498 |

### 🚫 Top Blockers (Why Most Trades Don't Execute)
| Reason | Count | % of Blocked |
|--------|-------|--------------|
| REJECTED_DRAWDOWN_BREAKER | 221,008 | 27.3% |
| BLOCKED_DUPLICATE_OPEN_POSITION | 187,792 | 23.2% |
| REJECTED_LOW_CONFIDENCE | 82,403 | 10.2% |
| BLOCKED_BOT_NOT_RUNNING | 48,755 | 6.0% |
| REJECTED_TRADE_VALIDATION | 43,083 | 5.3% |

**Good news:** 27% blocked by drawdown breaker = risk controls working
**Bad news:** Bot not running for 48,755 attempts = system issue

---

## Recent Activity (Live Feed)

**Last trade attempt:** 20:13:33 (2 min ago)
```
bond_scanner | paper | BLOCKED | BUY | $0.135 @ 90% confidence
bond_scanner | live  | BLOCKED | BUY | $0.028 @ 99% confidence  
bond_scanner | paper | BLOCKED | BUY | $0.023 @ 99% confidence
```

**Status:** Strategies are generating signals, but most are blocked by:
- `BLOCKED_COOLDOWN`: 3 consecutive losses, 432min remaining
- `BLOCKED_BOT_NOT_RUNNING`: Bot status check

---

## 🚨 Critical Issues Identified

### 1. **Bot Not Running**
- `is_running: false`
- Last run: **2026-05-26** (13+ days ago)
- No automatic trading happening
- 48,755 attempts blocked by "BOT_NOT_RUNNING"

### 2. **Paper Trading Underwater**
- Lost $3,919 over 5,310 trades
- 28.3% win rate is below profitability threshold
- 4 strategies with 0% win rate

### 3. **Failed Arbitrage Strategies**
- `arb_scanner`: 384 trades, 0 wins
- `cross_platform_arb`: 100 trades, 0 wins
- These are draining capital without any successful trades

### 4. **Strategy Performance Mismatch**
- `line_movement_detector`: 89.8% WR but loses money
- Suggests asymmetric loss sizes (small wins, large losses)

---

## 💡 Recommendations

### Immediate Actions
1. **Fix bot startup** — is_running=false is the biggest issue
2. **Disable losing strategies:**
   - arb_scanner (0% WR, -$1,772)
   - cross_platform_arb (0% WR, -$2,493)
3. **Investigate line_movement_detector** — 89.8% WR shouldn't lose money
4. **Audit bond_scanner** — keep this one running (best performer)

### Strategy Tuning
5. **longshot_bias** has suspicious 98.5% WR — verify this isn't a bug
6. **Risk management review** — losses too large when they happen
7. **Add win-rate guard** — auto-disable strategies with 0% WR after 50 trades

### Performance Improvement
8. **Focus capital on top 3 strategies:**
   - bond_scanner: +$1,140
   - longshot_bias: +$717
   - weather_emos: +$197
9. **Stop live trading** until paper performance improves
10. **Investigate trade execution** — 97.3% blocking rate suggests over-cautious system

---

## Conclusion

**Paper trading is LOSING money at $3,919 over 5,310 trades.** While the risk controls are working (blocking 97% of attempts), the strategies themselves are not profitable overall.

**The bot has been OFFLINE for 13 days** — this is the most critical issue. The good news is the integration work we just did (starting scheduler, loading strategies) should fix this.

**Next steps:**
1. Verify bot is now running (just started scheduler)
2. Disable losing strategies
3. Monitor next 24-48 hours
4. Re-evaluate performance

---

**Report End**

Generated from PolyEdge API endpoint `/api/v1/stats` and `/api/v1/stats/strategies`
