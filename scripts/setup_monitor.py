#!/usr/bin/env python3
"""
Setup script — installs & configures the autonomous monitor.

Run once after deploying the monitor module:
    python scripts/setup_monitor.py

This will:
1. Install systemd service (requires sudo)
2. Add AGI scheduler job for periodic self-wake
3. Create log directories
4. Test the monitor with a single cycle
5. Report results
"""

import asyncio
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
MONITOR_DIR = PROJECT_DIR / "backend" / "agents" / "monitor"
DEPLOY_DIR = PROJECT_DIR / "deploy"
VENV_DIR = PROJECT_DIR / "venv"
SERVICE_FILE = DEPLOY_DIR / "polyedge-monitor.service"
LOG_DIR = PROJECT_DIR / "logs"


def print_step(step: str, status: str, detail: str = ""):
    emoji = {"ok": "✅", "skip": "⏭️", "warn": "⚠️", "err": "❌", "info": "ℹ️"}.get(
        status, "➡"
    )
    print(f"{emoji}  {step}: {detail}" if detail else f"{emoji}  {step}")


def check_prerequisites() -> bool:
    """Verify all prerequisites are met."""
    ok = True

    if not MONITOR_DIR.exists():
        print_step("Monitor directory", "err", f"Not found at {MONITOR_DIR}")
        ok = False
    else:
        required_files = [
            "__init__.py",
            "monitor_daemon.py",
            "strategy_performance.py",
            "account_summary.py",
            "alerts.py",
            "research_assistant.py",
            "self_wake.sh",
            "main.py",
        ]
        for f in required_files:
            if not (MONITOR_DIR / f).exists():
                print_step(f"File: {f}", "err", "Missing")
                ok = False

    if not SERVICE_FILE.exists():
        print_step("Service file", "warn", f"Not found at {SERVICE_FILE}")

    if not VENV_DIR.exists():
        print_step("Virtual env", "warn", "No venv found — will use system Python")

    return ok


def install_systemd_service() -> bool:
    """Install the systemd service (requires sudo)."""
    if not SERVICE_FILE.exists():
        print_step("Systemd service", "skip", "Service file not found")
        return False

    try:
        service_name = SERVICE_FILE.name
        target = Path("/etc/systemd/system") / service_name

        subprocess.run(
            ["sudo", "cp", str(SERVICE_FILE), str(target)],
            check=True,
            capture_output=True,
        )
        print_step("Systemd: copy service", "ok")

        subprocess.run(
            ["sudo", "systemctl", "daemon-reload"],
            check=True,
            capture_output=True,
        )
        print_step("Systemd: daemon-reload", "ok")

        subprocess.run(
            ["sudo", "systemctl", "enable", service_name],
            check=True,
            capture_output=True,
        )
        print_step("Systemd: enable service", "ok", service_name)

        return True

    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else ""
        print_step("Systemd install", "err", stderr[:150])
        print_step(
            "Run manually", "info", f"sudo cp {SERVICE_FILE} /etc/systemd/system/"
        )
        return False

    except FileNotFoundError:
        print_step("Systemd install", "skip", "sudo not available (not a blocker)")
        return False


def set_executable_permissions():
    """Make shell scripts executable."""
    sh_scripts = list(MONITOR_DIR.glob("*.sh"))
    for script in sh_scripts:
        script.chmod(0o755)
        print_step(f"Permissions: {script.name}", "ok", "chmod +x")


