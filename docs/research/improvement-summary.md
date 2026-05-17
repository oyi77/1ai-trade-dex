# Improvement Research & External Reference Index

> **Purpose:** Catalog of external repos, libraries, datasets, and concepts discovered during research that could improve PolyEdge. 
> **Updated:** 2026-05-18
> 
> Use this file to track promising leads without committing to immediate implementation. When an AGI sprint starts, check here first.

---

## 🥇 Tier 1 — Integrate Directly

### 1. PMXT — CCXT for Prediction Markets
| Field | Value |
|---|---|
| **Repo** | https://github.com/pmxt-dev/pmxt |
| **Stars** | 1,736⭐ |
| **Language** | Python + TypeScript |
| **Value** | 🔴 **Replace CLOB client** — single API for Polymarket, Kalshi, Limitless, Hyperliquid |
| **Install** | `pip install pmxt` |
| **Why** | Our `polymarket_clob.py` only handles Polymarket. PMXT supports 10+ platforms with unified interface. Also has MCP server (`npx @pmxt/mcp`). |
| **ROI** | High — eliminates need for separate Kalshi/Limitless connectors |

### 2. Polymarket Strategy Backtester
| Field | Value |
|---|---|
| **Repo** | https://github.com/Polymarket-Research/Polymarket-Strategy-Backtester |
| **Stars** | 596⭐ |
| **Value** | 🟡 **Backtest validation** — compare our backtest results against theirs |
| **Why** | Dedicated Polymarket backtesting engine. Can validate our backtest accuracy. |

### 3. Polymarket Paper Trader
| Field | Value |
|---|---|
| **Repo** | https://github.com/agent-next/polymarket-paper-trader |
| **Stars** | 330⭐ |
| **Value** | 🔴 **Replace paper mode** — real order book execution, exact fee model |
| **Install** | `pip install polymarket-paper-trader` or `npx clawhub install polymarket-paper-trader` |
| **Why** | Our paper mode fabricates fills. This uses real Polymarket order books, level-by-level execution, slippage tracking. MCP server included for AGI integration. |

---

## 🥈 Tier 2 — Architecture Reference

### 4. Polymarket/agents (Official)
| Field | Value |
|---|---|
| **Repo** | https://github.com/Polymarket/agents |
| **Stars** | 3,505⭐ |
| **Value** | 🟡 **RAG pipeline, news sourcing, LLM tools** |
| **Why** | Official Polymarket framework for AI agents. Their RAG pipeline + news sourcing architecture can be adopted. |

### 5. rqalpha
| Field | Value |
|---|---|
| **Repo** | https://github.com/ricequant/rqalpha |
| **Stars** | 6,391⭐ |
| **Value** | 🟢 **Event-driven architecture, portfolio management** |
| **Why** | Battle-tested backtesting framework (6k+ stars). Event-driven pattern can improve our architecture. |

### 6. lumibot
| Field | Value |
|---|---|
| **Repo** | https://github.com/Lumiwealth/lumibot |
| **Stars** | 1,555⭐ |
| **Value** | 🟢 **Broker abstraction, strategy lifecycle** |
| **Why** | AI trading agents framework. Good reference for strategy lifecycle patterns. |

---

## 🥉 Tier 3 — Concepts to Learn

### 7. PyBroker
| Field | Value |
|---|---|
| **Repo** | https://github.com/edtechre/pybroker |
| **Stars** | 2,100⭐ |
| **Value** | 🟢 **NumPy-accelerated backtesting, Walkforward Analysis** |
| **Key Concepts** | Bootstrap metrics, custom data sources, model-based strategies |

### 8. polybot
| Field | Value |
|---|---|
| **Repo** | https://github.com/poly-bot/polybot |
| **Stars** | 636⭐ |
| **Value** | 🔵 **Whale detection, copy trading signals** |
| **Why** | Reverse-engineers Polymarket strategies. Could help with copy-trader module. |

### 9. OctoBot
| Field | Value |
|---|---|
| **Repo** | https://github.com/Drakkar-Software/OctoBot |
| **Stars** | 6,800⭐ |
| **Value** | 🔵 **Exchange abstraction, deployment patterns** |
| **Key Concepts** | 15+ exchange integration via CCXT, Docker deployment, mobile app |

