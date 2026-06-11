#!/usr/bin/env python3
"""Enable APEX strategy in StrategyConfig for paper trading.

Idempotent. Run from the project root:
    python scripts/enable_apex_paper.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make backend importable
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from backend.db.utils import get_db_session  # noqa: E402
from backend.models.database import StrategyConfig  # noqa: E402

APEX_NAME = "apex"
APEX_INTERVAL = 120  # seconds; 2min cycle matches the strategy's default_params
APEX_PARAMS = {
    "min_edge_pp": 2.0,
    "min_confidence": 0.5,
    "max_concurrent": 10,
    "bankroll_pct": 0.08,
    "kelly_fraction": 0.25,
    "profit_target_pct": 0.025,
    "stop_loss_pct": 0.04,
    "max_hold_seconds": 7200,
    "scan_interval": 120,
}


def main() -> int:
    # Force APEX import so STRATEGY_REGISTRY is populated
    from backend.strategies.registry import STRATEGY_REGISTRY  # noqa: E402

    if APEX_NAME not in STRATEGY_REGISTRY:
        print(
            f"ERROR: {APEX_NAME!r} not in STRATEGY_REGISTRY. "
            "Check backend/strategies/__init__.py imports."
        )
        print(f"Registered: {sorted(STRATEGY_REGISTRY.keys())}")
        return 1

    print(f"OK: {APEX_NAME!r} registered. Class: {STRATEGY_REGISTRY[APEX_NAME].__name__}")

    with get_db_session() as db:
        existing = (
            db.query(StrategyConfig)
            .filter(StrategyConfig.strategy_name == APEX_NAME)
            .one_or_none()
        )

        if existing is None:
            row = StrategyConfig(
                strategy_name=APEX_NAME,
                enabled=True,
                params=json.dumps(APEX_PARAMS),
                interval_seconds=APEX_INTERVAL,
                trading_mode="paper",
                mode="paper",
                time_horizon="mid",
                risk_tier="moderate",
                protected=False,
            )
            db.add(row)
            print(f"Inserted new StrategyConfig row for {APEX_NAME}")
        else:
            existing.enabled = True
            existing.interval_seconds = APEX_INTERVAL
            existing.trading_mode = "paper"
            existing.mode = "paper"
            existing.disabled_at = None
            existing.params = json.dumps(APEX_PARAMS)
            existing.risk_tier = "moderate"
            existing.time_horizon = "mid"
            print(
                f"Updated existing StrategyConfig row for {APEX_NAME} "
                f"(id={existing.id})"
            )

        db.commit()

    # Verify
    with get_db_session() as db:
        row = (
            db.query(StrategyConfig)
            .filter(StrategyConfig.strategy_name == APEX_NAME)
            .one()
        )
        print("\n--- Final state ---")
        print(f"strategy_name : {row.strategy_name}")
        print(f"enabled       : {row.enabled}")
        print(f"trading_mode  : {row.trading_mode}")
        print(f"mode          : {row.mode}")
        print(f"interval      : {row.interval_seconds}s")
        print(f"risk_tier     : {row.risk_tier}")
        print(f"params        : {row.params}")
        print(f"disabled_at   : {row.disabled_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