def test_monitor_single_cycle() -> bool:
    """Run a single monitor cycle to verify it works."""
    print("\n" + "=" * 60)
    print("🔍  Testing: Single monitor cycle...")
    print("=" * 60)

    try:
        sys.path.insert(0, str(PROJECT_DIR))

        from backend.agents.monitor.monitor_daemon import MonitorDaemon

        d = MonitorDaemon(alert_on_startup=False)
        report = asyncio.run(d.run_once())

        print(f"Status: {report['status'].upper()}")
        print(f"Cycle: #{report['cycle']}")

        accounts = report.get("accounts", {})
        for mode, acct in accounts.items():
            print(
                f"  {mode}: ${acct.get('balance', 0):.2f} | "
                f"PnL ${acct.get('pnl_total', 0):+.2f}"
            )

        strategies = report.get("strategies", {})
        if strategies:
            print(f"  Strategies tracked: {len(strategies)}")
            for name, sr in list(strategies.items())[:5]:
                print(
                    f"    {name}: {sr.get('total_trades', 0)}t | "
                    f"${sr.get('pnl', 0):+.2f}"
                )
            if len(strategies) > 5:
                print(f"    ... and {len(strategies) - 5} more")

        if report.get("warnings"):
            print(f"  ⚠️ Warnings: {len(report['warnings'])}")
        if report.get("critical"):
            print(f"  🚨 Critical: {len(report['critical'])}")
        if report.get("research", {}).get("suggestions"):
            print(f"  💡 Suggestions: {len(report['research']['suggestions'])}")

        print_step("Test cycle", "ok" if report["status"] != "error" else "warn")
        return report["status"] != "error"

    except Exception as e:
        print_step("Test cycle", "err", str(e))
        return False


def add_agi_scheduler_job():
    """Integration note for adding to AGI scheduler."""
    print()
    print("=" * 60)
    print("📋  AGI Scheduler Integration")
    print("=" * 60)
    print()
    print("To integrate with the existing AGI scheduler, add this job:")
    print()
    print("  # In backend/core/scheduling/scheduling_strategies.py:")
    print()
    print("  async def monitor_cycle_job():")
    print('      """Self-wake monitor cycle (runs every 5 min)."""')
    print("      from backend.agents.monitor.monitor_daemon import MonitorDaemon")
    print("      d = MonitorDaemon(alert_on_startup=False)")
    print("      await d.run_once()")
    print()
    print("  # Then in backend/core/scheduling/scheduler.py start_scheduler():")
    print("  scheduler.add_job(")
    print("      monitor_cycle_job,")
    print("      IntervalTrigger(minutes=5),")
    print('      id="monitor_cycle",')
    print("      replace_existing=True,")
    print("      max_instances=1,")
    print("  )")


def main():
    print("=" * 60)
    print("🔧  PolyEdge Monitor Setup")
    print("=" * 60)
    print()

    # Step 1: Prerequisites
    print("📋  Step 1: Checking prerequisites...")
    if not check_prerequisites():
        print("\n❌ Prerequisites not met. Fix the issues above.")
        sys.exit(1)
    print_step("Prerequisites", "ok")

    # Step 2: Permissions
    print("\n📋  Step 2: Setting permissions...")
    set_executable_permissions()

    # Step 3: Create log directory
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    print_step("Log directory", "ok", str(LOG_DIR))

    # Step 4: Systemd (optional — may fail without sudo)
    print("\n📋  Step 3: Installing systemd service...")
    install_systemd_service()

    # Step 5: Test
    print("\n📋  Step 4: Testing monitor...")
    test_ok = test_monitor_single_cycle()
    if not test_ok:
        print("\n⚠️  Test had errors — check the log above.")
        print(
            "   The monitor may still work if the errors are expected "
            "(e.g., empty DB)."
        )

    # Step 6: Integration
    add_agi_scheduler_job()

    # Summary
    print()
    print("=" * 60)
    print("📊  Setup Complete")
    print("=" * 60)
    print()
    print("  Start daemon:")
    print(f"    python {MONITOR_DIR / 'self_wake.sh'} start")
    print()
    print("  Run single cycle:")
    print(f"    python {MONITOR_DIR / 'self_wake.sh'} once")
    print()
    print("  Check status:")
    print(f"    python {MONITOR_DIR / 'self_wake.sh'} status")
    print()
    if test_ok:
        print("  ✅ Monitor is operational.")
    else:
        print("  ⚠️  Monitor has warnings — review logs.")
    print()


if __name__ == "__main__":
    main()
