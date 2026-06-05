"""Seed paper-only strategy configuration.

Run this to configure the system for safe paper trading with only
profitable strategies enabled. All live trading is disabled.

Usage:
    python scripts/seed_paper_config.py
"""

from backend.models.database import SessionLocal, StrategyConfig, BotState
from datetime import datetime, timezone

PAPER_SAFE_STRATEGIES = {
    "bond_scanner": {
        "mode": "paper",
        "notes": "308 settled trades, +$18,711 PnL, 35.9x win/loss ratio. "
        "Buys cheap NO shares (median 0.064) on high-probability markets.",
    },
    "copy_trader": {
        "mode": "paper",
        "notes": "Mirrors top traders. Needs validation period.",
    },
    "market_maker": {
        "mode": "paper",
        "notes": "Liquidity provision. Needs validation period.",
    },
    "resolution_sniper": {
        "mode": "paper",
        "notes": "Snaps near-resolution markets. Needs validation period.",
    },
    "probability_arb": {
        "mode": "paper",
        "notes": "Cross-platform probability arbitrage. Needs validation period.",
    },
    "negrisk_strategy": {
        "mode": "paper",
        "notes": "Negative risk exploitation. Needs validation period.",
    },
}

DISABLED_STRATEGIES = [
    "line_movement_detector",  # -$7,350 in 256 trades
    "cross_platform_arb",      # -$1,450 in 100 trades
    "arb_scanner",             # -$2,500 in 384 trades
    "cex_pm_leadlag",          # -$777 in 249 trades
    "crypto_oracle",           # -$2,014 in 665 trades
    "news_frontrun",           # -$5 in 7 trades (too few)
    "polymarket",              # $0 in 27 trades (no-op)
    "weather_emos",            # +$3,776 but disabled by AGI
    "longshot_bias",           # -$27 in 618 trades
]


def seed():
    db = SessionLocal()
    now = datetime.now(timezone.utc)

    # Disable all losing strategies
    for name in DISABLED_STRATEGIES:
        cfg = db.query(StrategyConfig).filter_by(strategy_name=name).first()
        if cfg and cfg.enabled:
            cfg.enabled = False
            cfg.kill_date = now
            print(f"  DISABLED: {name}")

    # Enable safe strategies in paper mode
    for name, info in PAPER_SAFE_STRATEGIES.items():
        cfg = db.query(StrategyConfig).filter_by(strategy_name=name).first()
        if cfg:
            cfg.enabled = True
            cfg.trading_mode = info["mode"]
            print(f"  ENABLED: {name} (mode={info['mode']})")
        else:
            print(f"  MISSING: {name} — create manually")

    # Stop live trading
    live = db.query(BotState).filter_by(mode="live").first()
    if live:
        live.is_running = False
        print(f"\n  LIVE TRADING: STOPPED (bankroll=${live.bankroll:.2f})")

    db.commit()

    # Print summary
    enabled = db.query(StrategyConfig).filter_by(enabled=True).all()
    print(f"\n{'='*50}")
    print(f"PAPER CONFIGURATION ({len(enabled)} strategies)")
    print(f"{'='*50}")
    for e in enabled:
        notes = PAPER_SAFE_STRATEGIES.get(e.strategy_name, {}).get("notes", "")
        print(f"  {e.strategy_name}: mode={e.trading_mode}")
        if notes:
            print(f"    {notes[:80]}")

    paper = db.query(BotState).filter_by(mode="paper").first()
    print(f"\nPaper bankroll: ${paper.bankroll:.2f}")
    print(f"Live trading: DISABLED")
    print(f"\nRun for 2+ weeks before considering live mode.")

    db.close()


if __name__ == "__main__":
    seed()
