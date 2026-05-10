# Config System Migration Guide

## Overview

The **ConfigRegistry** is the single source of truth for all configuration in PolyEdge. It replaces scattered hardcoded values with a centralized, validated configuration system that's organized by domain and powered by environment variables.

### Why ConfigRegistry Exists

Before ConfigRegistry:
- Strategy parameters scattered across modules as constants
- Hardcoded defaults embedded in business logic
- No central documentation of available settings
- No validation at startup (errors appeared at runtime)
- No clear pattern for adding new configuration

With ConfigRegistry:
- **Centralized**: All config in one dataclass (`ConfigRegistry`)
- **Organized**: Grouped by category (API, Rate Limits, Strategy Params, etc.)
- **Validated**: Fails fast on startup if critical config is missing/invalid
- **Documented**: Each key has inline documentation; `.env.example` describes all vars
- **Type-safe**: Uses Pydantic validation for type checking and conversion

### Key Design Principles

1. **Dataclass over Settings**: Uses `@dataclass` with type hints for clarity
2. **Environment Variable Backed**: All settings source from `.env` via Pydantic
3. **Categorized Access**: Grouped logically (no more guessing which config belongs where)
4. **Fail Fast**: `_validate_startup()` runs on import, preventing runtime surprises
5. **Backwards Compatible**: Old `settings` object still works; migration is gradual

## Quick Start

### Import and Use Settings

```python
from backend.config import settings

# Use settings directly
min_edge = settings.BOND_SCANNER_MIN_EDGE
api_url = settings.GAMMA_API_URL
```

### Access Pattern

```python
# Category prefix + parameter name
settings.{CATEGORY}_{PARAMETER_NAME}

# Examples:
settings.BOND_SCANNER_MIN_EDGE        # 0.005 (default)
settings.BTC_ORACLE_MIN_EDGE          # 0.03 (default)
settings.CIRCUIT_BREAKER_ENABLED      # True (default)
settings.LOG_LEVEL                    # "INFO" (default)
```

### Runtime vs Module-Level Imports

```python
# ✅ GOOD: Module-level (for static values like URLs)
from backend.config import settings
API_URL = settings.GAMMA_API_URL  # Fixed at import

# ✅ GOOD: Function-level (for runtime values like position sizes)
def calculate_position(risk_pct: float):
    return risk_pct * settings.INITIAL_BANKROLL  # Evaluates at runtime
```

## Adding New Config Keys

Follow this pattern to add new configuration:

### Step 1: Add to ConfigRegistry

Edit `backend/config.py` and add the key in the appropriate category section:

```python
@dataclass
class ConfigRegistry:
    # ... existing config ...
    
    # New category section (if needed)
    # MY_NEW_CATEGORY - Description
    MY_NEW_PARAM_NAME: str = "default_value"
    MY_NEW_INT_PARAM: int = 42
    MY_NEW_FLOAT_PARAM: float = 0.05
```

**Rules:**
- Place in the correct category section (API_ENDPOINTS, STRATEGY_PARAMS, SYSTEM, etc.)
- Use `UPPER_SNAKE_CASE` naming
- Provide type hints (`str`, `int`, `float`, `bool`, `Optional[str]`, etc.)
- Provide sensible defaults

### Step 2: Add to .env.example

Edit `.env.example` and document the new key:

```bash
# ============================================================
# STRATEGY_PARAMS - Strategy-specific thresholds and limits
# ============================================================

# MY_NEW_PARAM_NAME
MY_NEW_PARAM_NAME=default_value

# MY_NEW_INT_PARAM
MY_NEW_INT_PARAM=42
```

**Rules:**
- Add in the matching category section
- Include a comment line (with `#`) explaining the parameter
- Format: `# PARAM_NAME` followed by `PARAM_NAME=value`

### Step 3: Use in Code

Reference the setting wherever needed:

```python
from backend.config import settings

def my_function():
    threshold = settings.MY_NEW_FLOAT_PARAM
    if threshold > 0.05:
        # ...
```

### Step 4: Add Custom Validation (Optional)

If your setting needs special validation, add a `@model_validator`:

```python
@model_validator(mode="after")
def validate_my_settings(self):
    if self.MY_NEW_FLOAT_PARAM < 0 or self.MY_NEW_FLOAT_PARAM > 1:
        raise ValueError("MY_NEW_FLOAT_PARAM must be between 0 and 1")
    return self
```

## Categories

ConfigRegistry is organized into logical categories. Each category groups related settings:

### 1. API_ENDPOINTS

External API base URLs:

```python
settings.GAMMA_API_URL           # Polymarket gamma API
settings.DATA_API_URL            # Polymarket data API
settings.CLOB_API_URL            # Polymarket CLOB API
settings.KALSHI_API_URL          # Kalshi trade API
settings.COINGECKO_API_URL       # CoinGecko API
settings.OPEN_METEO_API_URL      # Weather API
```

