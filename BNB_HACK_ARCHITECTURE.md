# BNB HACK Bot — Architecture Diagram

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     BNB HACK Bot System (June 22-28, 2026)     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  External Services                                              │
├─────────────────────────────────────────────────────────────────┤
│  • Binance REST API (klines, prices)                           │
│  • Trust Wallet Agent Kit (TWAK CLI) → BSC swaps              │
│  • Telegram/Discord/Slack (notifications)                      │
└─────────────────────────────────────────────────────────────────┘
         ▲                      ▲                      ▲
         │                      │                      │
         │ klines, prices       │ swaps, balance       │ alerts
         │                      │                      │
┌────────┴──────┬──────────────┴─────────┬────────────┴─────────┐
│               │                        │                      │
│  ┌────────────▼──────────┐   ┌─────────▼─────────┐   ┌───────▼────────┐
│  │   BinanceFeed         │   │   LiveTWAKExchange│   │ BnbHackAlerter  │
│  │  (data_feed.py)      │   │   (exchange.py)   │   │  (alerter.py)   │
│  │  • retry logic        │   │  • CLI wrapper    │   │  • multi-channel│
│  │  • timeout handling   │   │  • paper engine   │   │  • event handler│
│  └──────────────────────┘   └───────────────────┘   └─────────────────┘
│          ▲                          ▲                         ▲
│          │                          │                         │
│  ┌───────┴──────────────────────────┴─────────────────────────┴───────┐
│  │                                                                      │
│  │                    BnbHackBot (bot.py)                              │
│  │  ┌──────────────────────────────────────────────────────────────┐ │
│  │  │ Main orchestrator: manages position lifecycle               │ │
│  │  │  • Signal evaluation (1h SMA crossover)                     │ │
│  │  │  • Position management (buy/sell, TP/SL)                   │ │
│  │  │  • Risk management (cooldowns, daily limits)               │ │
│  │  │  • Metrics collection (PnL, win rate, Sharpe)              │ │
│  │  │  • Alert triggering (trades, errors, limits)               │ │
│  │  │  • Trade logging (CSV + metrics DB)                        │ │
│  │  └──────────────────────────────────────────────────────────────┘ │
│  │          ▲                                           ▲              │
│  │          │                                           │              │
│  │  ┌───────┴─────────────────┐      ┌────────────────┴────────┐    │
│  │  │  SignalEngine           │      │  MetricsCollector      │    │
│  │  │  (signals.py)           │      │  (metrics.py)          │    │
│  │  │  • SMA(10/50) crossover │      │  • equity curve        │    │
│  │  │  • golden/death cross   │      │  • win/loss tracking   │    │
│  │  │  • confidence scores    │      │  • sharpe/drawdown     │    │
│  │  └─────────────────────────┘      │  • trade history       │    │
│  │          ▲                        └────────────────────────┘    │
│  │          │                                                       │
│  │  ┌───────┴──────────────────────────────────────────────────┐   │
│  │  │         BotState (state.py)                              │   │
│  │  │  • Position (entry price, TP/SL, amount)                │   │
│  │  │  • PnL tracking (total, daily)                           │   │
│  │  │  • Cooldown flags                                        │   │
│  │  │  • Consecutive loss counter                              │   │
│  │  └───────────────────────────────────────────────────────────┘   │
│  │                                                                    │
│  └────────────────────────────────────────────────────────────────────┘
│
└────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Config & Environment                                           │
├─────────────────────────────────────────────────────────────────┤
│  • backend/config.py (ConfigRegistry + BnbHackSettings)        │
│    ├─ TWAK auth: WALLET_ADDRESS, WALLET_PASSWORD              │
│    ├─ Strategy: SMA_FAST(10), SMA_SLOW(50), TIMEFRAME(1h)      │
│    ├─ Risk: TP(3%), SL(3%), MAX_POS(75%), DAILY_LOSS($5)      │
│    └─ Timing: COMPETITION_START/END, CHECK_INTERVAL(3600s)   │
│                                                                 │
│  • backend/signals/technical.py (Shared indicators)            │
│    ├─ compute_sma(), compute_sma_series()                      │
│    └─ compute_rsi(), compute_rsi_series()                      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  API Layer (backend/api/hackathon.py)                           │
├─────────────────────────────────────────────────────────────────┤
│  GET  /api/v1/hackathon/bnb-hack/status   → PnL, position     │
│  GET  /api/v1/hackathon/bnb-hack/signal   → current signal    │
│  GET  /api/v1/hackathon/bnb-hack/trades   → recent trades     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Storage                                                        │
├─────────────────────────────────────────────────────────────────┤
│  • logs/bnb_hack_trades.csv    (trade history)                 │
│  • data/backtests/             (backtest results)              │
│  • systemd journal             (bot logs)                       │
│  • .env                        (secrets)                        │
└─────────────────────────────────────────────────────────────────┘
```

## Module Dependency Graph

```
┌─────────────────────┐
│ bnb_hack_bot.py     │  Entry point (systemd wrapper)
│ (compatibility)     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ BnbHackBot.__main__ │  Run loop, signal handlers
└──────────┬──────────┘
           │
    ┌──────┴──────────┬───────────────┬──────────────┐
    │                 │               │              │
    ▼                 ▼               ▼              ▼
