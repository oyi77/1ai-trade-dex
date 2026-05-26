"""Seed HFT strategies into StrategyConfig for paper trading.

Registers market_maker, cross_market_arb, crypto_oracle, and cex_pm_leadlag
as enabled strategies with paper trading mode and HFT-appropriate intervals.

Run: python -m backend.scripts.seed_hft_strategies
"""

import sys
import json
from loguru import logger

from backend.models.database import SessionLocal, StrategyConfig, init_db

# HFT strategies to enable in paper mode
HFT_STRATEGIES = [
    {
        "strategy_name": "market_maker",
        "interval_seconds": 120,  # 2 min — market making needs frequent quoting
        "trading_mode": "paper",
        "risk_tier": "moderate",
        "time_horizon": "short",
        "params": json.dumps(
            {
                "base_spread": 0.02,
                "max_inventory": 500.0,
                "quote_size": 25.0,
                "min_spread": 0.01,
                "max_spread": 0.05,
            }
        ),
    },
    {
        "strategy_name": "cross_market_arb",
        "interval_seconds": 300,  # 5 min — cross-platform arb scanning
        "trading_mode": "paper",
        "risk_tier": "moderate",
        "time_horizon": "short",
        "params": json.dumps(
            {
                "min_profit": 0.005,
                "min_spread_pct": 0.013,
            }
        ),
    },
    {
        "strategy_name": "crypto_oracle",
        "interval_seconds": 60,  # 1 min — latency arb needs fast scanning
        "trading_mode": "paper",
        "risk_tier": "moderate",
        "time_horizon": "short",
        "params": None,
    },
    {
        "strategy_name": "cex_pm_leadlag",
        "interval_seconds": 5,  # 5 sec — lead-lag detection
        "trading_mode": "paper",
        "risk_tier": "moderate",
        "time_horizon": "short",
        "params": None,
    },
    {
        "strategy_name": "universal_scanner",
        "interval_seconds": 300,  # 5 min — broad market scanning
        "trading_mode": "paper",
        "risk_tier": "moderate",
        "time_horizon": "mid",
        "params": None,
    },
    {
        "strategy_name": "cross_dex_arb",
        "interval_seconds": 300,  # 5 min — cross-DEX price scanning
        "trading_mode": "paper",
        "risk_tier": "moderate",
        "time_horizon": "short",
        "params": json.dumps(
            {
                "min_profit_pct": 0.005,
                "gas_estimate": 5.0,
            }
        ),
    },
]


def seed_hft_strategies():
    """Seed or update HFT strategy configs for paper trading."""
    init_db()
    db = SessionLocal()

    try:
        created = 0
        updated = 0
        skipped = 0

        for strat in HFT_STRATEGIES:
            existing = (
                db.query(StrategyConfig)
                .filter_by(strategy_name=strat["strategy_name"])
                .first()
            )

            if existing:
                if existing.enabled:
                    # Update interval if HFT strategy needs a faster cycle
                    needs_update = (
                        existing.interval_seconds != strat["interval_seconds"]
                        or existing.trading_mode != strat["trading_mode"]
                    )
                    if needs_update:
                        existing.interval_seconds = strat["interval_seconds"]
                        existing.trading_mode = strat["trading_mode"]
                        existing.risk_tier = strat["risk_tier"]
                        existing.time_horizon = strat["time_horizon"]
                        updated += 1
                        logger.info(
                            f"[seed_hft] {strat['strategy_name']}: UPDATED interval/mode "
                            f"(interval={strat['interval_seconds']}s, mode={strat['trading_mode']})"
                        )
                    else:
                        logger.info(
                            f"[seed_hft] {strat['strategy_name']}: already enabled "
                            f"(mode={existing.trading_mode}, interval={existing.interval_seconds}s) — skipping"
                        )
                        skipped += 1
                    continue

                # Update: enable and set paper mode
                existing.enabled = True
                existing.trading_mode = strat["trading_mode"]
                existing.interval_seconds = strat["interval_seconds"]
                existing.risk_tier = strat["risk_tier"]
                existing.time_horizon = strat["time_horizon"]
                if strat["params"]:
                    existing.params = strat["params"]
                existing.disabled_at = None
                updated += 1
                logger.info(
                    f"[seed_hft] {strat['strategy_name']}: ENABLED in "
                    f"{strat['trading_mode']} mode, interval={strat['interval_seconds']}s"
                )
            else:
                cfg = StrategyConfig(
                    strategy_name=strat["strategy_name"],
                    enabled=True,
                    trading_mode=strat["trading_mode"],
                    interval_seconds=strat["interval_seconds"],
                    risk_tier=strat["risk_tier"],
                    time_horizon=strat["time_horizon"],
                    params=strat["params"],
                )
                db.add(cfg)
                created += 1
                logger.info(
                    f"[seed_hft] {strat['strategy_name']}: CREATED in "
                    f"{strat['trading_mode']} mode, interval={strat['interval_seconds']}s"
                )

        db.commit()

        logger.info(
            f"[seed_hft] Done: {created} created, {updated} enabled, {skipped} already active"
        )

        # Verify
        all_hft = (
            db.query(StrategyConfig)
            .filter(
                StrategyConfig.strategy_name.in_(
                    [s["strategy_name"] for s in HFT_STRATEGIES]
                )
            )
            .all()
        )
        logger.info("[seed_hft] Verification — HFT strategy states:")
        for cfg in all_hft:
            logger.info(
                f"  {cfg.strategy_name}: enabled={cfg.enabled}, "
                f"mode={cfg.trading_mode}, interval={cfg.interval_seconds}s, "
                f"risk={cfg.risk_tier}"
            )

        return created, updated, skipped

    except Exception as e:
        db.rollback()
        logger.error(f"[seed_hft] Failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    created, updated, skipped = seed_hft_strategies()
    print("\nHFT Strategy Seeding Complete:")
    print(f"  Created:  {created}")
    print(f"  Updated:  {updated}")
    print(f"  Skipped:  {skipped}")
    print(f"  Total:    {created + updated + skipped}")
    sys.exit(0)