**Naming:** `*_API_URL`, `*_BASE_URL`

### 2. RATE_LIMITS

Rate limiting and backoff configuration:

```python
settings.RATE_LIMIT_GAMMA        # 100 requests/unit
settings.RATE_LIMIT_KALSHI       # 30 requests/unit
settings.RATE_LIMIT_CRYPTO       # 60 requests/unit
settings.RATE_LIMIT_MAX_DELAY    # 60.0 seconds max backoff
```

**Naming:** `RATE_LIMIT_*`, `RATE_LIMIT_*_BACKOFF_*`

### 3. STRATEGY_PARAMS

Strategy-specific thresholds, limits, and parameters:

```python
# Bond Scanner
settings.BOND_SCANNER_MIN_PRICE          # 0.88
settings.BOND_SCANNER_MIN_EDGE           # 0.005
settings.BOND_SCANNER_KELLY_FRACTION     # 0.25

# BTC Oracle
settings.BTC_ORACLE_MIN_EDGE             # 0.03
settings.BTC_ORACLE_INTERVAL_SECONDS     # 30

# General Market Scanner
settings.GM_SCANNER_MIN_EDGE             # 0.02

# HFT Scanners
settings.HFT_SCANNER_MIN_EDGE            # 0.02
settings.HFT_SCANNER_PARALLEL_LIMIT      # 50
```

**Naming:** `{STRATEGY_NAME}_MIN_*`, `{STRATEGY_NAME}_MAX_*`, `{STRATEGY_NAME}_*_*`

### 4. RISK - Circuit Breakers & Limits

Trading risk parameters:

```python
settings.CIRCUIT_BREAKER_ENABLED         # True
settings.MAX_CONCURRENT_POSITIONS        # 3
settings.CONSECUTIVE_LOSS_LIMIT          # 3
settings.DAILY_LOSS_LIMIT_ENABLED        # True
settings.RISK_MAX_DAILY_LOSS_PCT         # 0.10 (10%)
settings.RISK_MAX_WEEKLY_LOSS_PCT        # 0.20 (20%)
```

**Naming:** `CIRCUIT_BREAKER_*`, `RISK_*`, `DAILY_LOSS_*`

### 5. SYSTEM - Deployment & Runtime

System-level configuration:

```python
settings.DATABASE_URL                    # "sqlite:///./tradingbot.db"
settings.TRADING_MODE                    # "paper" | "testnet" | "live"
settings.SHADOW_MODE                     # True (development mode)
settings.LOG_LEVEL                       # "INFO" | "DEBUG" | "WARNING"
settings.PORT                            # 8000
settings.POLYMARKET_API_KEY              # Your API key
settings.POLYMARKET_PRIVATE_KEY          # Your private key
```

**Naming:** `DATABASE_URL`, `TRADING_MODE`, `LOG_LEVEL`, `{EXCHANGE}_API_*`

### 6. FEATURE FLAGS - AGI, HFT, etc.

Feature toggle flags:

```python
# AGI Autonomy
settings.AGI_AUTO_PROMOTE               # False
settings.AGI_AUTO_ENABLE                # False
settings.AGI_STRATEGY_HEALTH_ENABLED    # True

# HFT Features
settings.HFT_SCANNER_PARALLEL_LIMIT     # 50
settings.HFT_EXECUTION_AUTO_EXECUTE     # True
```

**Naming:** `AGI_*`, `HFT_*`, `ENABLE_*`, `*_ENABLED`

### 7. POLLING - Job Intervals

Job scheduling intervals:

```python
settings.POLL_FAST_MS                   # 1000ms
settings.POLL_NORMAL_MS                 # 5000ms
settings.POLL_SLOW_MS                   # 30000ms
settings.AGI_HEALTH_CHECK_INTERVAL_MINUTES  # 15
settings.DATABASE_BACKUP_INTERVAL_HOURS     # 6
```

**Naming:** `POLL_*_MS`, `*_INTERVAL_*`

## Validation

### How Validation Works

When `ConfigRegistry` is imported:
1. Pydantic loads `.env` file (via `model_config = ConfigDict(env_file=".env")`)
2. Type conversion happens (e.g., `"0.05"` → `0.05`)
3. `@field_validator` and `@model_validator` run
4. `_validate_startup()` calls `settings.validate()`
5. If validation fails → `ValueError` raised, app won't start
6. If validation passes → "PolyEdge Configuration Loaded Successfully"

### Validation Flow

