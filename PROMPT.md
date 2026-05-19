# 1A-POLY-TRADER — Ultimate AI Agent Prompt v2

> **Build a Polymarket Intelligence & Autonomous Trading System.**
> 
> Analyze ANY wallet, discover profitable strategies, replicate them, execute autonomously.
> All data sources are public / on-chain / no auth needed for analysis.
> Authentication only required for trade execution (CLOB API + private key).

---

## 🎯 MISSION

Build a **complete Polymarket ecosystem** that enables:

| Capability | Description |
|---|---|
| **🔍 Wallet Intelligence** | Analyze any Polymarket wallet — full history, PnL, win rate, strategy fingerprint, behavioral patterns |
| **🐋 Whale Discovery** | Scan the entire Polymarket ecosystem to find profitable traders ranked by PnL, WR, Sharpe ratio |
| **🧠 Strategy Replication** | Not just copy trades — **understand WHY** a strategy works and replicate the decision logic |
| **🤖 Autonomous Execution** | Deploy a 24/7 trading agent with risk controls, session-aware adaptation, auto-pause |
| **📊 Performance Analytics** | Real-time dashboard, PnL tracking, trade journal, strategy performance monitoring |
| **⚡ Opportunity Detection** | Spot mispriced markets, arbitrage opportunities, momentum shifts in real-time |

---

## 📡 COMPLETE DATA SOURCES

### A. Public APIs (No Auth Required)

#### 1. Polymarket Data API
**Base:** `https://data-api.polymarket.com`

```python
# === USER / WALLET DATA ===

# Full trading history (closed positions) — THE GOLD SOURCE
GET /closed-positions?user={proxy_wallet}&limit=50&offset=0
# Response: realizedPnl, title, outcome, avgPrice, totalBought, timestamp,
#           slug, eventSlug, conditionId, asset, curPrice, icon,
#           outcomeIndex, oppositeOutcome, oppositeAsset

# Current open positions
GET /positions?user={proxy_wallet}
# Response: size, avgPrice, curPrice, currentValue, cashPnl, percentPnl

# User activity (real-time events)
GET /activity?user={proxy_wallet}&limit=500

# Current portfolio value
GET /value?user={proxy_wallet}

# Raw trades/order fills
GET /trades?user={proxy_wallet}&limit=50

# === MARKET DATA ===

# All active markets (simplified)
GET /markets?limit=100&offset=0
# Supports: closed, archived, tag filters

# Single market details
GET /markets/{condition_id}

# Market price history
GET /price-history/{market_slug}?interval=max&fidelity=1440

# Current order book
GET /orderbook/{token_id}

# Market events
GET /events?limit=100
```

**Pagination Rules:**
- `limit` max = 50 per request (for user data)
- `offset = 0, 50, 100, 150...` until empty response
- Add 100ms delay between pages to be polite
- Cache results to JSON to avoid re-fetching

**Sorting:**
```
sortBy=REALIZEDPNL|TITLE|PRICE|AVGPRICE|TIMESTAMP
sortDirection=ASC|DESC
```

#### 2. Polymarket Gamma API (Market metadata)
**Base:** `https://gamma-api.polymarket.com`

```python
# Get ALL markets with full metadata
GET /markets?limit=100&offset=0
# Returns: id, question, description, outcomes[], tags[], volume,
#           liquidity, startDate, endDate, image, ...

# Get events
GET /events?limit=100&offset=0

# Single event with all markets
GET /events/{event_id}
```

#### 3. Polymarket CLOB API (Read-only endpoints)
**Base:** `https://clob.polymarket.com`

```python
# Market data (no auth)
GET /midpoint/{token_id}
GET /price/{token_id}?side=BUY|SELL
GET /book/{token_id}
GET /last-trade-price/{token_id}
GET /trades?limit=100
GET /simplified-markets?limit=100
GET /server-time
GET /ok

# Auth required
GET /orders?status=OPEN
GET /orders?status=MATCHED
GET /transactions
GET /data/position-snapshots?limit=100

# Token discovery
GET /neg-risk/tc
GET /neg-risk/tc/{condition_id}
GET /neg-risk/tc/{condition_id}/c
GET /neg-risk/tc/{condition_id}/c/{outcome_id}

# Rewards
GET /rewards/bbo-1mm
```

#### 4. Blockscout API (Polygon blockchain explorer)
**Base:** `https://polygon.blockscout.com/api/v2`

**PURPOSE:** Find Polymarket PROXY WALLET from EOA wallet address.

```python
# Get token transfers
GET /addresses/{wallet}/token-transfers

# PUSD token address
PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"

# Look for Transfer(from=0x0000...000, to=proxy_wallet)
# This is a MINT event → to address = proxy wallet

# For EIP-7702 / contract wallets:
GET /addresses/{wallet}/internal-transactions
# Parse tx receipt logs for CTF transfer events
```

**Edge cases to handle:**
- No PUSD transfers → user doesn't use Polymarket directly
- Multiple proxy wallets → pick most recent / highest volume
- Contract wallet (EIP-7702) → parse receipt logs differently

#### 5. Blockscout Base API (for Base chain USDC)
**Base:** `https://base.blockscout.com/api/v2`

For users bridging from Base chain to Polygon.

#### 6. Polymarket Profile Page (username → wallet)
**URL:** `https://polymarket.com/@{username}`

```python
# Parse __NEXT_DATA__ from HTML
import re, json, requests

r = requests.get(f"https://polymarket.com/@{username}")
match = re.search(r'<script id="__NEXT_DATA__".*?>(.*?)</script>', r.text, re.DOTALL)
data = json.loads(match.group(1))

for q in data['props']['pageProps']['dehydratedState']['queries']:
    key = str(q['queryKey'])
    d = q['state']['data']
    
    if 'volume' in key:
        volume = d['amount']
        pnl = d['pnl']
        name = d['name']
        
    if 'user-stats' in key:
        trades = d['trades']
        biggest_win = d['largestWin']
        join_date = d['joinDate']
    
    if 'biggest-wins' in key or 'biggestWins' in key:
        wins = d.get('biggestWins', [])
    
    if "'positions'" in key and 'CURRENT' in key:
        pages = d.get('pages', [])
        if pages and isinstance(pages[0], list):
            positions = pages[0]
    
    # CRITICAL: wallet address is here
    if 'user' in key.lower() and 'address' in d:
        proxy_wallet = d['address']
    
    if 'user-clob' in key.lower():
        eoa_wallet = d.get('address', '')
        proxy_wallet = d.get('polygonAddress', '')
```

---

### B. Authenticated APIs (For Trade Execution)

#### 1. Polymarket CLOB V2 Client
**Current:** `py-clob-client-v2` (V1 is deprecated/archived)
**PyPI:** `pip install py-clob-client`
**GitHub:** `https://github.com/Polymarket/py-clob-client-v2`

```python
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    OrderArgs, MarketOrderArgs, OrderType, BookParams,
    OpenOrderParams, ApiCreds
)
from py_clob_client.order_builder.constants import BUY, SELL

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon

# Level 0: Read-only (no auth)
client = ClobClient(HOST)
ok = client.get_ok()
markets = client.get_simplified_markets()
book = client.get_order_book(token_id)

# Level 1: Authenticated
private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
funder = os.getenv("POLYMARKET_WALLET_ADDRESS")  # Proxy wallet

client = ClobClient(
    HOST,
    key=private_key,
    chain_id=CHAIN_ID,
    signature_type=1,  # 0=EOA, 1=Magic/Email, 2=Browser proxy
    funder=funder,
)
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)

# === ORDER OPERATIONS ===

# Limit order (GTC = Good Till Cancelled)
order = OrderArgs(token_id="123", price=0.50, size=10.0, side=BUY)
signed = client.create_order(order)
resp = client.post_order(signed, OrderType.GTC)

# Market order (FOK = Fill Or Kill)
mo = MarketOrderArgs(token_id="123", amount=25.0, side=BUY, order_type=OrderType.FOK)
signed_mo = client.create_market_order(mo)
resp = client.post_order(signed_mo, OrderType.FOK)

# Cancel orders
client.cancel(order_id)        # Single
client.cancel_all()            # All open

# Get open orders
open_orders = client.get_orders(OpenOrderParams())

# Get fills
fills = client.get_fills()
```

