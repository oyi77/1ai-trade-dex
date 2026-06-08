# BNB HACK Bot — Integration Summary

## Overview

BNB HACK is an autonomous onchain trading agent for the BNB HACK competition (June 22-28, 2026). It trades BNB/USDC spot on BSC using an SMA crossover strategy (10/50 on 1h timeframe) with 3% TP/SL.

**Backtested:** +10.78% return / 6mo, 43.6% win rate, 10.47% max drawdown, Sharpe 0.27, 55 trades.

---

## File Structure

### Runtime Bot
```
backend/bot/bnb_hack/
├── __init__.py              # Package exports
├── state.py                 # Position, BotState dataclasses
├── data_feed.py            # BinanceFeed (Binance REST client with retry)
├── signals.py              # SignalEngine (SMA crossover logic)
├── exchange.py             # LiveTWAKExchange (wraps TWAK client) + PaperEngine
└── bot.py                  # BnbHackBot (orchestrates cycle: eval signal → trade → manage risk)

backend/bot/bnb_hack_bot.py # Entry point wrapper (systemd calls this via python -m)
```

### Config & Dependencies
```
backend/config.py                     # ConfigRegistry with BnbHackSettings frozen dataclass
                                      # Access: settings.bnb_hack.sma_fast, etc.

backend/clients/twak_client.py       # TWAKClient (async CLI wrapper for Trust Wallet Agent Kit)
                                      # Enhanced: password, slippage, quote_only support

backend/signals/technical.py         # Shared: compute_sma(), compute_rsi() + series
backend/bot/indicators.py            # Re-export for backward compatibility
```

### Research & Testing
```
backend/research/bnb_hack_backtest.py # Multi-strategy backtest engine (SMA, RSI, Bollinger, MACD)
                                       # Run: python -m backend.research.bnb_hack_backtest

backend/tests/test_bnb_hack_bot.py   # Unit tests (4 passing):
                                       # - Settings exposure
                                       # - Indicator validation
                                       # - Bot buy logic (injected dependencies)
                                       # - Daily loss limit guard
```

### Operations
```
scripts/bnb-hack.service             # systemd unit (Type=simple, RestartSec=30s, auto-restart)
scripts/run_bnb_hack.sh              # systemd wrapper (venv + .env sourcing)
```

---

## Design Decisions

### 1. Not a BaseStrategy
BNB HACK is NOT a `BaseStrategy` subclass because:
- **Domain mismatch:** Trades BSC spot via TWAK CLI, not prediction markets
- **Capital model:** Dedicated $34 USDC wallet, not shared portfolio allocation
- **Execution:** Direct async subprocess TWAK calls, not market provider abstractions
- **Event model:** Independent 1h async loop, not strategy scheduler integration

✅ Correct placement: `backend/bot/` operational module (like `backend/bot/notification/`)

### 2. Single TWAK Client
- `backend/clients/twak_client.py` is canonical TWAK wrapper
- Bot uses `LiveTWAKExchange` adapter to normalize interface
- No duplicate subprocess wrappers in bot code

### 3. Shared Indicators
- `backend/signals/technical.py` is authoritative (SMA, RSI + series versions)
- Bot and backtest both import from there (DRY)
- Indicators have validation (period >= 1, closes not empty)

### 4. Config via Settings
- All params in `ConfigRegistry`: `BNB_HACK_SMA_FAST`, `TWAK_ACCESS_ID`, etc.
- Access via `settings.bnb_hack.*` (frozen dataclass property)
- Env vars auto-loaded from `.env`

### 5. Package Structure
- Modular: state, data, signals, exchange, bot are isolated modules
- Testable: each can be unit tested independently
- Backward-compatible: entry point `backend/bot/bnb_hack_bot.py` unchanged

---

## Runtime Flow

```
systemd bnb-hack.service
  ↓
scripts/run_bnb_hack.sh (venv + .env)
  ↓
python -m backend.bot.bnb_hack_bot --loop [--paper]
  ↓
BnbHackBot.from_config(paper=False)
  ├─ BinanceFeed()                    [fetch BNBUSDT klines from Binance]
  ├─ SignalEngine(feed)               [compute SMA(10/50) crosses]
  └─ LiveTWAKExchange(TWAKClient(...)) [execute swaps on BSC via TWAK]
  ↓
bot.run()  [async loop, 1h interval]
  ├─ tick() every check_interval_seconds
  ├─ Manage positions: entry (golden cross), exit (TP/SL)
  ├─ Track PnL, cooldowns, daily loss limits
  └─ Log trades to logs/bnb_hack_trades.csv
```