```python
# Step 1: Import triggers startup validation
from backend.config import settings
# ^ Running _validate_startup() now

# Step 2: Validation runs
def _validate_startup():
    issues = settings.validate()
    if issues:
        print("Configuration validation errors:")
        for issue in issues:
            print(f"  - {issue}")
        raise ValueError(f"Configuration validation failed")
```

### Built-in Validation

ConfigRegistry uses Pydantic validators:

- **Type coercion**: `"42"` → `42` (int), `"0.05"` → `0.05` (float)
- **Optional fields**: `Optional[str]` accepts `None`
- **Enum validation**: `TRADING_MODE: str = "paper"` validates allowed values
- **Custom validators**: `@field_validator` for domain-specific rules

### Adding Custom Validators

```python
@field_validator("BOND_SCANNER_MIN_EDGE")
@classmethod
def validate_min_edge(cls, v):
    if v < 0 or v > 1:
        raise ValueError("BOND_SCANNER_MIN_EDGE must be between 0 and 1")
    return v
```

### Common Validation Scenarios

**Range validation:**
```python
@field_validator("MAX_CONCURRENT_POSITIONS")
@classmethod
def validate_max_positions(cls, v):
    if v < 1 or v > 10:
        raise ValueError("MAX_CONCURRENT_POSITIONS must be 1-10")
    return v
```

**Conditional validation:**
```python
@model_validator(mode="after")
def validate_live_mode(self):
    if self.TRADING_MODE == "live" and not self.POLYMARKET_API_KEY:
        raise ValueError("POLYMARKET_API_KEY is required in live mode")
    return self
```

## Environment Variables

### File Organization

`.env.example` mirrors the `ConfigRegistry` category structure:

```bash
# ============================================================
# API_ENDPOINTS - External API URLs
# ============================================================
GAMMA_API_URL=https://gamma-api.polymarket.com
DATA_API_URL=https://data-api.polymarket.com

# ============================================================
# STRATEGY_PARAMS - Strategy-specific thresholds and limits
# ============================================================
BOND_SCANNER_MIN_PRICE=0.88
BTC_ORACLE_MIN_EDGE=0.03

# ============================================================
# SYSTEM - System Settings
# ============================================================
DATABASE_URL=sqlite:///./tradingbot.db
TRADING_MODE=paper
LOG_LEVEL=INFO
```

### Naming Conventions

**Always use UPPER_SNAKE_CASE with category prefix:**

```
[CATEGORY]_[PARAMETER_NAME]

Examples:
BOND_SCANNER_MIN_PRICE
API_RATE_LIMIT_GAMMA
HFT_SCANNER_MIN_EDGE
RISK_MAX_DAILY_LOSS_PCT
SYSTEM_PORT
```

**Category prefixes:**
- `BOND_SCANNER_*` → Bond Scanner strategy params
- `BTC_ORACLE_*` → BTC Oracle strategy params
- `HFT_SCANNER_*` → HFT scanner params
- `RISK_*` → Risk configuration
- `RATE_LIMIT_*` → Rate limiting

### .env File Setup

1. Copy `.env.example` to `.env`: `cp .env.example .env`
2. Fill in your values:
   ```bash
   POLYMARKET_API_KEY=your_actual_api_key
   POLYMARKET_PRIVATE_KEY=your_actual_private_key
   ```
3. Commit `.env.example` (template) but **NOT** `.env` (secrets)

### Type Conversion Rules

Environment variables are strings → ConfigRegistry converts:

| Python Type | Example .env Value | Conversion |
|-------------|-------------------|------------|
| `int` | `PORT=8000` | `"8000"` → `8000` |
| `float` | `BOND_SCANNER_MIN_EDGE=0.005` | `"0.005"` → `0.005` |
| `bool` | `AGI_AUTO_ENABLE=False` | `"False"` → `False` |
| `str` | `LOG_LEVEL=INFO` | `"INFO"` → `"INFO"` |
| `Optional[str]` | `ADMIN_API_KEY=None` | `"None"` → `None` |

**Important:** `.env` values are always strings. Pydantic handles conversion.

## Migration Pattern

### Migrating Hardcoded Defaults

**Before (hardcoded in strategy):**
```python
# backend/strategies/bond_scanner.py

DEFAULT_PARAMS = {
    "min_edge": 0.02,
    "min_price": 0.88,
    "max_price": 0.97
}

def scan_bonds():
    min_edge = DEFAULT_PARAMS["min_edge"]
    # ...
```

**After (migrated to ConfigRegistry):**

1. **Add to ConfigRegistry:**
   ```python
   # backend/config.py
   BOND_SCANNER_MIN_EDGE: float = _cfg("BOND_SCANNER_MIN_EDGE", 0.02)
   ```

2. **Add to .env.example:**
   ```bash
   # .env.example
   # BOND_SCANNER_MIN_EDGE
   BOND_SCANNER_MIN_EDGE=0.02
   ```