#### 2. On-Chain Operations (Web3)

```python
from web3 import Web3
from web3.middleware import geth_poa_middleware

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
w3.middleware_onion.inject(geth_poa_middleware, layer=0)
acct = w3.eth.account.from_key(private_key)

# Check MATIC balance (for gas)
matic = w3.eth.get_balance(acct.address)

# Check pUSD balance (USDC.e on Polygon)
PUSD = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
erc20_abi = [...]  # Standard ERC20 ABI
pusd_contract = w3.eth.contract(address=PUSD, abi=erc20_abi)
balance = pusd_contract.functions.balanceOf(acct.address).call() / 1e6

# Approvals needed (one-time setup):
# USDC → exchange contracts
# Conditional Tokens (CTF) → exchange contracts
EXCHANGES = [
    "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",  # Main
    "0xC5d563A36AE78145C45a50134d48A1215220f80a",  # Neg risk
    "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",  # Neg risk adapter
]
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"  # Conditional tokens
```

---

## 🧠 ADVANCED ARCHITECTURE

```
1a-poly-trader/
├── README.md
├── requirements.txt
├── config.py                           # Central config, env vars, thresholds
├── main.py                             # CLI entry point + interactive shell
│
├── core/                               # === CORE MODULES ===
│   ├── __init__.py
│   ├── proxy_finder.py                 # Blockscout → extract proxy wallet
│   ├── wallet_resolver.py              # username → EOA → proxy wallet chain
│   ├── history.py                      # Pull positions/activity from Data API
│   ├── analyzer.py                     # PnL, WR, Sharpe, strategy analysis
│   ├── scanner.py                      # Wallet discovery + ranking engine
│   ├── copytrade.py                    # Execute copy trades via CLOB
│   ├── trader.py                       # Autonomous trading daemon
│   └── portfolio.py                    # Portfolio tracking & risk management
│
├── strategies/                         # === STRATEGY ENGINE ===
│   ├── __init__.py
│   ├── classifier.py                   # Market categorization (15+ categories)
│   ├── fingerprint.py                  # Build strategy profile from history
│   ├── replication.py                  # Replicate strategy logic (not just trades)
│   ├── backtest.py                     # Backtest strategies on historical data
│   └── opportunity.py                  # Real-time opportunity detection
│
├── risk/                               # === RISK MANAGEMENT ===
│   ├── __init__.py
│   ├── position_sizer.py               # Kelly Criterion + variants
│   ├── circuit_breaker.py              # Auto-pause on losses, drawdown
│   ├── exposure_limits.py              # Per-market, per-strategy, per-day limits
│   └── sanity_checks.py                # Pre-trade validation (price, liquidity, spread)
│
├── monitor/                            # === MONITORING & ALERTING ===
│   ├── __init__.py
│   ├── tracker.py                      # Real-time PnL & position tracker
│   ├── alerts.py                       # Telegram/console alerts
│   ├── dashboard.py                    # Performance dashboard (HTML/FastAPI)
│   └── journal.py                      # Trade journal (SQLite/CSV)
│
├── streaming/                          # === REAL-TIME DATA ===
│   ├── __init__.py
│   ├── websocket.py                    # Polymarket WebSocket price feed
│   ├── pool_poller.py                  # Poll-based price monitor (fallback)
│   └── event_processor.py              # Process events → trigger actions
│
├── data/                               # === DATA STORAGE ===
│   ├── known_wallets.json              # Cached scanned wallets
│   ├── strategy_db.json                # Strategy fingerprints
│   ├── trade_journal.csv               # All executed trades
│   └── market_cache/                   # Cached market metadata
│
├── scripts/                            # === UTILITY SCRIPTS ===
│   ├── scan_top_traders.py             # Discover & rank profitable wallets
│   ├── auto_copy_trade.py              # Daemon: monitor & copy
│   ├── analyze_myself.py               # Analyze our own wallet performance
│   ├── backtest_strategy.py            # Run backtest on strategy
│   ├── deploy_dashboard.py             # Start FastAPI dashboard server
│   └── one_time_setup.py               # Approvals, wallet setup
│
└── tests/
    ├── test_proxy_finder.py
    ├── test_analyzer.py
    ├── test_copytrade.py
    ├── test_strategies.py
    └── test_integration.py
```

---

## 🔧 MODULE IMPLEMENTATION SPECIFICATIONS

### Module 1: Proxy Finder (`core/proxy_finder.py`)

```python
def find_proxy_wallet(eoa_address: str) -> Optional[str]:
    """
    Given a user's EOA wallet, find their Polymarket proxy wallet.
    
    Method A (primary): Blockscout PUSD MINT events
    - Query /addresses/{eoa}/token-transfers for PUSD token
    - Filter: Transfer(from=0x0000...000, to=ANY) → to = proxy wallet
    - If multiple, pick the one with most recent timestamp
    
    Method B (fallback): Polymarket profile page
    - Fetch https://polymarket.com/@{username} if username available
    - Parse __NEXT_DATA__ for user-clob query → polygonAddress
    
    Method C (fallback): Internal transactions
    - Query /addresses/{eoa}/internal-transactions
    - Look for CTF deposit events
    
    Method D (last resort): EIP-7702 contract wallets
    - Check if eoa is a contract
    - Parse tx receipt logs for ERC1155 TransferSingle events
    - Extract operator/to addresses
    
    Returns: proxy_wallet address (checksummed) or None
    """
```

### Module 2: Wallet Resolver (`core/wallet_resolver.py`)

```python
def resolve_wallet(input_str: str) -> dict:
    """
    Resolve ANY input format to wallet info.
    
    Supported inputs:
    - "0x..." → EOA or proxy address (auto-detect)
    - "@username" → Polymarket username (fetch profile)
    - "username" → Also treat as Polymarket username
    
    Returns:
    {
        'eoa': str | None,          # Original EOA wallet
        'proxy': str | None,         # Polymarket proxy wallet
        'username': str | None,      # Polymarket username
        'method': str,               # How it was resolved
        'is_proxy': bool,            # Whether input was already proxy
        'has_traded': bool,          # Whether wallet has Polymarket activity
    }
    """
```

### Module 3: History (`core/history.py`)

```python
def get_all_closed_positions(proxy_wallet: str, force_refresh: bool = False) -> List[dict]:
    """
    Fetch ALL closed positions for a wallet with pagination.
    
    Pagination: offset=0,50,100,... until empty response
    Rate limit: 100ms delay between requests
    Caching: Save to data/known_wallets/{proxy[:10]}_positions.json
    Cache TTL: 5 minutes (configurable)
    
    Returns sorted by timestamp ascending.
    
    Fields: realizedPnl, title, outcome, avgPrice, totalBought,
            timestamp, slug, eventSlug, conditionId, asset, curPrice
    """

def get_open_positions(proxy_wallet: str) -> List[dict]:
    """
    Fetch current open positions with real-time values.
    Returns: title, outcome, size, avgPrice, curPrice, currentValue, cashPnl, percentPnl
    """

def get_pnl_history(proxy_wallet: str) -> dict:
    """
    Calculate cumulative PnL over time.
    
    Algorithm:
    1. Sort closed positions by timestamp ascending
    2. Running_total = sum(realizedPnl[0:i]) for each i
    3. Find peak, min, current
    
    Returns:
    {
        'peak': 811.73,          # All-time high
        'peak_trade': { title, pnl, timestamp },
        'min': -250.90,          # All-time low  
        'min_trade': { title, pnl, timestamp },
        'current': -249.79,      # Current PnL
        'total_positions': 551,
        'pnl_history': [
            { timestamp: 1700000000, cumulative_pnl: 100.50, trades: 10 },
            ...
        ],
        'recovery_count': 3,     # Times recovered from >$200 loss
        'max_drawdown': 1062.63, # Peak to trough
    }
    """

def get_user_activity_summary(proxy_wallet: str) -> dict:
    """
    Get activity summary including recent trades, deposits, withdrawals.
    
    Returns:
    {
        'total_trades': int,
        'total_volume': float,
        'recent_trades': List[dict],  # Last 30 days
        'avg_trade_size': float,
        'avg_daily_trades': float,
        'most_active_day': str,
        'last_active': timestamp,
    }
    """
```

