# Strategy Research Report — 2026-06-30

## Current State
- Only 3 strategies enabled: bond_scanner, longshot_bias, ultra_cheap_no
- 14 strategies killed (all with negative lifetime PnL)
- Need new strategies based on research, not guessing

---

## Tier 1: Proven Strategies (Implement First)

### 1. Smart Money Copy Trading
**Source:** Industry practice, Polymarket leaderboard analysis
**Edge:** Follow wallets with proven track records. 84% of Polymarket traders lose money — copy the 0.03% who win.
**Logic:**
- Monitor top 50 wallets from Polymarket leaderboard via `data-api.polymarket.com/leaderboard`
- Track their recent trades via `data-api.polymarket.com/trades?user={address}`
- Filter: only copy if wallet has >60% WR over 50+ trades
- Filter: only copy trades >$100 size (skin in the game)
- Filter: only copy if trade is <5 minutes old (not stale)
- Execute same direction with Kelly-sized position
**Data needed:** Polymarket Data API (already integrated)
**Complexity:** LOW — we already have the API client
**Risk:** Following whales can get you into illiquid markets

### 2. Correlation/Spread Trading
**Source:** Academic research, industry practice
**Edge:** Related markets that should move together sometimes decouple. Trade the convergence.
**Logic:**
- Find market pairs with historical correlation >0.8 (e.g., "Will X win?" and "Will X's party control senate?")
- When spread diverges >2σ from mean, bet on convergence
- Use z-score for entry: z > 2.0 = buy underpriced, sell overpriced
- Exit when z < 0.5 (mean reversion)
**Data needed:** Historical price data for market pairs (we have this in trades table)
**Complexity:** MEDIUM — need correlation computation engine
**Risk:** Correlation can break permanently (regime change)

### 3. CLOB Market Making (Spread Capture)
**Source:** TUM academic research, Polymarket CLOB mechanics
**Edge:** Capture bid-ask spread by providing liquidity on both sides. Polymarket rewards liquidity providers.
**Logic:**
- Place limit orders on both sides of the book (bid below mid, ask above mid)
- Spread = max(1%, half the current bid-ask spread)
- Inventory control: if net long >30% of bankroll, tighten ask side
- Use Just-In-Time (JIT) liquidity: only quote during high-volume bursts
- Pull all orders during news events (adverse selection risk)
**Data needed:** Real-time order book (already have CLOB client)
**Complexity:** MEDIUM — need order management system
**Risk:** Adverse selection during news events; inventory can get stuck

---

## Tier 2: Research-Backed Strategies (Implement Second)

### 4. Resolution-Aware Near-Expiry Trading
**Source:** Bond scanner success pattern (our only profitable strategy)
**Edge:** Markets near resolution with >90% implied probability are mispriced because:
- Liquidity dries up → wider spreads → better entry
- Retail traders don't bother → less competition
- Settlement is deterministic if outcome is known
**Logic:**
- Find markets resolving within 48 hours with YES > 0.90 or NO > 0.90
- Verify outcome with external data (news APIs, official sources)
- Buy the near-certain outcome at best available price
- Size: 5% of bankroll per trade (conservative)
- Auto-sell 1 hour before resolution (we just built this)
**Data needed:** Gamma API for market discovery + news verification
**Complexity:** LOW — extending bond_scanner logic
**Risk:** Black swan events can flip "certain" outcomes

### 5. Multi-Outcome Arbitrage (LMSR Invariant)
**Source:** Academic research on prediction market invariants
**Edge:** For multi-outcome markets (elections, tournaments), sum of all outcome prices must = $1.00. When sum > 1.00, short the overpriced outcomes.
**Logic:**
- Find multi-outcome markets via Gamma API
- Calculate sum of all YES prices
- If sum > 1.02 (after fees), buy NO on the most overpriced outcome
- If sum < 0.98, buy YES on the most underpriced outcome
- Size: 3% of bankroll per trade
**Data needed:** Gamma API (already integrated)
**Complexity:** LOW — simple math on existing data
**Risk:** Execution risk (prices move between legs); liquidity may be thin

### 6. News-Driven Momentum
**Source:** Academic research on information cascades in prediction markets
**Edge:** When breaking news affects a market, prices adjust slowly (seconds to minutes). Faster information = profit.
**Logic:**
- Monitor news feeds (Twitter/X API, RSS, Google News)
- When news mentions a market topic, check if market price moved
- If news is bullish but price hasn't moved yet → buy YES
- If news is bearish but price hasn't moved yet → buy NO
- Exit within 15 minutes (momentum, not long-term hold)
**Data needed:** News API (we have Exa, Google News)
**Complexity:** MEDIUM — need NLP/sentiment analysis
**Risk:** Fake news; latency disadvantage vs faster bots

---

## Tier 3: Advanced Strategies (Research Phase)

### 7. Bayesian Market Making
**Source:** Virginia Tech academic research
**Edge:** Learn from trade flow to update probability estimates faster than the market.
**Logic:**
- Maintain a Bayesian prior for each market's true probability
- Update prior based on trade direction and size (large buys → probability likely higher)
- Quote tighter when confidence is high, wider when uncertain
- Use Kelly criterion for position sizing
**Complexity:** HIGH — need Bayesian inference engine

### 8. Reinforcement Learning Quote Optimization
**Source:** arXiv research on RL for market making
**Edge:** Train an RL agent to optimize bid/ask placement for maximum spread capture with minimum inventory risk.
**Complexity:** HIGH — need RL training pipeline

---

## Open Source Tools Found

| Repo | What it does | Use for us |
|---|---|---|
| [PredictOS](https://github.com/PredictionXBT/PredictOS) | AI agent framework for prediction markets | Strategy framework |
| [poly-maker](https://github.com/warproxxx/poly-maker) | Market making bot for Polymarket | Strategy #3 reference |
| [polymarket-trade-engine](https://github.com/KaustubhPatange/polymarket-trade-engine) | Modular trading engine | Execution engine reference |
| [Awesome-Prediction-Market-Tools](https://github.com/aarora4/Awesome-Prediction-Market-Tools) | Curated tool list | Research reference |

---

## Implementation Priority

1. **Smart Money Copy Trading** — lowest complexity, highest confidence (we know the wallets win)
2. **Resolution-Aware Near-Expiry** — extends our only profitable strategy
3. **Multi-Outcome Arbitrage** — simple math, existing data
4. **CLOB Market Making** — medium complexity, proven edge
5. **Correlation Trading** — medium complexity, needs historical analysis
6. **News-Driven Momentum** — medium complexity, needs NLP

## Key Insight from Research

> "84% of Polymarket traders lose money. The 0.03% who win don't predict the future — they exploit structural inefficiencies."

Our bond_scanner works because it exploits a structural inefficiency: near-certain outcomes are mispriced near resolution. We need more strategies like this — ones that exploit market structure, not predict outcomes.
