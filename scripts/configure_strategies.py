#!/usr/bin/env python3
"""Configure aggressive trading strategies in fresh database."""
import sqlite3
import time
import sys

DB_PATH = 'tradingbot.db'

# Winning strategies to enable (based on analysis)
WINNING_STRATEGIES = [
    'cex_pm_leadlag',
    'copy_trader',
    'general_scanner',
]

# Losing strategies to disable (0% win rate)
LOSING_STRATEGIES = [
    'btc_oracle',
    'weather_emos',
    'auto_trader',
    'btc_momentum',
    'realtime_scanner',
    'whale_pnl_tracker',
    'market_maker',
    'bond_scanner',
    'line_movement_detector',
    'universal_scanner',
    'probability_arb',
    'cross_market_arb',
    'whale_frontrun',
]

def wait_for_db(max_attempts=30):
    """Wait for database to be created by bot."""
    for i in range(max_attempts):
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("SELECT 1 FROM strategy_config LIMIT 1")
            conn.close()
            print(f"✓ Database ready after {i+1} attempts")
            return True
        except sqlite3.OperationalError as e:
            if 'no such table' not in str(e):
                print(f"Error: {e}")
                return False
            time.sleep(1)
    print("ERROR: Database not ready after timeout")
    return False

def configure_strategies():
    """Set aggressive strategy configuration."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    print("\n=== CONFIGURING STRATEGIES ===")

    # Enable winning strategies with aggressive intervals
    for strategy in WINNING_STRATEGIES:
        c.execute("""
            UPDATE OR IGNORE strategy_config
            SET enabled = 1,
                interval_seconds = 15,
                updated_at = CURRENT_TIMESTAMP
            WHERE strategy_name = ?
        """, (strategy,))
        if c.rowcount > 0:
            print(f"  ✓ Updated: {strategy}")
        else:
            print(f"  ⚠ Not found: {strategy} (will be added by bot)")

    # Disable losing strategies
    for strategy in LOSING_STRATEGIES:
        c.execute("""
            UPDATE strategy_config
            SET enabled = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE strategy_name = ?
        """, (strategy,))
        if c.rowcount > 0:
            print(f"  ✓ Disabled: {strategy}")

    # Verify cex_pm_leadlag has aggressive params
    c.execute("SELECT params FROM strategy_config WHERE strategy_name = 'cex_pm_leadlag'")
    row = c.fetchone()
    if row and row[0]:
        import json
        params = json.loads(row[0])
        params['min_edge'] = 0.30  # Aggressive 30% edge
        params['min_momentum'] = 0.002
        c.execute("UPDATE strategy_config SET params = ? WHERE strategy_name = 'cex_pm_leadlag'",
                  (json.dumps(params),))
        print(f"  ✓ cex_pm_leadlag params updated: {params}")

    conn.commit()
    conn.close()
    print("\n✓ Strategy configuration complete!")

def verify():
    """Verify final configuration."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT strategy_name, enabled, interval_seconds FROM strategy_config ORDER BY strategy_name")
    rows = c.fetchall()
    print("\n=== FINAL STRATEGY CONFIGS ===")
    for name, enabled, interval in rows:
        status = "ENABLED" if enabled else "disabled"
        print(f"  [{status}] {name}: every {interval}s")
    conn.close()

if __name__ == '__main__':
    print("Waiting for database to be ready...")
    if wait_for_db():
        configure_strategies()
        verify()
        sys.exit(0)
    else:
        sys.exit(1)