### Module 4: Analyzer (`core/analyzer.py`) — THE CORE

```python
def analyze_wallet(proxy_wallet: str, detailed: bool = True) -> dict:
    """
    COMPLETE wallet analysis. 
    This is the flagship function of the entire system.
    
    Returns:
    {
        # === BASIC STATS ===
        'wallet': proxy_wallet,
        'eoa': eoa_wallet | None,
        'username': str | None,
        'total_positions': int,
        'total_volume': float,
        'total_pnl': float,
        'analyzed_at': timestamp,
        
        # === PERFORMANCE METRICS ===
        'win_rate': float,            # % of profitable trades
        'wins': int,
        'losses': int,
        'avg_win': float,             # Average profit per winning trade
        'avg_loss': float,            # Average loss per losing trade
        'profit_factor': float,       # gross_win / gross_loss (>1 = profitable)
        'expected_value': float,      # avg PnL per trade
        'sharpe_ratio': float,        # risk-adjusted returns
        'max_drawdown': float,        # peak-to-trough in USD
        'max_drawdown_pct': float,    # peak-to-trough as % of peak equity
        'recovery_factor': float,     # total PnL / max drawdown
        
        # === BIGGEST TRADES ===
        'biggest_win': { title, pnl, roi_pct, outcome, date },
        'biggest_loss': { title, pnl, roi_pct, outcome, date },
        'top_10_wins': List[dict],
        'worst_10_losses': List[dict],
        
        # === CATEGORY BREAKDOWN ===
        'categories': {
            'BTC_5m': {
                'positions': 430, 'pnl': 150.0, 'wins': 229, 'losses': 201,
                'win_rate': 53.3, 'profit_factor': 1.15
            },
            'Politics': { ... },
            'Sports': { ... },
            'Crypto': { ... },
            ...
        },
        'best_category': str,
        'worst_category': str,
        
        # === TEMPORAL ANALYSIS ===
        'temporal': {
            'hourly_performance': { 0: {trades, pnl, wr}, 1: {...}, ... 23: {...} },
            'daily_performance': { 'Monday': {trades, pnl, wr}, ... },
            'monthly_performance': { '2026-01': {...}, ... },
            'best_hour': int,
            'worst_hour': int,
            'best_day': str,
            'worst_day': str,
        },
        
        # === SIZE ANALYSIS ===
        'size_analysis': {
            'avg_position_size': float,
            'median_position_size': float,
            'min_position_size': float,
            'max_position_size': float,
            'size_brackets': {
                'small (<$50)': {count, pnl, wr},
                'medium ($50-200)': {count, pnl, wr},
                'large ($200-1000)': {count, pnl, wr},
                'whale (>$1000)': {count, pnl, wr},
            },
            'position_size_correlation': float,  # correlation between size and PnL
        },
        
        # === OUTCOME BIAS ===
        'outcome_bias': {
            'yes_no_ratio': 0.6,          # % of Yes vs No trades
            'yes_win_rate': 0.48,
            'no_win_rate': 0.52,
            'up_down_ratio': 0.55,        # % of Up vs Down (for BTC markets)
            'up_win_rate': 0.54,
            'down_win_rate': 0.46,
        },
        
        # === BOOK ANALYTICS === (Kalman Filter for edge detection)
        'edge_analysis': {
            'avg_edge_when_buying': float,    # Avg price improvement from entry
            'avg_slippage': float,
            'fills_at_our_price_pct': float,  # % of fills at exact limit price
            'avg_wait_time_for_fill': float,  # Seconds median
        },
        
        # === RISK METRICS ===
        'risk_metrics': {
            'var_95': float,              # Value at Risk (95% confidence)
            'var_99': float,              # Value at Risk (99% confidence)
            'consecutive_losses_max': int,
            'consecutive_wins_max': int,
            'avg_consecutive_losses': float,
            'avg_consecutive_wins': float,
            'loss_recovery_rate': float,  # % of drawdowns recovered from
        },
        
        # === STRATEGY FINGERPRINT ===
        'strategy': strategy_fingerprint(positions),
        
        # === SUMMARY ===
        'verdict': str,                   # "PROFITABLE", "BREAK-EVEN", "LOSING"
        'copy_trade_rating': int,         # 1-10 rating for copy trading suitability
        'red_flags': List[str],           # Things to watch out for
    }
    """


def analyze_wallet_rapid(proxy_wallet: str) -> dict:
    """
    LIGHTWEIGHT analysis (no full history fetch).
    Uses profile page + recent trades only.
    ~2 seconds vs ~30 seconds for full analysis.
    
    Returns: limited subset of analyze_wallet()
    """


def compare_wallets(wallets: List[str]) -> dict:
    """
    Compare multiple wallets side-by-side.
    
    Returns ranking table with: wallet, pnl, wr, volume, category,
    sharpe, strategy_type, copy_rating
    """
```

### Module 5: Scanner (`core/scanner.py`)

```python
def find_profitable_traders(
    min_volume: float = 1000.0,
    min_trades: int = 50,
    max_results: int = 50,
    sort_by: str = 'pnl',       # pnl | win_rate | sharpe | volume
) -> List[dict]:
    """
    Discover profitable Polymarket wallets.
    
    Discovery methods (multi-strategy):
    
    A) **Gamma API Market Participants**
       1. Fetch top volume markets from Gamma API
       2. For each market, fetch order book
       3. Extract maker addresses from order book
       4. These are active traders
    
    B) **Blockscout Whale Tracking**
       1. Query large PUSD transfers (>$10K)
       2. These are whales moving money
       3. Extract from/to addresses
    
    C) **Leaderboard / Top Traders**
       1. Check Polymarket leaderboard endpoints
       2. Parse public "Top Traders" if available
    
    D) **Known Profitable Wallets (seeded)**
       1. Start with known profitable wallets
       2. Follow their copy-cats
       3. Cross-reference with new wallets from A+B
    
    E) **Market Event Participants**
       1. For major events (elections, sports finals)
       2. Extract addresses that made large trades
       3. Check if they're consistently profitable
    
    Pipeline:
    1. Collect candidate addresses (all methods)
    2. Deduplicate
    3. For each: find proxy, fetch closed positions
    4. Run rapid analysis (Module 4)
    5. Rank by sort_by metric
    6. Cache results
    
    Returns: sorted list of wallet analyses with strategy fingerprints
    """


def scan_market_participants(market_slug: str, limit: int = 100) -> List[str]:
    """
    Get all participants of a specific market (wallets that traded).
    """


def track_whale_movements(min_usd: float = 10000.0, hours_back: int = 24) -> List[dict]:
    """
    Monitor on-chain movements of large traders.
    Detect: deposits, withdrawals, large position changes.
    """


def build_trader_network(central_wallet: str, depth: int = 2) -> dict:
    """
    Build a network graph of traders.
    - Who trades the same markets as central_wallet
    - Who has similar position changes
    - Overlapping strategy patterns
    Returns: graph with nodes=wallets, edges=similarity_score
    """
```

### Module 6: Strategy Fingerprint (`strategies/fingerprint.py`)

