# PolyEdge Comprehensive Integration Plan

## Executive Summary

Integrate 4 DEXes (Hyperliquid, Ostium, Aster, Lighter) and complete 5 prediction market integrations (SX.bet, Myriad, Bookmaker.xyz, Limitless, Predict.fun) into 1ai-poly-trader. Total: 9 new venues.

---

## Phase 1: Shared Infrastructure (Day 1)

### 1A. EIP-712 Signing Module
**File**: `backend/core/eip712_signer.py` (NEW)

Build shared signing utility used by SX.bet, Limitless, and future EVM-based venues.

```python
# Core function
def sign_typed_data(private_key: str, domain: dict, types: dict, message: dict) -> str:
    """Generic EIP-712 typed data signing using eth_account."""
    account = Account.from_key(private_key)
    # Use eth_account's sign_transaction or raw signing
    return signature
```

**Reusable infrastructure already in place:**
- `eth_account.Account.from_key()` — imported in 5 files
- `WalletRouter.decrypt_key()` — Fernet decryption of stored private keys
- `TradingWallet` ORM model — encrypted key storage with chain/address fields
- `py_clob_client_v2` EIP-712 domain constants — reference pattern

**Dependencies**: `eth_account` (already installed)

### 1B. Update Wallet Model
**File**: `backend/models/trading_wallet.py`

Add chain values: `"sxbet"`, `"limitless"`, `"ostium"`, `"aster"`, `"lighter"`, `"hyperliquid"`

### 1C. Requirements.txt Updates
```
hyperliquid-python-sdk>=0.23.0
ostium-python-sdk>=3.2.0
lighter-sdk
ccxt>=4.5.0
```

---

## Phase 2: Prediction Markets — Complete Stubs (Days 2-3)

### 2A. Myriad Markets (EASIEST — just config)
**Status**: Most complete integration, REST API fully functional
**Files**: `backend/clients/myriad_client.py`, `backend/markets/providers/myriad_provider.py`
**Action**: Add `MYRIAD_API_URL=https://api.myriad.markets` to .env
**Blocker**: None — all methods implemented
**Test**: Verify `get_balance()`, `get_positions()`, `place_order()`, `cancel_order()` work

### 2B. SX.bet (MEDIUM — EIP-712 signing)
**Status**: Reads work, order placement stubbed
**Files**: `backend/clients/sxbet_client.py`, `backend/markets/providers/sxbet_provider.py`
**Action**:
1. Import `sign_typed_data` from `backend/core/eip712_signer.py`
2. Implement `place_maker_order()` with EIP-712 signing
3. Domain: Polygon chain_id=137, SX.bet contract address
**Blocker**: Need SX.bet EIP-712 domain struct (name, version, chainId, verifyingContract)
**Env vars**: `SXBET_API_URL`, `SXBET_WALLET_ADDRESS`, `SXBET_PRIVATE_KEY`

### 2C. Limitless Exchange (MEDIUM — EIP-712 signing)
**Status**: Reads work, order placement stubbed
**Files**: `backend/clients/limitless_client.py`, `backend/markets/providers/limitless_provider.py`
**Action**:
1. Import `sign_typed_data` from `backend/core/eip712_signer.py`
2. Implement `place_order()` and `cancel_order()` with EIP-712 signing
3. Domain: Base chain_id=8453, Limitless contract address
**Blocker**: Need Limitless EIP-712 domain struct
**Env vars**: `LIMITLESS_API_URL`, `LIMITLESS_WALLET_ADDRESS`, `LIMITLESS_PRIVATE_KEY`
**Bonus**: WebSocket at `wss://ws.limitless.exchange` for real-time data

### 2D. Bookmaker.xyz + Predict.fun (HARD — Azuro Protocol)
**Status**: Reads via GraphQL, order placement stubbed (same code)
**Files**: `backend/clients/azuro_client.py`, `backend/markets/providers/bookmaker_xyz_provider.py`, `backend/markets/providers/predict_fun_provider.py`
**Action**:
1. Get Azuro LP contract ABI from Azuro Protocol docs
2. Implement `sign_and_send_bet()` with real Web3 contract call
3. Both platforms share `AzuroClient` — fix once, works for both
**Blocker**: Need Azuro LP contract ABI + liquidity pool address
**Env vars**: `AZURO_GRAPH_URL`, `AZURO_RPC_URL`, `AZURO_PRIVATE_KEY`
**Chain**: Gnosis (xDai) chain_id=100

---

## Phase 3: DEXes — New Integrations (Days 4-8)

### 3A. Hyperliquid (EASIEST DEX — SDK installed)
**Status**: Data client exists (`backend/data/hyperliquid_client.py`), no market provider
**Files**: `backend/clients/hyperliquid_client.py` (NEW), `backend/markets/providers/hyperliquid_provider.py` (NEW)
**Action**:
1. Create client using `hyperliquid-python-sdk` v0.23.0
2. Use `Exchange` class for order placement, `Info` class for data
3. Create market provider implementing `BaseMarketProvider`
**SDK methods**:
- `Exchange.order(asset, is_buy, sz, limit_price, order_type)` — place order
- `Exchange.cancel(asset, order_id)` — cancel order
- `Exchange.bulk_orders(asset, orders)` — batch orders
- `Info.user_state(address)` — balance/positions
- `Info.open_orders(address)` — active orders
- `Info.meta()` — market metadata
**Env vars**: `HYPERLIQUID_PRIVATE_KEY`, `HYPERLIQUID_WALLET_ADDRESS`
**Chain**: Hyperliquid L1 (own chain)