### 10. OpenAlice
| Field | Value |
|---|---|
| **Repo** | https://github.com/TraderAlice/OpenAlice |
| **Stars** | New |
| **Value** | 🔵 **Trade-as-Git concept, Guard pipeline** |
| **Key Concepts** | Stage → Commit → Push execution, pre-execution safety checks, multi-broker UTA |

### 11. basana
| Field | Value |
|---|---|
| **Repo** | https://github.com/vmleon/basana |
| **Stars** | 829⭐ |
| **Value** | 🔵 **Async event-driven framework** |
| **Key Concepts** | Event bus patterns for async strategy execution |

### 12. Polymarket MCP Server
| Field | Value |
|---|---|
| **Repo** | https://github.com/Polymarket/polymarket-mcp-server |
| **Stars** | ~500⭐ |
| **Value** | 🔵 **MCP integration for Polymarket** |
| **Install** | Already installed (polymarket-mcp package) |

### 13. polymarket-paper-trader (by jchimbor)
| Field | Value |
|---|---|
| **Repo** | https://github.com/jchimbor/polymarket-paper-trader |
| **Stars** | 1⭐ |
| **Value** | 🔵 Alternative paper trader with real order books |

---

## 📊 Datasets for AGI Training

Found via GitHub API search — datasets that can make our AGI smarter over time:

| Dataset | Stars | Description | Use for AGI |
|---|---|---|---|
| **Polymarket_data** | 566⭐ | 1.1 billion trading records from Polymarket | 🔴 **Training data for market prediction models** |
| **prediction-market-analysis** | 3,369⭐ | Framework for collecting/analyzing prediction market data | 🟡 **Feature engineering pipeline** |
| **PolymarketBTC15mAssistant** | 692⭐ | Real-time BTC 15m trading assistant data | 🟡 **Pattern recognition training** |
| **Dome API (pmxt alternative)** | — | Prediction market data API | 🟢 **Alternative data source** |

**Kaggle / External Datasets to Explore:**
- Polymarket trade history (available via Data API)
- Kalshi event resolution history
- CoinGecko crypto price history (for oracle strategies)
- NOAA weather data (for weather markets settlement)

---

## 🎯 Priority Implementation Roadmap

```
Phase 1 (Now — May 2026):
  □ Replace paper mode with polymarket-paper-trader (MCP-based)
  □ Validate backtest accuracy against Polymarket Strategy Backtester

Phase 2 (Next — June 2026):
  □ Evaluate PMXT integration (replace CLOB client)
  □ Adopt Polymarket/agents RAG pipeline
  □ Integrate Polymarket_data dataset for ML training

Phase 3 (Future):
  □ PyBroker backtesting integration
  □ Architecture refactor using rqalpha/lumibot patterns
  □ OctoBot-style deployment pipeline
```

---

## 📈 Proven Strategies (from Open Source)

### Crypto 5-min / 15-min Markets

| Repo | Stars | Strategy | Win Rate | Adaptable? |
|---|---|---|---|---|
| **4coinsbot** | 88⭐ | Multi-coin BTC/ETH/SOL 15-min | N/A | ✅ Strategy pattern for polymarket 15-min |
| **polyrec** | 307⭐ | Real-time BTC 15-min terminal dashboard | N/A | ✅ Monitoring UI reference |
| **polymarket-btc-autotrader** | 12⭐ | Autonomous BTC & SOL | 100% ARB | ✅ Claims 100% WR on arbitrage leg |
| **PolyHFT-Autotrading-V3** | 10⭐ | HFT for crypto Up/Down | N/A | ✅ HFT execution pattern |

### Arbitrage

| Repo | Stars | Strategy | Notes |
|---|---|---|---|
| **prediction-market-arbitrage-bot** | 152⭐ | Cross-platform (Polymarket ↔ Kalshi) | 🎯 Most applicable — similar to our `kalshi_arb` |
| **Trum3it/polymarket-arbitrage-bot** | 34⭐ | Rust-based ETH/BTC spread monitor | Could learn from Rust performance |

### Weather Markets

| Repo | Stars | Strategy | Notes |
|---|---|---|---|
| **polymarket-kalshi-weather-bot** | 394⭐ | Weather temp markets (Polymarket + Kalshi) | 🎯 Similar to our `weather_emos` |
| **hermes_weatherbot** | 12⭐ | Exploits weather forecast errors | 🎯 Novel angle — forecast error arb |

### Copy Trading

| Repo | Stars | Strategy | Notes |
|---|---|---|---|
| **OctoBot-Prediction-Market** | 82⭐ | Polymarket copy trading | Fork of OctoBot for prediction markets |

