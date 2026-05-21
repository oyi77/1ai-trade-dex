# PnL & Wallet Fix Plan — No Hardcoded Values

## Principle
Everything configurable via `backend/config.py` with sensible defaults. No hardcoded values anywhere.

---

## Part 1: PnL Unification

### 1.1 Config Additions (`backend/config.py`)

Add these to Settings with defaults:

```python
# Fee Configuration
TAKER_FEE_RATE: float = 0.01  # Polymarket actual: 1% (was 0.02)
MAKER_FEE_RATE: float = 0.00  # Maker rebate
FEE_USE_STORED: bool = True   # Prefer trade.fee over recalculation
FEE_FALLBACK_RATE: float = 0.01  # Used when trade.fee is None

# Settlement Configuration
SETTLEMENT_USE_FILLED: bool = True  # Prefer filled_size/fill_price over size/entry_price
SETTLEMENT_VALUE_WIN: float = 1.0   # Redeem value for winning side
SETTLEMENT_VALUE_LOSS: float = 0.0  # Redeem value for losing side

# PnL Configuration
PNL_INCLUDE_FEE: bool = True  # Whether PnL already includes fee (prevents double-count)
```

### 1.2 Unified PnL Function (`backend/core/settlement/settlement_helpers.py`)

Refactor `calculate_pnl()` to use config:

```python
def calculate_pnl(trade, settings=None) -> float:
    """Unified PnL calculation. No hardcoded values."""
    s = settings or get_settings()
    
    # Determine effective price and size
    if s.SETTLEMENT_USE_FILLED and trade.fill_price and trade.filled_size:
        entry = trade.fill_price
        size = trade.filled_size
    else:
        entry = trade.entry_price
        size = trade.size
    
    # Determine fee
    if s.FEE_USE_STORED and trade.fee is not None:
        fee = trade.fee
    else:
        fee = s.FEE_FALLBACK_RATE * min(entry, 1 - entry) * size
    
    # Calculate
    dollar_cost = size + fee
    shares = dollar_cost / entry
    
    if trade.settlement_value >= s.SETTLEMENT_VALUE_WIN:
        return shares - dollar_cost
    else:
        return -dollar_cost
```

### 1.3 Fix BTC 5-min Settlement (`backend/core/settlement/settlement.py`)

Replace lines 84-108 inline formula with:
```python
from backend.core.settlement.settlement_helpers import calculate_pnl
pnl = calculate_pnl(trade, settings)
```

### 1.4 Fix Bankroll Double-Count (`backend/core/settlement/settlement.py`)

Line 825: Change from:
```python
state.paper_bankroll = max(0, bankroll + trade.size + trade.pnl - fee)
```
To:
```python
# PnL already includes fee when PNL_INCLUDE_FEE=True
state.paper_bankroll = max(0, bankroll + trade.size + trade.pnl)
```

### 1.5 Fix Genome Formula (`backend/repositories/genome_repository.py`)

Replace lines 249-274 with call to unified `calculate_pnl()`.

### 1.6 Fix Shadow Runner (`backend/application/strategy/shadow_runner.py`)

Replace lines 118-134 with call to unified `calculate_pnl()`.

### 1.7 Migration: Recalculate Existing PnL

Run `backend/scripts/recalculate_expired_pnl.py` to fix historical trades with wrong fee rate.

---

## Part 2: Wallet Wiring

### 2.1 Config Addition (`backend/config.py`)

```python
# Wallet Configuration
WALLET_ENCRYPTION_KEY: str = ""  # Fernet key for encrypting private keys
WALLET_ROUTER_ENABLED: bool = True  # Enable multi-wallet fan-out
COPY_POLICY_ENABLED: bool = True  # Enable copy-trade policy engine
```

### 2.2 Instantiate WalletRouter (`backend/api/lifespan.py`)