```python
def strategy_fingerprint(positions: List[dict]) -> dict:
    """
    Build a COMPREHENSIVE strategy profile from trading history.
    
    Factors analyzed (14 dimensions):
    
    1. **Category Preference**
       - What % of trades in each category
       - Primary category (where most trades are)
       - Secondary category (where most profit comes from)
    
    2. **Position Sizing**
       - Fixed vs variable sizing
       - Bet fraction of portfolio
       - Does size correlate with confidence?
    
    3. **Entry Timing**
       - Time-of-day patterns
       - Day-of-week patterns
       - Pre/post event patterns (e.g. trades right before news)
       - How long after market open do they enter?
    
    4. **Hold Duration**
       - Average hold time per category
       - Scalper (<1h) vs Swing (1h-1d) vs Position (>1d)
       - When do they exit? (trailing stop, take profit, expiration)
    
    5. **Win Rate Analysis**
       - Raw WR vs Risk-Adjusted WR
       - WR per category
       - WR by time of day
    
    6. **Profit Factor Decomposition**
       - What % of profit comes from 80% of trades (breadth)
       - What % from top 20% (concentration)
       - Luck vs skill analysis
    
    7. **Risk Profile**
       - Avg loss / avg win ratio
       - Max consecutive losses
       - How much are they willing to lose per trade?
       - Portfolio-level risk management
    
    8. **Outcome Preference**
       - Yes vs No bias
       - Up vs Down bias (for binary directional markets)
       - Do they buy the favorite or the underdog?
    
    9. **Price/Spread Sensitivity**
       - What price range do they trade in?
       - Do they chase or wait for better prices?
       - Spread tolerance
    
    10. **Market Entry Strategy**
        - Limit orders vs market orders
        - How far from midpoint?
        - Fill rate
    
    11. **Market Exit Strategy**
        - Do they take profit early or let it ride?
        - Do they cut losses quickly?
        - Auto-exit before expiration?
    
    12. **News/Event Responsiveness**
        - Trading activity spikes around events
        - Pre-event positioning
        - Post-event reaction trades
    
    13. **Capital Management**
        - How much of their capital is deployed
        - Position overlap (multiple positions in same market)
        - Hedging behavior
    
    14. **Pattern Reproducibility**
        - Are strategies consistent across time?
        - Strategy drift detection
        - Performance degradation over time
    
    Returns:
    {
        'strategy_type': str,           # 'SCALPER' | 'SWING' | 'POSITION' | 'WHALE' | 'HEDGER' | 'MIXED'
        'confidence': float,             # 0-1 how well-defined the strategy is
        'primary_category': 'BTC_5m',
        'primary_category_share': 0.78,  # 78% of trades in this category
        'avg_position_size': 250.0,
        'size_strategy': 'FIXED' | 'KELLY' | 'VARIABLE' | 'UNKNOWN',
        'win_rate': 53.3,
        'profit_factor': 1.1,
        'sharpe_ratio': 0.45,
        'avg_hold_time_hours': 4.5,
        'hold_style': 'SWING',
        'preferred_outcome': 'Up',
        'preferred_side': 'BUY',
        'avg_price_entry': 0.55,
        'limit_order_pct': 0.85,
        'fill_rate': 0.72,
        'max_consecutive_losses': 8,
        'recovery_ability': 0.7,        # 0-1
        'is_replicable': True,          # Can we replicate this?
        'replication_difficulty': 'MEDIUM',  # EASY | MEDIUM | HARD
        'copy_trade_suitability': 8,     # 1-10 rating
        
        # Detailed breakdowns
        'categories': { ... },          # Per-category performance
        'sizing_analysis': { ... },     # Size-related patterns
        'timing_analysis': { ... },     # Temporal patterns
        'entry_exit_analysis': { ... }, # Entry/exit behavior
        'risk_analysis': { ... },       # Risk metrics
        
        'red_flags': [
            'Only 10 trades total - too small sample',
            '50% win rate but profit_factor 0.8 - wins small, losses big',
            'Strategy changed completely after March 2026',
            'Only profitable because of 1 lucky trade (+$500)',
        ],
        'green_flags': [
            '500+ trades with consistent WR',
            'Low drawdown relative to PnL',
            'Replicates easily (single category, fixed sizing)',
        ],
    }
    """
```

### Module 7: Strategy Replication (`strategies/replication.py`)

```python
def replicate_strategy(source_wallet: str, our_capital: float) -> dict:
    """
    Generate an EXECUTABLE strategy from a wallet's fingerprint.
    
    This is NOT copy trading — it extracts the DECISION LOGIC.
    
    Steps:
    1. Full analysis + fingerprint of source wallet
    2. Decompose into rules:
       - "Enter BTC 5m Up when price < 0.40c"
       - "Exit at +20% or -15%"
       - "Only trade 07:00-09:00 UTC"
       - "Use 2% of capital per trade"
    3. Validate rules against historical data
    4. Generate executable strategy config
    5. Simulate on our capital (paper trade first)
    
    Returns:
    {
        'source_wallet': str,
        'strategy': strategy_fingerprint_dict,
        'rules': List[Rule],            # Executable rules
        'paper_results': {
            'total_trades': int,
            'win_rate': float,
            'pnl': float,
            'max_drawdown': float,
        },
        'config': {
            'markets': [category_or_list],
            'entry_conditions': List[Condition],
            'exit_conditions': List[Condition],
            'position_sizing': KellyConfig,
            'max_positions': int,
            'daily_budget': float,
            'allowed_hours': List[int],
        },
        'confidence_score': float,      # 0-1
        'is_ready_for_live': bool,
    }
    """


def generate_strategy_config(fingerprint: dict, capital: float) -> dict:
    """
    Generate executable strategy configuration from fingerprint.
    
    Output format compatible with core/trader.py
    """
```

### Module 8: Copy Trade Engine (`core/copytrade.py`)

```python
async def execute_copy_trade(source_wallet: str, max_size: float = 50.0):
    """
    Direct copy trading: mirror trades of profitable wallet.
    
    Pipeline:
    1. Fetch source wallet's recent closed positions (last 10)
    2. For each profitable position:
       a. Resolve market (conditionId, tokenId)
       b. Create order matching: market, outcome, price, size
       c. Apply risk controls
       d. Place order via CLOB API
    3. Track fills
    4. Report results
    
    Risk Controls (REQUIRED before placing any order):
    - Max position size: configurable (default $50)
    - Max daily loss: $100
    - Min source win rate: 40%
    - Min source total PnL: $500
    - Max open positions: 5
    - Min spread: 0.2 cents (avoid illiquid markets)
    - Min liquidity in order book: $500
    
    Edges Cases Handled:
    - Market already resolved → skip
    - Insufficient balance → skip
    - Order book has no liquidity → skip
    - Price moved since source entered → use current best
    - Source position was partial fill → use original size proportionally
    
    Returns: CopyTradeReport
    """


class CopyTradeDaemon:
    """
    Background daemon that monitors and copies trades.
    
    Config:
    - sources: List of profitable wallet addresses
    - polling_interval: 300 seconds (5 min)
    - max_copy_size: $50
    - max_daily_loss: $100
    
    State:
    - last_checked_positions: { source_wallet: [list_of_position_ids] }
    - tracked_wallets: metrics per source
    - daily_pnl_tracker
    
    Behavior:
    - Every polling_interval:
      1. Check each source for new closed positions
      2. Filter profitable ones (realizedPnl > 0)
      3. Check risk limits
      4. Execute copy trades
      5. Update state
    - On max daily loss hit: pause until next day
    - On circuit breaker: pause until manual resume
    """
```

### Module 9: Autonomous Trader (`core/trader.py`)