### 3B. Ostium (NEW — Python SDK available)
**Status**: No integration, SDK v3.2.1 on PyPI
**Files**: `backend/clients/ostium_client.py` (NEW), `backend/markets/providers/ostium_provider.py` (NEW)
**Action**:
1. `pip install ostium-python-sdk`
2. Create client wrapping `OstiumSDK`
3. Create market provider implementing `BaseMarketProvider`
**SDK methods**:
- `sdk.ostium.perform_trade(params, at_price)` — open market/limit/stop
- `sdk.ostium.close_trade(pair_id, trade_index)` — close position
- `sdk.ostium.update_tp(pair_id, trade_index, price)` — set TP
- `sdk.ostium.update_sl(pair_id, trade_index, price)` — set SL
- `sdk.ostium.cancel_limit_order(pair_id, index)` — cancel
- `sdk.balance.get_balance()` — account balance
- `sdk.subgraph.get_open_trades(address)` — positions
- `sdk.subgraph.get_orders(address)` — open orders
- `sdk.price.get_price(base, quote)` — live prices
**25 pairs**: BTC, ETH, EUR, GBP, JPY, Gold, Silver, Copper, Crude Oil, SOL, S&P 500, Dow Jones, NASDAQ, Nikkei, FTSE, DAX, USD-CAD, USD-MXN, NVDA, GOOG, AMZN, META, TSLA, AAPL, MSFT
**Env vars**: `OSTIUM_PRIVATE_KEY`, `OSTIUM_RPC_URL`
**Chain**: Arbitrum (Ethereum L2)

### 3C. Aster DEX (EASY — CCXT native support)
**Status**: No integration, CCXT has native `aster` exchange class
**Files**: `backend/clients/aster_client.py` (NEW), `backend/markets/providers/aster_provider.py` (NEW)
**Action**:
1. Use `ccxt.aster()` with wallet private key
2. Same API structure as Binance — reuse Binance patterns
3. Create market provider implementing `BaseMarketProvider`
**CCXT usage**:
```python
exchange = ccxt.aster({
    'privateKey': '0x...',
    'options': {'defaultType': 'swap'},
})
order = exchange.create_order('BTC/USDT:USDT', 'limit', 'buy', 0.01, 50000)
balance = exchange.fetch_balance()
positions = exchange.fetch_positions()
```
**Auth**: ECDSA secp256k1 (NOT HMAC like Binance)
**Env vars**: `ASTER_PRIVATE_KEY`, `ASTER_WALLET_ADDRESS`
**Chain**: Aster Chain (chain_id=1666, DEX)
**Fees**: Maker 0.01%, Taker 0.035% (cheaper than Binance)

### 3D. Lighter (MEDIUM — Python SDK available)
**Status**: No integration, `lighter-sdk` available
**Files**: `backend/clients/lighter_client.py` (NEW), `backend/markets/providers/lighter_provider.py` (NEW)
**Action**:
1. `pip install lighter-sdk`
2. Create client using `SignerClient` for trading, `AccountApi` for reads
3. Create market provider implementing `BaseMarketProvider`
**SDK usage**:
```python
from lighter import SignerClient, AccountApi, Configuration, ApiClient

config = Configuration(host="https://mainnet.zklighter.elliot.ai/api/v1")
client = ApiClient(config)
account_api = AccountApi(client)
signer = SignerClient(private_key, account_index, api_key_index)

# Place order
signer.create_order(market_id, side, size, price, order_type, time_in_force)
# Cancel
signer.cancel_order(market_id, order_id)
# Send signed tx
TransactionApi(client).send_tx(signer.sign_create_order(...))
```
**Key details**:
- Price/size as integers (use `orderBookDetails` for decimals)
- Per-API-key nonce management
- Auth token generation for REST/WS (max 8h expiry)
- Zero fees for Standard accounts
**Env vars**: `LIGHTER_PRIVATE_KEY`, `LIGHTER_ACCOUNT_INDEX`, `LIGHTER_API_KEY_INDEX`
**Chain**: Ethereum L2 (ZK-proof)

---

## Phase 4: Wire Data Feeds (Day 9)

### 4A. DuneAnalytics → AGI Orchestrator
**File**: `backend/core/agi_orchestrator.py`
**Action**: Import `DuneAnalyticsClient`, wire 4 pre-built Polymarket queries into AGI decision engine
**Queries**: Volume, liquidity, market efficiency, settlement timing