In startup:
```python
from backend.core.wallet.wallet_router import WalletRouter

if settings.WALLET_ENCRYPTION_KEY and settings.WALLET_ROUTER_ENABLED:
    fernet = Fernet(settings.WALLET_ENCRYPTION_KEY.encode())
    wallet_router = WalletRouter(db_session, fernet_key=fernet)
    app.state.wallet_router = wallet_router
else:
    app.state.wallet_router = None
```

### 2.3 Wire to AutoTrader (`backend/core/auto_trader.py`)

No changes needed — already accepts `wallet_router=None`. Just needs the instance passed.

### 2.4 Wire CopyPolicyEngine (`backend/core/copy_engine.py`)

In scheduler/orchestrator where AutoTrader is created:
```python
copy_engine = CopyPolicyEngine(db) if settings.COPY_POLICY_ENABLED else None
auto_trader = AutoTrader(
    risk_manager=risk_manager,
    clob_factory=clob_factory,
    wallet_router=app.state.wallet_router,
    copy_engine=copy_engine,  # NEW
)
```

### 2.5 Frontend: Dynamic Strategy List (`frontend/src/components/admin/WalletMatrix.tsx`)

Replace hardcoded `['btc_oracle', 'market_maker', 'line_movement_detector']` with:
```typescript
const [strategies, setStrategies] = useState<string[]>([]);
useEffect(() => {
    fetch('/api/v1/strategy-config')
        .then(r => r.json())
        .then(data => setStrategies(data.map(s => s.strategy_name)));
}, []);
```

### 2.6 Frontend: Create TradingWallet UI

Add create form in `WalletConfigTab.tsx`:
- Label input
- Chain selector (polymarket/kalshi/sxbet/limitless/ostium/aster/lighter/hyperliquid)
- Address input
- Private key input (encrypted on submit)
- Paper mode toggle

### 2.7 Frontend: Create WalletAllocation UI

Add allocation creator:
- Strategy dropdown (from DB)
- Wallet dropdown (from DB)
- Weight slider (0.0 - 1.0)
- Max exposure input

---

## Part 3: Verification

### 3.1 Unit Tests
- Test `calculate_pnl()` with stored fee vs calculated fee
- Test `calculate_pnl()` with filled vs unfilled trades
- Test WalletRouter fan-out with new config
- Test CopyPolicyEngine filtering

### 3.2 Integration Tests
- Create TradingWallet via API, verify encryption
- Create WalletAllocation, trigger signal, verify fan-out
- Run settlement with new fee rate, verify PnL matches Polymarket

### 3.3 Manual Verification
- Compare DB PnL for btc-5m-1779370200 with Polymarket data ($19.49)
- Verify no double-counting in bankroll
- Verify wallet router produces correct ChildOrders

---

## Files to Modify

| File | Change |
|---|---|
| `backend/config.py` | Add 9 new settings with defaults |
| `backend/core/settlement/settlement_helpers.py` | Refactor `calculate_pnl()` to use config |
| `backend/core/settlement/settlement.py` | Fix BTC 5-min path, fix bankroll double-count |
| `backend/repositories/genome_repository.py` | Replace inline formula with `calculate_pnl()` |
| `backend/application/strategy/shadow_runner.py` | Replace inline formula with `calculate_pnl()` |
| `backend/api/lifespan.py` | Instantiate WalletRouter |
| `backend/core/auto_trader.py` | Accept copy_engine param |
| `backend/core/orchestrator.py` | Pass wallet_router to AutoTrader |
| `frontend/src/components/admin/WalletMatrix.tsx` | Dynamic strategy list |
| `frontend/src/components/admin/WalletConfigTab.tsx` | Create wallet/allocation UI |

## Order of Operations

1. Config additions (no behavior change)
2. Unified `calculate_pnl()` (backward compatible)
3. Fix BTC 5-min settlement
4. Fix bankroll double-count
5. Fix genome + shadow formulas
6. Wire WalletRouter
7. Wire CopyPolicyEngine
8. Frontend fixes
9. Tests + verification