```python
class AutonomousTrader:
    """
    24/7 autonomous trading engine.
    
    Can operate in modes:
    1. STRATEGY_FOLLOWING — Follow a pre-defined strategy config
    2. COPY_TRADING — Mirror specific profitable wallets
    3. OPPORTUNITY — Detect and trade mispriced markets
    4. HYBRID — Combination of above
    
    Strategy Execution Pipeline:
    ```
    Market Feed → Opportunity Detection → Signal Generation
    → Risk Check → Order Placement → Fill Tracking → Journal
    ```
    
    Session Management:
    - Each strategy has optimal session hours
    - Auto-pause outside session hours
    - Auto-disable after 3 consecutive losses
    - Cool-down period after max daily loss hit
    
    Risk Management (MANDATORY):
    - Circuit breaker: -$50/day stops all trading
    - Position limits: max 5 concurrent positions
    - Market limits: max 2 positions in same market
    - Category limits: max 60% capital in single category
    - Kelly sizing with 0.25 fraction (quarter-Kelly)
    - Minimum liquidity check before order
    
    Logging:
    - Every signal logged with confidence score
    - Every order logged with full details
    - Every fill logged with execution quality
    - Daily PnL summary
    """
```

### Module 10: Opportunity Detection (`strategies/opportunity.py`)

```python
def scan_for_opportunities() -> List[dict]:
    """
    Real-time market opportunity scanning.
    
    Types of opportunities:
    
    1. **Price Discrepancy**
       - Same event, different outcome prices don't sum to 1
       - Mispriced due to stale order book
       - Arbitrage between Yes/No within same market
    
    2. **Momentum Detection**
       - Price moving rapidly in one direction
       - Follow momentum with entry/exit rules
    
    3. **Liquidity Gaps**
       - Wide spread = opportunity to provide liquidity
       - Place orders at midpoint
    
    4. **Event-Driven**
       - Major news breaks → prices haven't adjusted yet
       - Pre-event positioning opportunities
    
    5. **Emotional Trading**
       - After major event, market may overreact
       - Mean reversion trades
    
    Returns: List of opportunity dicts with:
    {
        'type': str,
        'market': dict,
        'expected_value': float,
        'confidence': float,
        'entry_price': float,
        'target_price': float,
        'stop_loss': float,
        'max_size': float,
        'time_horizon': str,
    }
    """


def resolve_market_odds(market: dict) -> dict:
    """
    Calculate true odds from order book.
    Uses mid-price, not just best bid/ask.
    Accounts for spread and depth.
    """
```

### Module 11: Risk Management (`risk/`)

```python
# === position_sizer.py ===

def kelly_criterion(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """
    Calculate optimal Kelly fraction.
    f* = (p * b - q) / b
    where p = win_rate, q = 1-p, b = avg_win/avg_loss
    
    Returns: fraction of capital (0-1)
    Always use quarter-Kelly: f* / 4
    """

def calculate_position_size(
    capital: float,
    confidence: float,
    market_liquidity: float,
    max_slippage: float,
) -> float:
    """
    Position sizing that accounts for:
    - Kelly optimal fraction
    - Confidence discount (lower confidence = smaller size)
    - Liquidity discount (less liquid = smaller size)
    - Slippage buffer
    - Hard limits (max $50, min $5)
    """


# === circuit_breaker.py ===

class CircuitBreaker:
    """
    Auto-pause mechanism to prevent runaway losses.
    
    States:
    - GREEN: Normal trading
    - YELLOW: Warning (3 consecutive losses)
    - RED: Stopped (max daily loss hit or -50% in week)
    
    Triggers:
    - 3 consecutive losses → YELLOW (reduce size 50%)
    - Max daily loss (-$50) → RED (stop until next day)
    - Max weekly loss (-$150) → RED (stop until manual resume)
    - Position PnL drops 20% → force close position
    
    Auto-reset:
    - YELLOW → GREEN after 1 winning trade
    - RED (daily) → GREEN next day
    - RED (weekly) → requires manual resume
    """


# === exposure_limits.py ===

def validate_trade(trade_config: dict, portfolio_state: dict) -> Tuple[bool, str]:
    """
    Pre-trade validation checklist:
    ✓ Capital: Have enough free capital
    ✓ Position limit: Not at max concurrent positions
    ✓ Market limit: Not already in this market
    ✓ Category limit: Not over-allocated in this category
    ✓ Daily loss: Haven't hit max daily loss
    ✓ Trading hours: Within allowed session
    ✓ Source quality: Source wallet still profitable
    ✓ Market health: Market not expired, has liquidity
    ✓ Spread: Within acceptable range
    ✓ Position size: Within min/max limits
    
    Returns: (valid: bool, reason: str)
    """


# === sanity_checks.py ===

def quick_sanity_check(market: dict) -> Tuple[bool, str]:
    """
    Fast pre-trade sanity check (~100ms).
    - Is the market still open?
    - Is there at least $100 in order book depth?
    - Is spread < 5 cents?
    - Has the market been traded in last 24h?
    - Is end date > 1 hour away?
    """

def deep_sanity_check(wallet: str, strategy: dict) -> Tuple[bool, List[str]]:
    """
    Deep validation of a copy trade source.
    - Wallet still active (traded in last 7 days)
    - Recent performance as good as historical
    - No sudden strategy change
    - No suspicious patterns (wash trading)
    - Wallet age > 30 days
    - At least 20 trades total
    """
```

### Module 12: Real-Time Monitoring (`monitor/`)

```python
# === tracker.py ===

class PnLTracker:
    """
    Real-time PnL tracking across all positions.
    
    Features:
    - Auto-refresh every 60 seconds
    - Current value of all open positions
    - Unrealized PnL
    - Realized PnL (from closed positions today)
    - Daily PnL
    - Total PnL (all time)
    - Graph/trend over time
    
    Output formats:
    - Console table
    - JSON (for bots/dashboard)
    - HTML dashboard
    """


# === alerts.py ===

class AlertSystem:
    """
    Multi-channel alerting system.
    
    Alert Events:
    - 🟢 New profitable trade executed
    - 🔴 Position stopped out (loss)
    - 🟡 Strategy paused (circuit breaker)
    - 🟠 Whale alert (large wallet activity detected)
    - 💰 Opportunity detected (mispriced market)
    - 📊 Daily PnL summary
    
    Channels:
    - Telegram (primary)
    - Console
    - JSON log
    - Push notifications
    
    Format:
    ```
    🟢 [1A-POLY-TRADER] New Trade
    Market: BTC Up or Down - May 19 (5m)
    Side: BUY Up
    Size: $25 @ 0.45¢
    Source: @profitable_wallet
    Oracle: EV +$0.32 | Confidence: 72%
    ```
    """


# === dashboard.py ===

def start_dashboard(port: int = 8080):
    """
    FastAPI web dashboard with real-time updates.
    
    Pages:
    / — Main dashboard
      - Portfolio overview (total PnL, open positions, balance)
      - Active strategies
      - Recent trades
      - Performance chart
    
    /wallets — Wallet analysis tool
      - Input: wallet address or username
      - Full analysis report
      - Strategy fingerprint
      - Similar traders
    
    /copy-trade — Copy trade management
      - Add/remove sources
      - Performance of each source
      - Copy trade history
    
    /strategies — Strategy browser
      - All discovered strategies
      - Filter by category, WR, PnL
      - Strategy details
    
    /scanner — Wallet scanner
      - Top traders leaderboard
      - Newly discovered wallets
      - Whale movements
    
    /settings — Configuration
      - API keys
      - Risk limits
      - Notification preferences
    
    Tech: FastAPI + HTMX (SSR, no JS framework)
    """


# === journal.py ===

class TradeJournal:
    """
    Complete trade journal (SQLite backend).
    
    Schema:
    CREATE TABLE trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        market_title TEXT,
        condition_id TEXT,
        token_id TEXT,
        outcome TEXT,
        side TEXT,           -- BUY / SELL
        order_type TEXT,     -- LIMIT / MARKET / FOK
        price REAL,
        size REAL,
        value REAL,
        fee REAL,
        status TEXT,         -- OPEN / FILLED / CANCELLED / EXPIRED
        order_id TEXT,
        fill_id TEXT,
        realized_pnl REAL,
        source_wallet TEXT,  -- For copy trades
        strategy TEXT,       -- Strategy identifier
        notes TEXT,
        created_at INTEGER DEFAULT (strftime('%s', 'now'))
    );
    
    Methods:
    - log_trade(trade_data) → trade_id
    - update_fill(order_id, fill_data) → updated
    - get_trades(filters={}) → list
    - get_daily_summary(date) → dict
    - get_strategy_performance(strategy_id) → dict
    - export_csv() → file path
    """
```