### Toolkits / Platforms

| Repo | Stars | Use |
|---|---|---|
| **polymarket-crypto-toolkit** | 57⭐ | Composable Python toolkit for Polymarket algo trading |
| **homerun** | 63⭐ | Open-source prediction market trading platform |
| **polyrec** | 307⭐ | Real-time Polymarket BTC dashboard (terminal UI) |

---

## 🤖 Additional AI / Data Providers

### AI Providers (untapped)
| Provider | Type | Why |
|---|---|---|
| **Hyperbolic** | GPU compute + AI inference | Cheaper than OpenAI for AGI pipeline |
| **Together.ai** | LLM inference API | 200+ models, lower cost |
| **Groq** (already used) | Fast LLM inference | ✅ Already integrated |
| **Claude** (already used) | Anthropic API | ✅ Already integrated |

### Market Data Providers (untapped)
| Provider | Data | Why |
|---|---|---|
| **Hyperliquid** | Crypto perp + spot data | Prediction markets on Hyperliquid |
| **Limitless** | Prediction markets | Alternative to Polymarket |
| **Myriad Markets** | Prediction markets | Open source prediction market |

---

## 📚 Academic Papers & Research

### Prediction Market Efficiency
- **"Prediction Markets: A Review"** — Rhodes-Kropf, 2023
- **"Information Aggregation in Prediction Markets"** — Wolfers & Zitzewitz
- **"Betting on Beta"** — How prediction market prices relate to statistical probabilities

### ML for Prediction Markets
- LSTM networks for short-term price movement in binary markets
- Transformer models for multi-outcome market resolution
- Bayesian updating for forecast combination

### Strategy Papers
- Kelly Criterion variants for prediction markets (asymmetric payoffs)
- Arbitrage detection across prediction market platforms
- Market microstructure of CLOB-based prediction markets

---

## 🗺️ Full Implementation Roadmap (Updated May 18, 2026)

```
Phase 1 (Now):
  □ Replace paper mode with polymarket-paper-trader (MCP-based)
  □ Validate backtest accuracy against Strategy Backtester
  □ Study 4coinsbot for multi-coin strategy patterns

Phase 2 (Next):
  □ Evaluate PMXT integration (replace CLOB client)
  □ Adopt Polymarket/agents RAG pipeline
  □ Integrate Polymarket_data dataset for ML training
  □ Study arbitrage bot patterns (prediction-market-arbitrage-bot)

Phase 3 (Future):
  □ PyBroker backtesting integration
  □ Weather forecast error arb (hermes_weatherbot pattern)
  □ OctoBot-style deployment pipeline
  □ Hyperliquid prediction market support
  □ Rust-based arb bot components
```

---

## 📦 Datasets — HuggingFace & GitHub

### 🔴 Prediction Market Trade Data

