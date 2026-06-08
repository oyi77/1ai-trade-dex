#!/usr/bin/env python3
"""
PolyEdge Live Performance Monitor

Runs periodically to:
  1. Verify bot is still running
  2. Check current strategy enable/disable state
  3. Get latest performance metrics
  4. Alert if anything is wrong
  5. Log to file for historical tracking

Usage:
  python scripts/monitor_polyedge.py           # One-shot check
  python scripts/monitor_polyedge.py --loop    # Continuous monitoring
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/home/openclaw/projects/1ai-poly-trader')

from backend.config import settings
from backend.models.database import StrategyConfig, BotState, SessionLocal
import httpx

API_URL = "http://localhost:8100"
LOG_FILE = Path("logs/monitor.log")


def check_bot_state() -> dict:
    """Verify bot is running in DB."""
    session = SessionLocal()
    try:
        state = session.query(BotState).first()
        if not state:
            return {"running": False, "error": "no BotState"}
        return {
            "running": state.is_running,
            "last_run": state.last_run.isoformat() if state.last_run else None,
            "bankroll": state.bankroll,
            "mode": state.mode,
        }
    finally:
        session.close()


def check_strategy_state() -> dict:
    """Get current strategy enable/disable state."""
    session = SessionLocal()
    try:
        configs = session.query(StrategyConfig).all()
        enabled = sorted([c.strategy_name for c in configs if c.enabled])
        disabled = sorted([c.strategy_name for c in configs if not c.enabled])
        return {
            "total": len(configs),
            "enabled": enabled,
            "disabled": disabled,
        }
    finally:
        session.close()


def check_api_health() -> dict:
    """Check if API is responding."""
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(f"{API_URL}/api/v1/stats")
            if r.status_code == 200:
                d = r.json()
                return {
                    "alive": True,
                    "bankroll": d.get("bankroll"),
                    "total_pnl": d.get("total_pnl"),
                    "total_trades": d.get("total_trades"),
                    "winning_trades": d.get("winning_trades"),
                }
            return {"alive": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"alive": False, "error": str(e)[:100]}


def check_recent_activity() -> list:
    """Get last 5 trade attempts."""
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(f"{API_URL}/api/v1/trade-attempts?limit=5")
            if r.status_code == 200:
                d = r.json()
                items = d if isinstance(d, list) else d.get("items", [])
                return [
                    {
                        "time": a["created_at"][:19],
                        "strategy": a["strategy"],
                        "status": a["status"],
                        "decision": a["decision"],
                    }
                    for a in items[:5]
                ]
            return []
    except Exception:
        return []


def log_status(status: dict):
    """Append status to log file."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(status) + "\n")


def _activity_freshness_minutes(activities: list) -> float | None:
    """Return age in minutes of the most recent trade attempt, or None."""
    if not activities:
        return None
    from datetime import datetime, timezone

    latest = activities[0]["time"]
    try:
        ts = datetime.fromisoformat(latest.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts).total_seconds() / 60
    except Exception:
        return None


def _append_activity_health(lines: list, activities: list):
    """Append a fresh-activity health line based on most recent trade attempt."""
    age_min = _activity_freshness_minutes(activities)
    if age_min is None:
        return
    if age_min < 5:
        lines.append(f"  ✓ Fresh activity: last attempt {age_min:.1f} min ago")
    elif age_min < 30:
        lines.append(f"  ⚠ Stale activity: last attempt {age_min:.1f} min ago")
    else:
        lines.append(f"  ✗ Very stale: last attempt {age_min:.1f} min ago")


def format_report(status: dict) -> str:
    """Format status as human-readable report."""
    lines = []
    lines.append("=" * 70)
    lines.append(f"PolyEdge Monitor — {status['timestamp']}")
    lines.append("=" * 70)

    lines.append("")
    lines.append("BOT STATE")
    bs = status["bot_state"]
    if bs.get("running"):
        lines.append(f"  ✓ Running | last_run: {bs.get('last_run')} | bankroll: ${bs.get('bankroll')}")
    else:
        lines.append(f"  ✗ NOT RUNNING | error: {bs.get('error', 'unknown')}")

    # Use trade activity freshness as the real health signal since
    # BotState.last_run is only updated by market/weather scan jobs.
    _append_activity_health(lines, status.get("recent_activity", []))

    lines.append("")
    lines.append("API HEALTH")
    ah = status["api_health"]
    if ah.get("alive"):
        lines.append(f"  ✓ Alive | PnL: ${ah.get('total_pnl', 0):+.2f} | trades: {ah.get('total_trades', 0)}")
    else:
        lines.append(f"  ✗ NOT ALIVE | error: {ah.get('error', 'unknown')}")

    lines.append("")
    lines.append("STRATEGY CONFIG")
    sc = status["strategy_state"]
    lines.append(f"  Total: {sc['total']} | Enabled: {len(sc['enabled'])} | Disabled: {len(sc['disabled'])}")
    lines.append(f"  Enabled:  {', '.join(sc['enabled'])}")

    if status.get("recent_activity"):
        lines.append("")
        lines.append("RECENT ACTIVITY (last 5 trade attempts)")
        for a in status["recent_activity"]:
            lines.append(f"  {a['time']} | {a['strategy']:<20} | {a['status']:<8} | {a['decision']}")

    lines.append("")
    return "\n".join(lines)


def monitor_once() -> dict:
    """Run one monitoring check."""
    status = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bot_state": check_bot_state(),
        "api_health": check_api_health(),
        "strategy_state": check_strategy_state(),
        "recent_activity": check_recent_activity(),
    }
    log_status(status)
    return status


def monitor_loop(interval_seconds: int = 60):
    """Continuous monitoring loop."""
    print(f"Starting monitor (interval: {interval_seconds}s). Ctrl+C to stop.")
    try:
        while True:
            status = monitor_once()
            print(format_report(status))
            print(f"\nNext check in {interval_seconds}s...\n")
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\nMonitor stopped.")


def main():
    parser = argparse.ArgumentParser(description="PolyEdge live performance monitor")
    parser.add_argument("--loop", action="store_true", help="Continuous monitoring")
    parser.add_argument("--interval", type=int, default=60, help="Loop interval (seconds)")
    args = parser.parse_args()

    if args.loop:
        monitor_loop(args.interval)
    else:
        status = monitor_once()
        print(format_report(status))
        print(f"Logged to: {LOG_FILE}")


if __name__ == "__main__":
    main()