### Module 13: Real-Time Data Streaming (`streaming/`)

```python
# === websocket.py ===

class PolymarketWebSocket:
    """
    Real-time WebSocket connection to Polymarket.
    
    Connection: wss://ws-subscriptions-clob.polymarket.com/ws
    
    Subscription types:
    - Market prices (token_id)
    - Order book updates
    - User order fills
    - User position updates
    
    Reconnection:
    - Auto-reconnect on disconnect
    - Exponential backoff (1s, 2s, 4s, 8s, max 60s)
    - Re-subscribe on reconnect
    
    Heartbeat:
    - Send ping every 30 seconds
    - Expect pong within 10 seconds
    - Missed pong = reconnect
    """


# === pool_poller.py ===

class MarketPoller:
    """
    Polling-based market data (fallback when WebSocket unavailable).
    
    Polls Data API for specific markets every 5 seconds.
    
    Configurable:
    - Markets to watch (by token_id or slug)
    - Poll interval
    - On-change callback
    
    Efficient:
    - Batch requests when possible
    - Only process changed data
    - Skip stale markets (endDate in past)
    """
```

---

## 📊 MARKET CLASSIFICATION (15+ Categories)

```python
def classify_market(title: str, slug: str, event_slug: str, tags: List[str] = None) -> str:
    """
    Universal market classifier.
    
    Categories with classification logic:
    """
    t = (title + ' ' + slug + ' ' + event_slug + ' ' + ' '.join(tags or [])).lower()
    
    # === TIME-BASED BTC ===
    if 'bitcoin' in t and ('up or down' in t or '5m' in t or '1m' in t or '15m' in t):
        return 'BTC_5m'
    if 'bitcoin' in t or 'btc' in t:
        return 'BTC'
    
    # === CRYPTO ===
    if 'ethereum' in t or 'eth' in t:
        return 'ETH'
    if 'solana' in t or 'sol' in t:
        return 'SOL'
    if any(x in t for x in ['dogecoin','doge','shiba','pepe','xrp','cardano','ada',
                             'polkadot','dot','avalanche','avax','matic','polygon',
                             'chainlink','link','uniswap','uni','defi','crypto',
                             'token','altcoin','meme coin']):
        return 'Crypto_Alt'
    if 'bitcoin' in t and 'etf' in t:
        return 'BTC_ETF'
    
    # === POLITICS (US + International) ===
    if any(x in t for x in ['president','nominee','trump','biden','election',
                             'congress','senate','fetterman','massie','youngkin',
                             'ramaswamy','united russia','republican','democratic',
                             'governor','primary','2024','2025','2026','2028',
                             'electoral','swing state','gop','dnc']):
        return 'Politics_US'
    if any(x in t for x in ['prime minister','election','votes','referendum',
                             'parliament','coalition','presidential','regime',
                             'nato','eu ','european union','brexit','france','germany',
                             'uk ','britain','hungary','poland','turkey','india',
                             'japan','brazil','mexico','canada','australia']):
        return 'Politics_Global'
    
    # === GEOPOLITICS / WAR ===
    if any(x in t for x in ['iran','israel','ukraine','russia','china','war',
                             'ceasefire','sanction','nato','hormuz','strait',
                             'military','invasion','missile','nuclear','conflict',
                             'taiwan','gaza','houthi','hezbollah','hamas']):
        return 'Geopolitics'
    
    # === SPORTS ===
    sports_keywords = [
        'nba','nfl','mlb','nhl','soccer','football','tennis','cricket','boxing',
        'ufc','mma','golf','formula 1','f1','ncaa','champions league','premier league',
        'la liga','serie a','bundesliga','super bowl','world cup','olympics',
        'grand slam','wimbledon','us open','australian open','french open',
        'match','game','handicap','championship','playoff','series','medal',
        'race','driver','champion','title','round','bout','fight','knockout',
    ]
    if any(x in t for x in sports_keywords):
        # Sub-classify sport type
        if any(x in t for x in ['nba','basketball','ncaa']):
            return 'Sports_Basketball'
        if any(x in t for x in ['nfl','football','super bowl']):
            return 'Sports_NFL'
        if any(x in t for x in ['soccer','premier league','champions league',
                                 'la liga','serie a','bundesliga','world cup']):
            return 'Sports_Soccer'
        return 'Sports_Other'
    
    # === ENTERTAINMENT / CULTURE ===
    if any(x in t for x in ['eurovision','eurovision 2025','song contest',
                             'sweden','finland','bulgaria','croatia',
                             'jury','televote','grand final']):
        return 'Eurovision'
    if any(x in t for x in ['oscar','grammy','emmy','academy award','mtv',
                             'billboard','golden globe','tony']):
        return 'Entertainment_Awards'
    if any(x in t for x in ['album','song','music','concert','tour','spotify',
                             'stream','release','debut','rihanna','taylor',
                             'beyonce','kanye','weeknd','bad bunny','drake']):
        return 'Entertainment_Music'
    if any(x in t for x in ['movie','film','box office','marvel','dc','disney',
                             'netflix','hbo','streaming','cinema']):
        return 'Entertainment_Film'
    if any(x in t for x in ['mrbeast','elon musk','celebrity','influencer',
                             'youtube','tiktok','twitch','podcast']):
        return 'Entertainment_Media'
    
    # === TECH / SCIENCE ===
    if any(x in t for x in ['gemini','spacex','starship','nasa','space',
                             'rocket','launch','satellite','moon','mars']):
        return 'Tech_Space'
    if any(x in t for x in ['ipo','acquisition','merger','startup','venture',
                             'silicon valley','google','apple','meta','amazon',
                             'microsoft','nvidia','tesla','openai','anthropic',
                             'ai','artificial intelligence','robot','automation',
                             'chatgpt','gpt','llm','model']):
        return 'Tech_AI'
    if any(x in t for x in ['bitcoin etf','crypto regulation','sec','cfpb',
                             'fincen','bill','law','court','supreme court',
                             'lawsuit','regulation','ban','legal']):
        return 'Regulation'
    
    # === FINANCE / ECONOMICS ===
    if any(x in t for x in ['fed','federal reserve','interest rate','rate cut',
                             'rate hike','inflation','cpi','gdp','recession',
                             'stock','spx','nasdaq','dow','s&p','earnings',
                             'microstrategy','treasury','yield','bond']):
        return 'Finance'
    
    # === WEATHER / CLIMATE ===
    if any(x in t for x in ['temperature','celsius','fahrenheit','weather',
                             'hurricane','tornado','flood','storm','climate',
                             'global warming','heat','snow','rain']):
        return 'Weather'
    
    # === SCIENCE / HEALTH ===
    if any(x in t for x in ['covid','vaccine','pandemic','virus','drug','fda',
                             'medical','health','obesity','longevity','clinical',
                             'trial','cure','treatment']):
        return 'Science_Health'
    if any(x in t for x in ['nobel','physics','chemistry','biology','math',
                             'discovery','invention','patent','research']):
        return 'Science'
    
    # === TECH (General) ===
    if any(x in t for x in ['gta','grand theft auto','nintendo','playstation',
                             'xbox','video game','gaming','esports','steam',
                             'nft','metaverse']):
        return 'Entertainment_Gaming'
    
    return 'Other'
```