| Dataset | Downloads | Records | Use for AGI | Link |
|---|---|---|---|---|
| **SII-WANGZJ/Polymarket_data** | 28,913 | **1B-10B** rows | 🔥 **Primary training data** — largest Polymarket dataset | [HF](https://huggingface.co/datasets/SII-WANGZJ/Polymarket_data) |
| **wilsonwangwang/Polymarket_data** | 3,937 | 1B-10B rows | Same data, different format | [HF](https://huggingface.co/datasets/wilsonwangwang/Polymarket_data) |
| **AllLongJohnson/Polymarket_data** | 2,234 | 1B-10B rows | Parquet format | [HF](https://huggingface.co/datasets/AllLongJohnson/Polymarket_data) |
| **PolyData/polymarket_trade_capture** | 7,475 | — | Trade capture snapshot (Mar 2026) | [HF](https://huggingface.co/datasets/PolyData/polymarket_trade_capture_5Mar2026) |

### 🟡 Prediction Market — Processed

| Dataset | Downloads | Use | Link |
|---|---|---|---|
| **2084Collective/prediction-markets-historical-v5** | 40 | 1M-10M cleaned records, parquet | [HF](https://huggingface.co/datasets/2084Collective/prediction-markets-historical-v5) |
| **2084Collective/prediction-markets-historical-v4** | 21 | Earlier version | [HF](https://huggingface.co/datasets/2084Collective/prediction-markets-historical-v4) |
| **thomaswmitch/kalshi-prediction-markets-betting** | 208 | Kalshi specific | [HF](https://huggingface.co/datasets/thomaswmitch/kalshi-prediction-markets-betting) |
| **thomaswmitch/kalshi-prediction-markets-markets** | 97 | Kalshi market definitions | [HF](https://huggingface.co/datasets/thomaswmitch/kalshi-prediction-markets-markets) |

### 🟢 Crypto + Prediction Markets

| Dataset | Downloads | Use | Link |
|---|---|---|---|
| **trentmkelly/polymarket_crypto_derivatives** | 13,525 | Crypto derivatives on Polymarket | [HF](https://huggingface.co/datasets/trentmkelly/polymarket_crypto_derivatives) |
| **mingossx/polymarket-crypto-updown** | 4,273 | Crypto up/down market data | [HF](https://huggingface.co/datasets/mingossx/polymarket-crypto-updown) |
| **BrockMisner/polymarket-crypto-5m-15m** | 3,573 | 5-min & 15-min crypto | [HF](https://huggingface.co/datasets/BrockMisner/polymarket-crypto-5m-15m) |
| **aliplayer1/polymarket-crypto-updown** | 4,314 | Alternative version | [HF](https://huggingface.co/datasets/aliplayer1/polymarket-crypto-updown) |
| **rameez543/polymarket_bot_data** | 12,479 | Bot trading data | [HF](https://huggingface.co/datasets/rameez543/polymarket_bot_data) |

### 🔵 News + Signals

| Dataset | Downloads | Use | Link |
|---|---|---|---|
| **lwaekfjlk/prediction-market-news** | 5,907 | News articles for prediction markets | [HF](https://huggingface.co/datasets/lwaekfjlk/prediction-market-news) |
| **ismail-ELBOUKNIFY/news-selection-for-market-prediction** | 43 | News selection for market pred | [HF](https://huggingface.co/datasets/ismail-ELBOUKNIFY/news-selection-for-market-prediction) |

### GitHub Datasets (from earlier search)

| Repo | Stars | Records | Link |
|---|---|---|---|
| **Polymarket_data** | 566⭐ | 1.1B records | [GitHub](https://github.com/Polymarket-Data/Polymarket_data) |
| **prediction-market-analysis** | 3,369⭐ | Framework + data | [GitHub](https://github.com/Polymarket-Research/prediction-market-analysis) |

---

## 🤖 AGI Auto-Research — Current Gaps

| Feature | Status | Why Needed |
|---|---|---|
| 🔴 **Automated GitHub trending scan** | ❌ Missing | AGI should scan new Polymarket repos weekly |
| 🔴 **Automated HF dataset ingestion** | ❌ Missing | Should download + index datasets for ML training |
| 🔴 **Whale wallet tracking** | ❌ Missing | Should track top Polymarket wallets for copy trading |
| 🟡 **Paper/changelog scanner** | ❌ Missing | Should read Polymarket API changelog + research papers |
| 🟡 **Competitor strategy monitor** | ❌ Missing | Should monitor 4coinsbot, polyrec, etc for new patterns |
| 🟢 **Auto-backtest on new data** | ❌ Missing | Should re-backtest strategies when new data arrives |
| 🟢 **Performance degradation alert** | ✅ Partial | Risk layer disables on loss, but no trend analysis |

---

## 🏗️ Major Frameworks We Should Know (MISSED PREVIOUSLY)

| Framework | Stars | Why We Missed It | Value |
|---|---|---|---|
| **hummingbot** | **18,578⭐** | Focused on crypto market making, not prediction markets | 🏆 **Market making patterns** — their strategy for providing liquidity could apply to Polymarket |
| **freqtrade** | **30,000+⭐** | Crypto bot, not prediction markets | 🏆 **Architecture gold standard** — strategy lifecycle, backtesting, deployment |
| **backtesting.py** | **8,374⭐** | General backtesting, not prediction-specific | 🏆 **NumPy/Pandas backtesting** — simpler than PyBroker, more popular |
| **vectorbt** | **5,000+⭐** | Pro-level vectorized backtesting | 🟡 **Portfolio-level backtesting** — can test 100s of strategies at once |
| **jesse** | **2,000+⭐** | Crypto algo trading | 🟢 **Strategy lifecycle patterns** |

### Why These Matter for PolyEdge

| Framework | What We Can Steal |
|---|---|
| **hummingbot** | Liquidity provision algorithm, order book management, **market making on prediction markets** |
| **freqtrade** | Strategy file format, backtesting pipeline, Telegram integration pattern, **docker deployment** |
| **backtesting.py** | Clean strategy API, indicator library, **trade analysis metrics** |
| **vectorbt** | **Portfolio optimization**, parameter scanning, Monte Carlo simulation |

---

## 🔧 Tools & Services We Don't Use (But Should Consider)

### Market Making
| Tool | Stars | Use |
|---|---|---|
| **hummingbot** | 18.5k | Deploy market making strategies on any exchange |
| **OctoBot-Market-Making** | 33 | Market making automation for crypto |

### Backtesting
| Tool | Stars | Why Better Than Ours |
|---|---|---|
| **backtesting.py** | 8.4k | Clean API, 100x faster, built-in indicators |
| **vectorbt** | 5k+ | Portfolio-level, vectorized, 1000x faster |
| **freqtrade backtesting** | 30k+ | Battle-tested, multi-exchange |

### Data Pipelines
| Tool | Use |
|---|---|
| **pm-history-tracker** (5⭐) | Historical data pipeline for prediction markets |
| **Subgraph (Polymarket)** | On-chain data indexing via The Graph |
| **Dune Analytics** | Polymarket dashboards and SQL queries |

### MCP Servers for Polymarket
| Server | Stars | Use |
|---|---|---|
| **caiovicentino/polymarket-mcp-server** | 503⭐ | 🤖 AI-Powered MCP Server — Claude trades Polymarket |
| **pmxt-mcp** | 4⭐ | MCP for unified prediction market API |
| **guangxiangdebizi/PolyMarket-MCP** | 7⭐ | Comprehensive MCP server |

### Copy Trading
| Tool | Use |
|---|---|
| **neosun100/polycopy** (4⭐) | Copy trading bot for Polymarket |
| **G3-DEV-AGENCY/polymarket-copytrading-bot** (104⭐) | Copy trading |

### Monitoring
| Tool | Use |
|---|---|
| **freqhub** (3⭐) | Multi-bot dashboard for Freqtrade |
| **BEC** (64⭐) | Binance bot with automated monitoring |

---

## 📦 Full Dataset Inventory (All Sources)

### HuggingFace — New Finds
| Dataset | Downloads | Records | Use |
|---|---|---|---|
| **SII-WANGZJ/Polymarket_data** | 28,913 | 1B-10B | 🔴 ML training |
| **PolyData/polymarket_trade_capture** | 7,475 | — | Backtest validation |
| **mingossx/polymarket-crypto-updown** | 4,273 | — | Crypto strategy |
| **BrockMisner/polymarket-crypto-5m-15m** | 3,573 | — | 5-min strategy |
| **rameez543/polymarket_bot_data** | 12,479 | — | Bot behavior |
| **2084Collective pred markets** | 40-49 | 10K-1M | Cleaned historical |
| **lwaekfjlk/prediction-market-news** | 5,907 | — | News → sentiment |

### Missing Dataset Sources (Untapped)
| Source | What's Available | How to Access |
|---|---|---|
| **Kaggle** | Stock/crypto datasets, maybe prediction markets | Needs API key |
| **Dune Analytics** | Polymarket on-chain SQL queries | Free tier |
| **The Graph** | Polymarket subgraph for indexed on-chain data | GraphQL API |
| **CoinGecko API** | All crypto historical prices | Free tier (rate limited) |
| **Polymarket Data API** | Full trade history | Direct API (we use it partially) |
| **NOAA/NWS** | Weather history for settlement validation | Free API |
| **Twitter/X** | Market sentiment, news | Needs API key |

---

## 🎯 Updated Priority Roadmap

```
Phase 1 (Now — May 2026):
  □ Replace paper mode with polymarket-paper-trader
  □ Install backtesting.py for faster backtesting
  □ Start collecting Polymarket_data from HF (28k downloads, 1B rows)
  □ Study hummingbot architecture for market making patterns

Phase 2 (Next — June 2026):
  □ PMXT integration (replace CLOB client, get multi-platform)
  □ Install polymarket-mcp-server for AGI direct access
  □ Integrate news dataset for sentiment signals
  □ Set up Dune Analytics queries for on-chain data

Phase 3 (Future):
  □ Deploy market making via hummingbot patterns
  □ Portfolio-level backtesting with vectorbt
  □ Copy trading via polycopy/G3 patterns
  □ Freqtrade-style deployment (docker, Telegram, monitoring)
```
