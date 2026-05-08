#!/usr/bin/env python3
"""
Enforce paper/shadow lifecycle gating on strategies.

Only btc_oracle (52.1% WR, +$161 PnL on 79 live trades) keeps trading_mode='live'.
All other enabled strategies get trading_mode='paper' until they prove performance.

Run: python scripts/set_trading_mode_gating.py [--dry-run]
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "tradingbot.db"

# Strategy → allowed trading_mode mapping
LIVE_STRATEGIES = {"btc_oracle"}  # proven live metrics only
DEFAULT_MODE = "paper"

# Strategies excluded from gating (not real strategies, already disabled, etc.)
SKIP_STRATEGIES = {
    "auto_trader",       # execution router, not a strategy
    "wallet_import",     # utility, not a strategy
    "unknown",           # artifact
}


def main(dry_run: bool = False):
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get all enabled strategies
    cur.execute("SELECT id, strategy_name, enabled, trading_mode FROM strategy_config ORDER BY id")
    rows = cur.fetchall()

    updates = []
    for row in rows:
        name = row["strategy_name"]
        enabled = row["enabled"]
        current_mode = row["trading_mode"]

        if not enabled:
            continue

        if name in SKIP_STRATEGIES:
            continue

        target_mode = "live" if name in LIVE_STRATEGIES else DEFAULT_MODE

        if current_mode != target_mode:
            updates.append((target_mode, row["id"], name, current_mode))

    print(f"Found {len(rows)} total strategies, {sum(1 for r in rows if r['enabled'])} enabled")
    print(f"{'[DRY RUN] ' if dry_run else ''}{len(updates)} strategies need trading_mode update:\n")

    for target_mode, sid, name, current in updates:
        current_display = current if current else "NULL"
        print(f"  id={sid:2d}  {name:25s}  {current_display:6s} → {target_mode}")

    if dry_run:
        print("\nDry run — no changes made.")
        conn.close()
        return

    if not updates:
        print("All enabled strategies already have correct trading_mode.")
        conn.close()
        return

    # Apply updates
    for target_mode, sid, name, _ in updates:
        cur.execute(
            "UPDATE strategy_config SET trading_mode = ?, updated_at = datetime('now') WHERE id = ?",
            (target_mode, sid),
        )
        print(f"  ✓ Updated {name} → {target_mode}")

    conn.commit()

    # Verify
    print("\n--- Verification ---")
    cur.execute("SELECT strategy_name, enabled, trading_mode FROM strategy_config WHERE enabled = 1 ORDER BY strategy_name")
    for row in cur.fetchall():
        print(f"  {row['strategy_name']:25s}  enabled={row['enabled']}  trading_mode={row['trading_mode']}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    main(dry_run=dry_run)
