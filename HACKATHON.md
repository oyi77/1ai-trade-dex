# PolyEdge — Autonomous Trading Agent & Strategy Skill Suite

> **BNB HACK: AI Trading Agent Edition** | CoinMarketCap × Trust Wallet × BNB Chain
> **Entering**: 🤖 Onchain Trading Agent Track + 📊 Crypto Intelligence Agent Track
> **Special Prizes**: Best Use of Agent Hub, Best Use of Trust Wallet Agent Kit, Best Use of BNB AI Agent SDK
> **GitHub**: https://github.com/openclaw/1ai-trade-dex (private) | Demo: http://localhost:8100/docs

---

## What It Is

PolyEdge is an existing production-grade automated trading system (137K LOC, 14 strategies, AGI evolution engine, 11 market providers). For this hackathon we extended it with three sponsor integrations — CMC Agent Hub, Trust Wallet Agent Kit, and BNB AI Agent SDK — and entered both tracks.

---

## 🤖 Track 1: Onchain Trading Agent

### Architecture

```
CMC Data API (quotes/OHLCV/trending/global metrics)
       │
       ▼
CoinMarketCapFeed → AGI Debate Engine → Risk Controls
       │                                    │
       ▼                                    ▼
CMC Skills Registry                    TWAK Execution (BSC)
  (signal validation)                       │
                                            ▼
                                      PancakeSwap / BSC
```

### Sponsor Stack Integration

**CoinMarketCap (Agent Hub):**
- REST API v2 endpoints: `/v2/cryptocurrency/quotes/latest`, `/v2/cryptocurrency/ohlcv/latest`, `/v1/global-metrics/quotes/latest`, `/v1/cryptocurrency/trending/latest`
- MCP bridge: `mcp_get_market_snapshot()` and `mcp_get_technicals()` produce LLM-friendly structured output (no raw JSON parsing)
- Pre-computed signals built in: RSI, SMA, support/resistance from OHLCV data

**Trust Wallet Agent Kit:**
- **Mode A (Autonomous Agent Wallet)**: agent signs its own transactions within user-defined rules
- CLI surface: `twak swap`, `twak wallet portfolio`, `twak price`, `twak automation dca`, `twak alert create`
- Execution via Python subprocess wrapper (`TWAKClient`) — signal comes in, TWAK CLI executes, result returns
- Trade safeguards: confidence threshold (≥0.6 to execute), token allowlist, risk rules passed as parameters
- **x402 integration**: `twak serve` exposes x402 pay-per-call endpoints; the agent can charge other agents for its signals

**BNB AI Agent SDK (bnbagent):**
- ERC-8004 agent identity registration on BSC Testnet (gas-free via MegaFuel)
- ERC-8183 agentic commerce protocol — job creation, escrow, settlement
- Contract addresses (BSC Testnet): Commerce=`0xa206c0517b6371c6638cd9e4a42cc9f02a33b0de`, Identity=`0x8004A818BFB912233c491871b3d84c89A494BD9e`

### Autonomous Trade Loop

```
1. CoinMarketCapFeed.get_quotes() → market snapshot
2. CMC Skills Registry validates signal (momentum/regime/sentiment)
3. AGI debate engine scores confidence
4. Risk module checks: allowed token? confidence ≥ min? position within limits?
5. TWAKClient.autonomous_trade() executes via `twak swap` on BSC
6. Result logged, position tracked
```

### Registration (Track 1)

```bash
twak compete register
```

Agent wallet will be registered before the June 22 trading window opens.

### Setup

```bash
# Prerequisites
export CMC_PRO_API_KEY="your_key"
curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash  # TWAK
pip install bnbagent  # BNB Agent SDK (optional)

# Run
pip install -r requirements.txt
uvicorn backend.api.main:app --port 8100

# Verify
curl http://localhost:8100/api/v1/hackathon/status
curl http://localhost:8100/api/v1/hackathon/agent
```

### API Endpoints (Track 1)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/hackathon/status` | System health |
| `GET` | `/api/v1/hackathon/agent` | Agent status, balance, open positions |
| `POST` | `/api/v1/hackathon/trade` | Execute a trading signal via TWAK |
| `POST` | `/api/v1/hackathon/agent/onchain` | Register ERC-8004 identity on BSC |
| `GET` | `/api/v1/hackathon/manifest` | Full submission manifest (JSON) |

---

## 📊 Track 2: Crypto Intelligence Agent Track

5 CMC Skills registered for the Skills Marketplace. Each skill consumes CMC data, runs a strategy pipeline, and returns agent-ready structured output.

