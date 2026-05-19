#!/usr/bin/env python3
"""
PolyEdge Monitor — Main entry point.

This is the primary entry point for the autonomous self-wake monitor.
Can be run as a standalone daemon or imported by the scheduler.

Usage:
    python -m backend.agents.monitor.main                    # Start daemon
    python -m backend.agents.monitor.main --once             # Single cycle
    python -m backend.agents.monitor.main --no-alert         # Daemon, no startup alert
    python -m backend.agents.monitor.main --interval 300     # Custom interval
    python -m backend.agents.monitor.main --version          # Version info
"""

import argparse
import asyncio
import json
import os
import sys

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def main():
    parser = argparse.ArgumentParser(
        description="PolyEdge Autonomous Monitor Daemon",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single monitor cycle then exit",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=900,
        help="Monitor interval in seconds (default: 900)",
    )
    parser.add_argument(
        "--report-interval",
        type=int,
        default=3600,
        help="Full report interval in seconds (default: 3600)",
    )
    parser.add_argument(
        "--no-alert",
        action="store_true",
        help="Suppress startup alert",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output report as JSON (only with --once)",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit",
    )

    args = parser.parse_args()

    if args.version:
        print("PolyEdge Monitor v2.0")
        print("Self-wake autonomous monitoring for Polymarket trading stacks")
        return

    from backend.agents.monitor.monitor_daemon import MonitorDaemon

    if args.once:
        # Single cycle
        daemon = MonitorDaemon(
            monitor_interval=args.interval,
            report_interval=args.report_interval,
            alert_on_startup=not args.no_alert,
        )
        report = asyncio.run(daemon.run_once())
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(f"Cycle #{report['cycle']} complete — status: {report['status']}")
            if report.get("warnings"):
                print(f"  Warnings: {len(report['warnings'])}")
            if report.get("critical"):
                print(f"  Critical: {len(report['critical'])}")
            accounts = report.get("accounts", {})
            for mode, acct in accounts.items():
                print(
                    f"  {mode}: ${acct.get('balance', 0):.2f} | "
                    f"PnL ${acct.get('pnl_total', 0):+.2f}"
                )
    else:
        # Continuous daemon
        daemon = MonitorDaemon(
            monitor_interval=args.interval,
            report_interval=args.report_interval,
            alert_on_startup=not args.no_alert,
        )
        daemon.start()
        print(f"🔍 PolyEdge Monitor started (interval={args.interval}s)")
        print("Press Ctrl+C to stop.")

        try:
            while daemon.is_running:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
            daemon.stop()
            print("Done.")


if __name__ == "__main__":
    main()