---

## Configuration (environment variables)

**TWAK/Wallet:**
```
TWAK_WALLET_ADDRESS        Default: 0x5DE14Ebd7703662Ea7AB524a85af1910661a8768
TWAK_WALLET_PASSWORD       Required for live trading
TWAK_ACCESS_ID             Required for TWAK auth
TWAK_HMAC_SECRET           Required for TWAK auth
```

**Strategy (SMA Trend):**
```
BNB_HACK_SMA_FAST          10       # Fast moving average period
BNB_HACK_SMA_SLOW          50       # Slow moving average period
BNB_HACK_TIMEFRAME         1h       # Candle timeframe (1h for backtested params)
BNB_HACK_TAKE_PROFIT_PCT   3.0      # Exit on +3% PnL
BNB_HACK_STOP_LOSS_PCT     3.0      # Exit on -3% PnL
BNB_HACK_MAX_POSITION_PCT  75.0     # Use 75% of available USDC per trade
BNB_HACK_MIN_CONFIDENCE    0.50     # Only enter on 0.50+ signal confidence
```

**Risk Management:**
```
BNB_HACK_MAX_DAILY_LOSS_USD           5.0    # Halt if daily PnL <= -$5
BNB_HACK_COOLDOWN_MINUTES             120    # Cool down 2h after SL hit
BNB_HACK_MAX_CONSECUTIVE_LOSSES       3      # Halt after 3 losing trades
BNB_HACK_CHECK_INTERVAL_SECONDS       3600   # Check signal every 1h
```

**Competition Window:**
```
BNB_HACK_COMPETITION_START   2026-06-22T00:00:00Z
BNB_HACK_COMPETITION_END     2026-06-28T23:59:59Z
```

---

## Usage

**Single cycle (check signal, show output):**
```bash
python -m backend.bot.bnb_hack_bot
```

**Continuous trading (24/7 loop):**
```bash
python -m backend.bot.bnb_hack_bot --loop
```

**Paper trading (sim, no real swaps):**
```bash
python -m backend.bot.bnb_hack_bot --loop --paper
```

**Via systemd:**
```bash
sudo systemctl start bnb-hack    # Start
sudo systemctl stop bnb-hack     # Stop
sudo systemctl restart bnb-hack  # Restart
sudo systemctl status bnb-hack   # Status
sudo journalctl -u bnb-hack -f   # Tail logs
```

**Backtest:**
```bash
python -m backend.research.bnb_hack_backtest                      # All strategies
python -m backend.research.bnb_hack_backtest --strategy sma_trend # Specific
```

---

## Testing

**Unit tests:**
```bash
pytest backend/tests/test_bnb_hack_bot.py -v
```

**Integration verification:**
```bash
python -c "
from backend.bot.bnb_hack import BnbHackBot
from backend.config import settings
assert settings.bnb_hack.sma_fast == 10
print('✓ Integration OK')
"
```

---

## Verification Checklist

- ✅ All modules compile (`py_compile`)
- ✅ Unit tests pass (4/4)
- ✅ Imports work (backward-compatible + package)
- ✅ Config loads correctly (`settings.bnb_hack.*`)
- ✅ systemd service active and running
- ✅ Service restart succeeds
- ✅ Paper mode works (no TWAK needed)
- ✅ Shared indicators reusable
- ✅ TWAK client centralized
- ✅ No duplicate code

---

## Key Patterns Followed

1. **loguru** for logging (not stdlib)
2. **settings** from ConfigRegistry for all config (not env vars directly)
3. **Type hints** throughout
4. **DRY:** shared `technical.py` for indicators
5. **Modular:** state, feed, signals, exchange, bot separated
6. **Testable:** injected dependencies, mocked exchanges in tests
7. **No BaseStrategy:** bot is operational module, not strategy
8. **Backward compatible:** entry point unchanged
9. **Git clean:** no doc slop, only code
10. **Production-ready:** retry logic, graceful shutdown, logging, error handling

---

## Next Steps (If Needed)

1. **Monitoring:** Add metrics export (Prometheus, StatsD) for PnL tracking
2. **Alerting:** Telegram/Discord alerts on large trades or risk events
3. **Dashboard:** Web UI to monitor bot status in real-time
4. **Multi-strategy:** Support portfolio of different strategies via config
5. **Hedge:** Add inverse positions or hedging logic for risk mgmt
6. **Post-competition:** Archive bot for future reference, extract learnings into reusable strategy framework

---

**Status:** Production-ready for BNB HACK competition (June 22-28, 2026).