---

## 💰 BACKTESTING ENGINE (`strategies/backtest.py`)

```python
class BacktestEngine:
    """
    Backtest strategies on historical Polymarket data.
    
    Capabilities:
    - Simulate strategy on historical positions
    - Account for: slippage, spread, liquidity
    - Generate: PnL curve, max drawdown, Sharpe, Calmar ratio
    - Compare multiple strategies side-by-side
    - Walk-forward optimization
    
    Data Sources:
    - Historical prices from price-history endpoint
    - Historical order book snapshots
    - Reconstructed from position history
    
    Output:
    - PnL chart (ASCII/matplotlib)
    - Performance statistics
    - Trade-by-trade breakdown
    - Comparison report
    
    Example:
    ```
    $ python backtest_strategy.py --wallet 0xPROFITABLE --mode walkforward --periods 4
    
    WALK-FORWARD BACKTEST: @profitable_wallet
    ┌─────────────────┬────────┬────────┬────────┬────────┬──────┐
    │ Metric          │ Period1│ Period2│ Period3│ Period4│ Avg  │
    ├─────────────────┼────────┼────────┼────────┼────────┼──────┤
    │ Win Rate        │ 54.1%  │ 55.2%  │ 51.8%  │ 52.5%  │ 53.4%│
    │ Profit Factor   │ 1.15   │ 1.18   │ 1.08   │ 1.12   │ 1.13 │
    │ Sharpe          │ 0.52   │ 0.58   │ 0.38   │ 0.45   │ 0.48 │
    │ Max DD          │ -$120  │ -$95   │ -$180  │ -$140  │ -$134│
    │ Trades          │ 125    │ 130    │ 118    │ 122    │ 124  │
    └─────────────────┴────────┴────────┴────────┴────────┴──────┘
    Verdict: Strategy ROBUST (no period overfitting)
    Confidence: 78% — safe to trade
    ```
    """
```

---

## 🚀 CLI COMMANDS (main.py)

```bash
# ────────── ANALYSIS ──────────

# Full wallet analysis
python main.py analyze 0x46029b13381D0cd207C56D4Ba968035b7e92F209

# Analyze by Polymarket username
python main.py analyze berkah-karya

# Rapid analysis (no full history)
python main.py analyze --rapid @username

# Compare multiple wallets
python main.py compare 0xWALLET1 0xWALLET2 0xWALLET3

# ────────── SCANNING ──────────

# Scan for profitable traders
python main.py scan --min-profit 500 --limit 20

# Scan specific category
python main.py scan --category BTC_5m --min-trades 50

# Discover wallets that trade same markets as target
python main.py scan --similar-to 0xWALLET

# ────────── STRATEGIES ──────────

# Strategy fingerprint of a wallet
python main.py fingerprint 0xWALLET

# Replicate strategy (extract decision logic)
python main.py replicate 0xPROFITABLE_WALLET

# Backtest a strategy
python main.py backtest --wallet 0xWALLET --period 90d

# List all known strategies
python main.py strategies list

# Show strategy details
python main.py strategies show BTC_5m_mean_reversion

# ────────── TRADING ──────────

# Start copy trade daemon
python main.py copytrade --source 0xPROFITABLE_WALLET --max-size 50

# Multiple sources
python main.py copytrade --sources-file sources.json

# Autonomous trading mode
python main.py trade --strategy configs/btc_5m_scalper.json

# Paper trade (no real money)
python main.py trade --paper --strategy configs/btc_5m_scalper.json

# ────────── MONITORING ──────────

# Live PnL tracker
python main.py monitor --refresh 60

# PnL chart
python main.py pnl 0xWALLET

# Start web dashboard
python main.py dashboard --port 8080

# Trade journal
python main.py journal today
python main.py journal --from 2026-01-01 --to 2026-05-18

# ────────── PORTFOLIO ──────────

# Check our own portfolio
python main.py portfolio

# Check available balance
python main.py balance

# Open positions summary
python main.py positions

# ────────── OPPORTUNITIES ──────────

# Scan for opportunities
python main.py opportunities

# Real-time opportunity monitor
python main.py opportunities --watch

# ────────── UTILITY ──────────

# Resolve wallet from any input
python main.py resolve 0xWALLET
python main.py resolve @username

# Find proxy wallet
python main.py proxy 0xEOA_WALLET

# Link checker
python main.py check-link 0xEOA_WALLET  # Does EOA → proxy mapping exist?

# One-time setup (approvals)
python main.py setup-approvals

# Withdraw USDC
python main.py withdraw --amount 100 --to 0xTARGET
```

---

## 🔐 CONFIG (config.py)

```python
import os
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class WalletConfig:
    """Primary wallet configuration."""
    primary_eoa: str = "0x46029b13381D0cd207C56D4Ba968035b7e92F209"
    primary_proxy: Optional[str] = None  # Auto-detected
    polymarket_username: str = "berkah-karya"

@dataclass
class PolymarketConfig:
    """Polymarket credentials and endpoints."""
    private_key: str = os.getenv('POLYMARKET_PRIVATE_KEY', '')
    wallet_address: str = os.getenv('POLYMARKET_WALLET_ADDRESS', '')
    builder_api_key: str = os.getenv('POLYMARKET_BUILDER_API_KEY', '')
    builder_secret: str = os.getenv('POLYMARKET_BUILDER_SECRET', '')
    builder_passphrase: str = os.getenv('POLYMARKET_BUILDER_PASSPHRASE', '')
    builder_address: str = os.getenv('POLYMARKET_BUILDER_ADDRESS', '')
    
    # API endpoints
    clob_url: str = "https://clob.polymarket.com"
    gamma_url: str = "https://gamma-api.polymarket.com"
    data_url: str = "https://data-api.polymarket.com"
    blockscout_url: str = "https://polygon.blockscout.com/api/v2"
    
    # Chain
    chain_id: int = 137
    rpc_url: str = "https://polygon-bor-rpc.publicnode.com"
    
    # Contract addresses
    pusd_address: str = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
    usdc_address: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    ctf_address: str = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
    exchange_main: str = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
    exchange_neg_risk: str = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
    neg_risk_adapter: str = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"

@dataclass
class RiskConfig:
    """Risk management limits."""
    max_position_size_usd: float = 50.0
    min_position_size_usd: float = 5.0
    max_daily_loss_usd: float = 100.0
    max_weekly_loss_usd: float = 300.0
    max_open_positions: int = 5
    max_per_market: int = 2
    max_per_category_pct: float = 0.60  # 60% max in single category
    kelly_fraction: float = 0.25  # Quarter-Kelly
    
    # Circuit breaker
    consecutive_losses_yellow: int = 3
    consecutive_losses_red: int = 5
    position_stop_loss_pct: float = 0.20  # Force close at -20%

@dataclass
class CopyTradeConfig:
    """Copy trading settings."""
    min_source_win_rate: float = 40.0  # %
    min_source_pnl: float = 500.0  # USD
    min_source_trades: int = 20
    max_copy_per_source: int = 3  # Max concurrent positions per source
    polling_interval: int = 300  # Seconds
    auto_remove_stale_sources: bool = True
    stale_days: int = 14

@dataclass
class ScanConfig:
    """Scanner configuration."""
    min_volume: float = 1000.0
    min_trades: int = 50
    max_results: int = 50
    scan_interval: int = 3600  # Re-scan every hour
    whale_threshold: float = 10000.0  # $10K

@dataclass
class MonitorConfig:
    """Monitoring and logging."""
    refresh_interval: int = 60  # Seconds
    alert_channels: List[str] = field(default_factory=lambda: ['telegram', 'console'])
    log_level: str = "INFO"
    trade_journal_db: str = "data/trade_journal.sqlite"
    dashboard_port: int = 8080

@dataclass
class AppConfig:
    """Root configuration."""
    wallet: WalletConfig = field(default_factory=WalletConfig)
    polymarket: PolymarketConfig = field(default_factory=PolymarketConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    copy_trade: CopyTradeConfig = field(default_factory=CopyTradeConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
```

