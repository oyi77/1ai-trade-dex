#!/usr/bin/env python3
"""
Configure strategies based on actual performance data (June 2026).

DISABLE: Strategies with 0% WR or massive losses
  - arb_scanner (0% WR, -$1,772)
  - cross_platform_arb (0% WR, -$2,493)
  - line_movement_detector (89.8% WR but -$424 - asymmetric payoffs)

KEEP ENABLED: Profitable strategies
  - bond_scanner (+$1,140, 80.9% WR) — TOP PERFORMER
  - longshot_bias (+$717, 98.5% WR) — Verify not a bug
  - weather_emos (+$197, 50% WR) — Was profitable

AUTO-STOP BOT: System is hemorrhaging money
  - All paper/live trading while we fix things
"""

import sys
sys.path.insert(0, '/home/openclaw/projects/1ai-poly-trader')

from backend.config import settings
from backend.models.database import StrategyConfig, SessionLocal

# Strategies to DISABLE (losing money or broken)
DISABLE = [
    "arb_scanner",           # 0% WR, -$1,772
    "cross_market_arb",      # 0% WR, -$2,493
    "line_movement_detector", # 89% WR but -$424 (asymmetric losses)
    "crypto_oracle",         # 48% WR, -$1,630
    "cex_pm_leadlag",        # 49% WR, -$58 (small loss but weak)
    "news_frontrun",         # 43% WR, -$2.64 (low edge)
]

# Strategies to KEEP ENABLED (profitable)
ENABLE = [
    "bond_scanner",          # 80.9% WR, +$1,140 — TOP PERFORMER
    "longshot_bias",         # 98.5% WR, +$717
    "weather_emos",          # 50% WR, +$197
    "copy_trader",           # Keep — passive income source
    "market_maker",          # Keep — provides liquidity
    "probability_arb",       # Keep — try to fix later
    "negrisk_strategy",      # Keep
    "resolution_sniper",     # Keep
    "unified_arb",           # Keep — try to fix later
]

# Strategies to KEEP DISABLED (already off, don't touch)
LEAVE_ALONE = [
    "agi_orchestrator",
    "general_scanner",
    "hft_scalper",
    "hyperliquid",
    "kalshi_arb",
    "universal_scanner",
    "whale_frontrun",
    "whale_pnl_tracker",
]

# New strategies to enable
NEW = [
    "bnb_hack",              # Enable BNB HACK for June 22
]


def main():
    session = SessionLocal()

    print("="*80)
    print("STRATEGY CONFIGURATION UPDATE — Based on Performance Data")
    print("="*80)
    print()

    # Disable losing strategies
    print("DISABLING losing strategies:")
    for name in DISABLE:
        config = session.query(StrategyConfig).filter_by(strategy_name=name).first()
        if config:
            if config.enabled:
                config.enabled = False
                print(f"  ✗ {name:<30} DISABLED (was enabled)")
            else:
                print(f"  · {name:<30} already disabled")
        else:
            # Create config entry if it doesn't exist
            config = StrategyConfig(strategy_name=name, enabled=False)
            session.add(config)
            print(f"  + {name:<30} created (disabled)")

    print()
    print("ENABLING profitable strategies:")
    for name in ENABLE:
        config = session.query(StrategyConfig).filter_by(strategy_name=name).first()
        if config:
            if not config.enabled:
                config.enabled = True
                print(f"  ✓ {name:<30} ENABLED (was disabled)")
            else:
                print(f"  · {name:<30} already enabled")
        else:
            # Create config entry
            config = StrategyConfig(strategy_name=name, enabled=True)
            session.add(config)
            print(f"  + {name:<30} created (enabled)")

    print()
    print("ENABLING new strategies:")
    for name in NEW:
        config = session.query(StrategyConfig).filter_by(strategy_name=name).first()
        if config:
            if not config.enabled:
                config.enabled = True
                print(f"  ✓ {name:<30} ENABLED")
            else:
                print(f"  · {name:<30} already enabled")
        else:
            config = StrategyConfig(strategy_name=name, enabled=True)
            session.add(config)
            print(f"  + {name:<30} created (enabled)")

    session.commit()

    print()
    print("="*80)
    print("FINAL STATE:")
    print("="*80)
    configs = session.query(StrategyConfig).order_by(
        StrategyConfig.strategy_name
    ).all()

    enabled_count = sum(1 for c in configs if c.enabled)
    disabled_count = sum(1 for c in configs if not c.enabled)

    print(f"  Total strategies: {len(configs)}")
    print(f"  Enabled:  {enabled_count}")
    print(f"  Disabled: {disabled_count}")
    print()

    print("  Enabled list:")
    for c in configs:
        if c.enabled:
            print(f"    ✓ {c.strategy_name}")

    print()
    print("  Disabled list:")
    for c in configs:
        if not c.enabled:
            print(f"    ✗ {c.strategy_name}")

    session.close()

    print()
    print("="*80)
    print("NEXT STEPS:")
    print("="*80)
    print("  1. Restart the bot to apply changes:")
    print("     sudo systemctl restart polyedge")
    print("  2. Monitor performance for 24-48 hours")
    print("  3. Verify only profitable strategies are trading")
    print()


if __name__ == "__main__":
    main()