### 4B. NewsCollector → Sentiment Engine
**File**: `backend/core/sentiment_engine.py` or `backend/strategies/agi_meta_strategy.py`
**Action**: Import `NewsCollector`, call `scored_to_context()` for debate injection
**Currently**: Completely unused, has HuggingFace dataset fetch + SentimentAnalyzer

### 4C. Orphaned Feeds Decision
**Files**: `simmer_client.py`, `polymeteo.py`, `polynimbus.py`, `clob_event_indexer.py`, `parquet_archiver.py`, `goldsky_client.py`
**Action**: Either wire into strategies or mark as deprecated with docstring

---

## Phase 5: Tests & Verification (Day 10)

### 5A. Unit Tests
- Test each new client's `place_order()`, `cancel_order()`, `get_balance()`, `get_positions()`
- Test EIP-712 signing with known test vectors
- Test CCXT Aster integration

### 5B. Integration Tests
- Test paper mode for each new provider
- Test live API connectivity (read-only)
- Test WebSocket connections

### 5C. Full Suite
- Run `pytest tests/` — target 0 failures, 0 errors
- Verify all providers register via `market_registry.auto_discover()`

---

## Dependency Matrix

| Platform | SDK | Auth | Chain | Difficulty |
|---|---|---|---|---|
| Myriad | Custom REST | API key | Polygon | Easy (config only) |
| SX.bet | Custom REST | EIP-712 | Polygon | Medium |
| Limitless | Custom REST | EIP-712 | Base | Medium |
| Bookmaker/Predict | Azuro GraphQL | Web3 contract | Gnosis | Hard |
| Hyperliquid | `hyperliquid-python-sdk` | EIP-712 | Hyperliquid L1 | Easy |
| Ostium | `ostium-python-sdk` | Web3 private key | Arbitrum | Easy |
| Aster | CCXT `aster` | ECDSA secp256k1 | Aster Chain | Easy |
| Lighter | `lighter-sdk` | API key signing | Ethereum L2 | Medium |

---

## Environment Variables Needed

```bash
# Prediction Markets (new)
SXBET_API_URL=https://api.sx.bet
SXBET_WALLET_ADDRESS=
SXBET_PRIVATE_KEY=

MYRIAD_API_URL=https://api.myriad.markets

LIMITLESS_API_URL=https://api.limitless.exchange
LIMITLESS_WALLET_ADDRESS=
LIMITLESS_PRIVATE_KEY=

AZURO_GRAPH_URL=https://api.thegraph.com/subgraphs/name/azuro-protocol/azuro-v2-gnosis
AZURO_RPC_URL=https://rpc.gnosis.gateway.fm
AZURO_PRIVATE_KEY=

# DEXes (new)
HYPERLIQUID_PRIVATE_KEY=
HYPERLIQUID_WALLET_ADDRESS=

OSTIUM_PRIVATE_KEY=
OSTIUM_RPC_URL=https://arb1.arbitrum.io/rpc

ASTER_PRIVATE_KEY=
ASTER_WALLET_ADDRESS=

LIGHTER_PRIVATE_KEY=
LIGHTER_ACCOUNT_INDEX=
LIGHTER_API_KEY_INDEX=
```

---

## Files to Create/Modify

### New Files (8)
1. `backend/core/eip712_signer.py` — shared EIP-712 signing
2. `backend/clients/hyperliquid_client.py` — Hyperliquid trading client
3. `backend/clients/ostium_client.py` — Ostium trading client
4. `backend/clients/aster_client.py` — Aster trading client (CCXT wrapper)
5. `backend/clients/lighter_client.py` — Lighter trading client
6. `backend/markets/providers/hyperliquid_provider.py` — Hyperliquid market provider
7. `backend/markets/providers/ostium_provider.py` — Ostium market provider
8. `backend/markets/providers/aster_provider.py` — Aster market provider
9. `backend/markets/providers/lighter_provider.py` — Lighter market provider

### Modified Files (7)
1. `backend/clients/sxbet_client.py` — implement EIP-712 signing
2. `backend/clients/limitless_client.py` — implement EIP-712 signing
3. `backend/clients/azuro_client.py` — implement real bet placement
4. `backend/markets/providers/sxbet_provider.py` — wire signing
5. `backend/markets/providers/limitless_provider.py` — wire signing
6. `backend/markets/providers/bookmaker_xyz_provider.py` — wire bet placement
7. `backend/markets/providers/predict_fun_provider.py` — wire bet placement
8. `backend/models/trading_wallet.py` — add chain values
9. `requirements.txt` — add new dependencies
10. `.env` — add new env vars

---

## Risk Assessment

| Risk | Impact | Mitigation |
|---|---|---|
| EIP-712 domain structs unknown for SX.bet/Limitless | Blocks order placement | Research from platform docs, test with small orders |
| Azuro LP contract ABI unavailable | Blocks Bookmaker/Predict.fun | Contact Azuro team, check GitHub |
| Lighter API-key signing complex | Delays integration | Use official `lighter-sdk`, follow docs |
| CCXT Aster auth differs from Binance | Subtle bugs | Test thoroughly, don't assume Binance behavior |
| Multiple new wallets = key management | Security risk | Use existing WalletRouter + Fernet encryption |