### Skills

| # | Skill | What It Does | Input | Output | Category |
|---|-------|-------------|-------|--------|----------|
| 1 | **cmc_momentum_scanner** | Multi-asset directional momentum using SMA crossover + RSI from CMC OHLCV data | `symbols`, `lookback_hours` | Direction, confidence, price, support/resistance | Trading Signal |
| 2 | **cmc_market_regime** | Regime classifier from CMC global metrics — identifies BTC season, alt season, bullish/bearish phases. Outputs strategy allocation weights | (none) | Regime, confidence, allocation ratios, risk level | Market Analysis |
| 3 | **cmc_cross_asset_arb** | Detects price divergences between individual assets and sector average. Flags mean-reversion opportunities when divergence exceeds threshold | `symbols`, `min_divergence_pct` | Opportunities ranked by divergence, direction, confidence | Trading Signal |
| 4 | **cmc_risk_assessment** | Real-time portfolio risk: volatility scoring per asset, concentration warnings, recommended exposure % and max position % | (none) | Risk level, volatility scores, warnings, position limits | Risk Management |
| 5 | **cmc_sentiment** | Composite sentiment from trending data + BTC RSI + asset price action. Classifies market structure as trending/ranging/correcting | (none) | Sentiment score (0-100), classification, trending tokens | Market Analysis |

### Example: cmc_market_regime Output

```json
{
  "regime": "bitcoin_season_bullish",
  "confidence": 0.8,
  "total_market_cap": 3200000000000,
  "btc_dominance": 62.5,
  "strategy_allocation": {
    "momentum": 0.4,
    "trend_following": 0.3,
    "mean_reversion": 0.1,
    "market_making": 0.2
  },
  "risk_level": "low"
}
```

### Backtesting

All 5 skills are backtestable. The codebase includes a full backtesting engine with Sharpe ratio, Sortino ratio, max drawdown, and win rate metrics — reused from the existing PolyEdge infrastructure.

### API Endpoints (Track 2)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/hackathon/skills` | List all registered skills |
| `POST` | `/api/v1/hackathon/skills/{name}/run` | Execute a specific skill |
| `GET` | `/api/v1/hackathon/market` | Combined market snapshot (all skills) |

### Setup

```bash
# Just needs CMC API key
export CMC_PRO_API_KEY="your_key"
uvicorn backend.api.main:app --port 8100

# List skills
curl http://localhost:8100/api/v1/hackathon/skills

# Run a skill
curl -X POST http://localhost:8100/api/v1/hackathon/skills/cmc_momentum_scanner/run \
  -H "Content-Type: application/json" \
  -d '{"symbols": ["BTC", "ETH", "SOL"], "lookback_hours": 24}'
```

---

## What Makes This Different

1. **Production-grade foundation**: Not a fresh hackathon project. 137K LOC, 14 strategies, AGI evolutionary engine, full risk management framework (Kelly sizing, circuit breakers, drawdown caps, concentration limits). This was a trading system before the hackathon — the sponsor integrations make it agent-ready.

2. **AGI orchestrator**: Each strategy goes through a DRAFT → SHADOW → PAPER → LIVE promotion pipeline. Strategies with <30% win rate are auto-killed. The system evolves its own strategy composition based on market conditions.

3. **Multi-provider architecture**: The same system that trades Polymarket, Kalshi, Hyperliquid, and 8 other venues now trades BSC via TWAK. The market provider plugin pattern (`BaseMarketProvider`) made adding BSC/TWAK a drop-in — same interface, different venue.

4. **Both tracks fully entered**: The CMC Skills (Track 2) feed the AGI analysis (Track 1). They're not separate projects — the skills validate signals before the autonomous agent executes.

---

## Key Files (Hackathon-Specific)

| File | LOC | Purpose |
|------|-----|---------|
| `backend/data/crypto_feeds/providers/coinmarketcap.py` | ~170 | CMC Data API feed with MCP bridge + 7 endpoints |
| `backend/clients/twak_client.py` | ~370 | TWAK CLI wrapper with paper trading sim |
| `backend/clients/bnb_agent_client.py` | ~210 | BNB Agent SDK (ERC-8004, ERC-8183) |
| `backend/modules/cmc_skills.py` | ~320 | 5 CMC Skills + skill registry |
| `backend/markets/providers/bsc_provider.py` | ~290 | BSC/TWAK market provider with paper mode |
| `backend/api/hackathon.py` | ~430 | All hackathon API endpoints |
| `HACKATHON.md` | — | This file |