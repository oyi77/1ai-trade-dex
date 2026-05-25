# Draft: Prediction Market Microstructure Research Insights

## Sources
- Jon Becker: "The Microstructure of Wealth Transfer in Prediction Markets" (2026) — 72.1M trades, $18.26B volume on Kalshi
- Bloomberg/Yahoo: "Most prediction market traders are losing money while bots rack up gains" (Apr 2026)
- Cointelegraph/DigitalToday: "AI agents reshape prediction market arbitrage" (Mar 2026)
- Becker GitHub: prediction-market-analysis (3.3k stars, parquet datasets, analysis framework)
- 4 X/Twitter links (inaccessible due to X blocking) — heynavtoor, ProbTradeAI, seelffff, WillyChuang, jonjonclark

## Key Research Findings (CRITICAL for Polyedge strategy)

### 1. Maker-Taker Wealth Transfer (BIGGEST FINDING)
- **Makers**: +1.12% avg excess return across ALL price levels
- **Takers**: -1.12% avg excess return — systematically losing
- At 1-cent contracts: takers win 0.43%, makers win 1.57% — 57pp gap
- Makers profit by "being counterparty to optimism" — not by forecasting
- **Makers don't need to predict the future, just sell into biased flow**

### 2. YES/NO Asymmetry (DIRECTION BIAS)
- At 1-cent: YES contract EV = -41%, NO contract EV = +23% — 64pp divergence
- NO outperforms YES at 69 of 99 price levels
- Takers account for 41-47% of YES volume at 1-10¢ range
- Makers account for 43% of NO volume at 99¢
- **Buying NO at longshot prices is systematically better than buying YES**
- Dollar-weighted: YES buyers -1.02%, NO buyers +0.83%

### 3. Execution Edge > Information Edge
- "Retail investors, despite being correct, are losing money" — Della Vedova
- "The execution edge is an underrated aspect of trading"
- Bots average 89 trades/day vs 2.2 for non-bots
- Bots got into markets EARLIER and at BETTER PRICES — not better predictions
- Arbitrage windows vanish in SECONDS
- $40M leaked from Polymarket due to price inefficiencies

### 4. Category-Specific Efficiency
- Finance: 0.17pp gap (nearly perfect efficiency) — dry, quantitative questions filter out emotion
- Politics: 1.02pp (moderate)
- Sports: 2.23pp (72% of volume!)
- Crypto: 2.69pp ("number go up" mentality)
- Entertainment: 4.79pp (low barrier to perceived expertise)
- Weather: 2.57pp (moderate gap)
- **Weather markets have a 2.57pp maker-taker gap** — relevant to weather_emos strategy

### 5. Professionalization of Liquidity
- Pre-2024: takers were WINNING (+2.0%), makers were LOSING (-2.0%)
- Post-2024 election: FLIPPED — takers -2.5%, makers +2.5%
- Volume surge attracted professional market makers who extract value from taker flow
- **The longshot bias existed for years but only became profitable to exploit once professional MM entered**

### 6. Arbitrage Opportunities
- Cross-market probability sum ≠ 100%: frequent on Polymarket
- $40M estimated leaked from these inefficiencies
- Windows close in seconds — requires automated scanning
- Current bots scan "hundreds of markets per second" (Edge & Node CEO)

## Implications for Polyedge (NOT YET VERIFIED — awaiting explore agents)

### Critical Questions
1. Are ALL our 14 strategies acting as TAKERS? If yes, we're paying the "optimism tax"
2. Do we exploit the YES/NO asymmetry? (buying NO at longshot is +23% EV vs YES at -41%)
3. Does copy_trader mirror taker flow from whales? (paying spread both ways)
4. Do we have a market_maker strategy providing limit orders? (capturing the optimism tax)
5. What's our signal-to-execution latency? (late = bad prices even if direction correct)
6. Do we use WebSocket real-time data or REST polling? (seconds matter)
7. Is probability_arb capturing the probability sum ≠ 100% inefficiency quickly enough?

### Potential New Strategies / Enhancements
- **Market Making**: Place limit orders to capture spread + optimism tax (1.12% avg edge)
- **NO-Longshot Bias Exploit**: Systematically buy NO at longshot prices instead of YES
- **Cross-market Sum Arb**: Scan for probability sums ≠ 100% across related Polymarket markets
- **Execution Speed**: WebSocket-first architecture, sub-second signal-to-order
- **Category-aware Confidence**: Adjust confidence by category (Finance = efficient, Entertainment = exploitable)
- **Becker Dataset Integration**: Use 36GB parquet dataset for backtesting and calibration

## Open Questions
- X/Twitter links unread — may contain additional strategy insights
- Need to verify explore agent findings before updating plans