---

## 🧪 VERIFICATION / TEST DATA

Use @berkah-karya wallet as test case:

```python
WALLET_EOA = "0x46029b13381D0cd207C56D4Ba968035b7e92F209"
WALLET_PROXY = "0xad85c2f3942561afa448cbbd5811a5f7e2e3c6bd"
WALLET_USERNAME = "berkah-karya"

# ===== EXPECTED VERIFICATION RESULTS =====

# Profile Data (from __NEXT_DATA__):
{
    'name': 'Berkah Karya',
    'trades': 551,
    'volume': 12153.0,     # Approx, depends on current
    'pnl': -249.79,         # As of last check (was -249.79)
    'biggest_win': 287.50,   # BTC 5m Up
}

# Full Analysis (from closed-positions API):
{
    'total_positions': 551,
    'total_pnl': -249.79,
    'peak_pnl': 811.73,       # ALL TIME HIGH
    'min_pnl': -250.90,      # ALL TIME LOW
    'win_rate': 47.2,        # 260 wins / 291 losses
    'wins': 260,
    'losses': 291,
    'profit_factor': 0.92,   # Slightly negative
    'biggest_win': {'title': 'Bitcoin Up or Down - 5m window', 'pnl': 287.50},
    'biggest_loss': {'title': 'Bitcoin Up or Down - 5m window', 'pnl': -150.0},
    
    # Category breakdown
    'categories': {
        'BTC_5m': {'positions': 430, 'pnl': 150.0, 'wr': 53.3},
        'Politics': {'positions': 50, 'pnl': -300.0, 'wr': 14.0},
        'Sports': {'positions': 30, 'pnl': -50.0, 'wr': 40.0},
    },
    
    'best_category': 'BTC_5m',
    'worst_category': 'Politics',
    'key_insight': 'BTC_5m is profitable (53.3% WR), Politics is -85.7% WR'
}
```

---

## 🚫 CRITICAL DO-NOT RULES

| Rule | Reason |
|---|---|
| ❌ Do NOT hardcode private keys | Security — use env vars always |
| ❌ Do NOT use local DB as data source | It's wrong/stale — always use APIs |
| ❌ Do NOT use `/activity` for PnL | Returns cumulative data, not position-level |
| ❌ Do NOT build headless browser dependency | Slower, fragile — use APIs directly |
| ❌ Do NOT trade without risk checks | Losses compound fast |
| ❌ Do NOT deploy copy trade without paper test first | Validate before risking real money |
| ❌ Do NOT put the CLOB private key in git | Use .env, .envrc, or secrets manager |
| ❌ Do NOT use py-clob-client v1 | It's deprecated/archived — use v2 |
| ❌ Do NOT YOLO position sizes | Quarter-Kelly at absolute max |
| ❌ Do NOT ignore edge cases | Handle empty responses, rate limits, timeouts |

---

## 📈 ERROR HANDLING PATTERNS

```python
# === API Retry Pattern ===
async def api_call_with_retry(
    fn: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
) -> Any:
    """
    Retry API calls with exponential backoff.
    
    Retry on: ConnectionError, Timeout, HTTP 429, HTTP 5xx
    Do NOT retry on: HTTP 4xx (client errors), JSON parse errors
    """
    for attempt in range(max_retries):
        try:
            return await fn()
        except (ConnectionError, asyncio.TimeoutError) as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (backoff ** attempt)
            logger.warning(f"Retry {attempt+1}/{max_retries} in {delay}s: {e}")
            await asyncio.sleep(delay)
        except HTTPStatusError as e:
            if e.response.status_code == 429:
                retry_after = int(e.response.headers.get('Retry-After', base_delay))
                await asyncio.sleep(retry_after)
                continue
            elif e.response.status_code >= 500:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(delay)
            else:
                raise  # 4xx = don't retry


# === Edge Cases to ALWAYS Handle ===

# 1. Empty wallet (no activity)
positions = await get_all_closed_positions(wallet)
if not positions:
    return {"wallet": wallet, "status": "NO_ACTIVITY"}
    # Differentiate: "never used" vs "privacy mode"

# 2. Rate limit
# Blockscout: no key needed but rate-limited
# Data API: no observed limits but be polite with 100ms delays

# 3. Wallet not found
# Blockscout returns empty array if no transactions
# Profile page returns 404 if username doesn't exist

# 4. Market expired
# endDate in past → skip trading, analysis is still valid
# For closed markets, price is final settlement price (0 or 1)

# 5. Insufficient balance
# Check pUSD balance BEFORE placing any order
# Check MATIC balance (gas) BEFORE any on-chain tx

# 6. Order book too thin
# Check total order book depth before placing order
# Skip if depth < $100

# 7. No proxy wallet found
# Some EOA wallets don't have proxy (never used Polymarket)
# Return: "NO_PROXY" status

# 8. CLOB authentication fails
# Try re-creating API creds
# Check private key validity
# Check funder address matches proxy wallet

# 9. Python version / dependency issues
# The py-clob-client requires Python 3.9+
# Use venv to isolate dependencies
# Fall back to direct HTTP calls if client fails
```

---

## 🔄 INTEGRATION POINTS

### With 1A-MCP / BerkahKarya Ecosystem

```python
# === Integration via CLI ===
# Other systems can call 1a-poly-trader as a subprocess:
#   python main.py analyze 0xWALLET --json
#   python main.py scan --json

# === Integration via Python API ===
from core.analyzer import analyze_wallet
result = analyze_wallet("0xWALLET")

from core.copytrade import execute_copy_trade
await execute_copy_trade("0xSOURCE", max_size=25.0)

# === Integration via FastAPI ===
# Dashboard automatically exposes REST API:
# GET /api/analyze/{wallet}
# GET /api/scan?min_pnl=500
# POST /api/copy-trade
# GET /api/portfolio
```

### With BerkahKarya Quant Fund

```python
# Polymarket PnL feeds into overall BerkahKarya PnL tracking
# Strategies can be adapted from Polymarket to XAUUSD (same EV/Kelly math)
# Wallet intelligence models can be retrained for Deriv binary options
```

---

## 📋 DEVELOPMENT PRIORITY

```
Phase 1 — Foundation (Critical Path)
├── Wallet Resolver (username → EOA → proxy)
├── History Fetcher (closed positions with pagination)
├── Analyzer (PnL, WR, basic metrics)
└── Market Classifier

Phase 2 — Intelligence
├── Strategy Fingerprint (14 dimensions)
├── Wallet Scanner (discovery)
├── PnL History + Visualization
└── Wallet Comparison

Phase 3 — Execution
├── CLOB Auth Integration
├── Copy Trade Engine (with risk controls)
├── Circuit Breaker
└── Trade Journal

Phase 4 — Advanced
├── Strategy Replication (not just copy)
├── Backtesting Engine
├── Real-Time Streaming (WebSocket)
├── Opportunity Detection
└── Web Dashboard

Phase 5 — Autonomous
├── Autonomous Trader Daemon
├── Multi-Wallet Portfolio Management
├── Whale Tracking and Alerts
├── Strategy Marketplace (discover → replicate → deploy)
└── Full Integration with BerkahKarya Ecosystem
```

---

> **Last Updated:** 2026-05-19
> **Target:** v2.0 — Autonomous Polymarket Intelligence & Trading Platform
> **Test Wallet:** @berkah-karya (0xad85c2f3942561afa448cbbd5811a5f7e2e3c6bd)
> **All-Time Verification:** Peak +$811.73 | Min -$250.90 | BTC_5m profitable