3. **Update strategy to use settings:**
   ```python
   # backend/strategies/bond_scanner.py
   from backend.config import settings
   
   def scan_bonds():
       min_edge = settings.BOND_SCANNER_MIN_EDGE
       # ...
   ```

### Migration Checklist

- [ ] Add setting to `ConfigRegistry` in correct category
- [ ] Add setting to `.env.example` with documentation comment
- [ ] Update all uses of old hardcoded value
- [ ] Add custom validator if needed
- [ ] Test in shadow mode before removing old values
- [ ] Remove old hardcoded value after migration complete

### Gradual Migration Strategy

1. **Add new config key** (no breaking changes)
2. **Update one module at a time** to use new config
3. **Test in shadow mode** to verify behavior
4. **Deprecate old hardcoded value** after all uses migrated
5. **Remove old value** when confident in new system

## Common Gotchas

### 1. _cfg() Returns String, Type Conversion Needed

**Gotcha:** `_cfg()` returns strings from environment → need type conversion

```python
# ❌ WRONG: String comparison
if settings.BOND_SCANNER_MIN_EDGE == "0.005":  # String!
    # ...

# ✅ CORRECT: Float comparison (Pydantic converted it)
if settings.BOND_SCANNER_MIN_EDGE == 0.005:  # Float
    # ...
```

**Fix:** Rely on Pydantic type coercion - config is already converted.

### 2. Import Location Matters

**Gotcha:** Import at module level evaluates at import time (static), function level evaluates at runtime.

```python
# ❌ BAD: URL set at import time (can't change at runtime)
from backend.config import settings
API_URL = settings.GAMMA_API_URL  # Fixed value

# ✅ GOOD: URL fetched every time function called
def make_request():
    api_url = settings.GAMMA_API_URL  # Current value
    # ...
```

**Use module-level for:** URLs, addresses, constants  
**Use function-level for:** Dynamic params, runtime decisions

### 3. .env Not in Git (Good!)

**Gotcha:** Accidentally committing `.env` exposes API keys

```bash
# ✅ Add to .gitignore (already done):
.env
*.env
```

**Test:** Run `git status` to verify `.env` is ignored.

### 4. Validation Runs on Import

**Gotcha:** Config validation fails → app won't start

```bash
$ python main.py
Configuration validation errors:
  - BOND_SCANNER_MIN_EDGE must be between 0 and 1
Traceback (most recent call last):
  ...
ValueError: Configuration validation failed
```

**Fix:** Check `.env` values match expected types and ranges.

### 5. Type Mismatch Errors

**Gotcha:** String in `.env` but `int` expected

```bash
# .env (wrong)
BOND_SCANNER_MAX_CONCURRENT_BONDS=8

# ConfigRegistry expects int:
BOND_SCANNER_MAX_CONCURRENT_BONDS: int = 8

# But .env has string "8", not int 8 → Pydantic handles it, but be careful
```

**Best practice:** Match `.env` value format to expected type.

### 6. Default Values Not Overridden

**Gotcha:** Default in `ConfigRegistry` used when `.env` missing

```python
# ConfigRegistry
BOND_SCANNER_MIN_EDGE: float = 0.005

# If .env missing this line:
# BOND_SCANNER_MIN_EDGE=0.005

# → Falls back to 0.005 (default)
```

**Good:** Default protects against missing config  
**Bad:** You might think config is set when it's not

**Solution:** Check `.env` has all required values, or add explicit check:

```python
if settings.BOND_SCANNER_MIN_EDGE == 0.005:
    logger.warning("BOND_SCANNER_MIN_EDGE using default value")
```

## Summary

### Quick Reference

| Action | Command/Pattern |
|--------|-----------------|
| Import settings | `from backend.config import settings` |
| Access config | `settings.CATEGORY_PARAMETER` |
| Add new config | 1. Add to ConfigRegistry<br>2. Add to .env.example<br>3. Use in code |
| Validate config | Runs on import, raises `ValueError` if invalid |
| Override config | Add to `.env` (not .env.example) |
| Default fallback | `settings.PARAM = _cfg("PARAM", default_value)` |

### Principles to Remember

1. **Centralized**: One source of truth (ConfigRegistry)
2. **Categorized**: Grouped by domain (API, Strategy, System, etc.)
3. **Validated**: Fails fast on startup
4. **Documented**: Inline comments + .env.example
5. **Gradual migration**: Old hardcoded values can coexist temporarily

### Further Reading

- `backend/config.py` - Complete ConfigRegistry definition
- `.env.example` - All environment variables documented
- `backend/strategies/` - Migrated strategy examples
- `docs/architecture/` - Architecture decisions (ADR files)