┌─────────┐  ┌────────────┐  ┌─────────────┐  ┌──────────┐
│ Config  │  │ SignalEngine│  │BinanceFeed  │  │Alerter   │
│ (ctx)   │  │(signals.py)│  │(data_feed)  │  │(alerter) │
└─────────┘  └─────┬──────┘  └──────┬──────┘  └──────────┘
                    │                │
                    ▼                ▼
             ┌──────────────────────────────┐
             │ technical (compute_sma/rsi)  │
             │ shared with backtest         │
             └──────────────────────────────┘
    │
    ├──────────────────┬───────────────┬─────────────────┐
    │                  │               │                 │
    ▼                  ▼               ▼                 ▼
┌────────────┐  ┌──────────┐  ┌──────────────┐  ┌──────────────┐
│Exchange    │  │Metrics   │  │TWAK Client   │  │BotState      │
│(exchange)  │  │(metrics) │  │(clients/)    │  │(state)       │
└────────────┘  └──────────┘  └──────────────┘  └──────────────┘
```

## Execution Timeline

```
Bot Start
  ├─ Load config (settings.bnb_hack.*)
  ├─ Initialize subsystems (feed, signals, exchange, metrics, alerter)
  ├─ Log: "Bot loop started..."
  │
  └─→ Check competition window (June 22-28, 2026)
      │ If outside window: sleep 60s, retry
      │ If inside window: continue
      │
      └─→ Main cycle (every check_interval_seconds = 3600s = 1h)
          │
          ├─1. Fetch BNB/USDT 1h klines (last 100 candles)
          │
          ├─2. Compute SMA(10/50) and detect crossover
          │
          ├─3. Check position state
          │
          ├─4A. If position exists:
          │    ├─ Check TP (exit at +3%)
          │    ├─ Check SL (exit at -3%)
          │    └─ Exit if triggered → on_sell() → record_trade()
          │
          ├─4B. If no position:
          │    ├─ Check risk limits (daily loss, consecutive losses)
          │    ├─ Check cooldown status
          │    └─ If golden cross + confidence >= 0.50:
          │       └─ Buy (amount = 75% of USDC)
          │          → on_buy() → record_trade()
          │
          ├─5. Update metrics (equity curve, win rate, Sharpe)
          │
          ├─6. Log cycle result (signal, PnL, position status)
          │
          └─7. Sleep (check_interval_seconds)
              │
              └─→ Repeat cycle

Bot Stop (SIGTERM/SIGINT)
  ├─ Set _shutdown_requested = True
  ├─ Finish current cycle
  └─ Close gracefully (feed.close(), save metrics, log total PnL)
```

## Data Flow

```
Binance API (klines)
        │
        ▼
   BinanceFeed.get_klines()
        │
        ▼
   closes: List[float]
        │
        ├─→ SignalEngine.evaluate()
        │        │
        │        ├─→ compute_sma(closes, 10) → sma_fast
        │        ├─→ compute_sma(closes, 50) → sma_slow
        │        │
        │        └─→ Detect golden/death cross
        │                    │
        │                    ▼
        │            signal: Dict[action, confidence, ...]
        │                    │
        ├─ BotState (position, PnL, cooldown)
        │        │
        └────────┼──→ BnbHackBot.tick()
                 │        │
                 │        ├─ Check cooldowns, risk limits
                 │        ├─ Check exit conditions (TP/SL)
                 │        ├─ Check entry conditions (signal + confidence)
                 │        │
                 │        └─→ on_buy() or on_sell()
                 │                    │
                 │                    ├─ Exchange.swap()
                 │                    ├─ record_trade(TradeMetrics)
                 │                    ├─ alerter.on_buy/on_sell()
                 │                    └─ metrics.update_equity()
                 │
                 └─→ logs/bnb_hack_trades.csv
                 └─→ MetricsCollector (equity curve, win rate)
                 └─→ Alerts (Telegram/Discord/Slack)
```

## Risk Architecture

```
Daily Cycle
    │
    └─ Daily Loss Limit: $5
       ├─ If daily_pnl <= -$5: halt for 24h
       └─ Alert: on_risk_limit_hit("daily_loss_limit")

Trade Exit
    │
    ├─ Take Profit: +3%
    │  └─ Alert: on_sell(..., "take_profit")
    │
    └─ Stop Loss: -3%
       ├─ Increment consecutive_losses
       ├─ If consecutive_losses >= 3: halt for 4h
       └─ Alert: on_sell(..., "stop_loss") + on_risk_limit_hit(...)

Cooldown States
    │
    ├─ SL Hit: 2h cooldown (COOLDOWN_MINUTES=120)
    ├─ 3 Consecutive Losses: 4h cooldown
    └─ Daily Loss: 24h implied halt (bot idles)
```

---

**Diagram Version:** 1.0
**Last Updated:** 2026-06-08
**Competition Window:** June 22-28, 2026
