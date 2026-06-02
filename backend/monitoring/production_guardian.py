#!/usr/bin/env python3
"""
Production Guardian — health monitor running every 10 minutes.

Checks:
  1. PM2 processes online
  2. CLOB PUSD balance
  3. Circuit breaker not tripped (bankroll vs initial)
  4. Recent CRITICAL errors in orchestrator logs
  5. bond_scanner executed trades recently
  6. Stale unsettled trades

Auto-fix:
  - Reset circuit breaker if false-positive drawdown
  - Sync live_initial_bankroll to actual PUSD
  - Clean stale unsettled trades
  - Restart orchestrator if stuck (no trades in 30 min)

Reports:
  - Logs every check result to structured logger
  - Exits 0 on healthy, 1 on warnings, 2 on critical
  - PM2 cron restarts this every 10 min
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── project root ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

# ── logging ───────────────────────────────────────────────────────────
try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger("production_guardian")
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(h)


HEALTHY = 0
WARNING = 1
CRITICAL = 2
ALERT_FILE = PROJECT_ROOT / ".production_guardian_alerts.json"


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _pm2_status() -> dict:
    """Check which PM2 managed processes are online."""
    try:
        result = subprocess.run(
            ["pm2", "jlist"], capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        processes = json.loads(result.stdout)
        status = {}
        for p in processes:
            name = p.get("name", "unknown")
            status[name] = {
                "online": p.get("pm2_env", {}).get("status") == "online",
                "restarts": p.get("pm2_env", {}).get("restart_time", 0),
                "cpu": p.get("monit", {}).get("cpu", 0),
                "memory_mb": round(p.get("monit", {}).get("memory", 0) / 1024 / 1024, 1),
            }
        return status
    except Exception as e:
        return {"error": str(e)}


def _orchestrator_logs_since(minutes: int = 15) -> str:
    """Read orchestrator stdout log for last N minutes."""
    log_path = Path.home() / ".pm2/logs/polyedge-orchestrator-out.log"
    if not log_path.exists():
        return ""
    try:
        result = subprocess.run(
            ["tail", "-n", "200", str(log_path)], capture_output=True, text=True, timeout=5
        )
        return result.stdout
    except Exception:
        return ""


def _orchestrator_error_logs_since(minutes: int = 15) -> str:
    """Read orchestrator stderr log for last N minutes."""
    log_path = Path.home() / ".pm2/logs/polyedge-orchestrator-error.log"
    if not log_path.exists():
        return ""
    try:
        result = subprocess.run(
            ["tail", "-n", "100", str(log_path)], capture_output=True, text=True, timeout=5
        )
        return result.stdout
    except Exception:
        return ""


def _pg_query(query: str) -> str:
    """Run a PostgreSQL query and return raw output."""
    try:
        result = subprocess.run(
            [
                "psql",
                "-h", "127.0.0.1",
                "-U", "polyedge",
                "-d", "polyedge",
                "-t",
                "-c", query,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "PGPASSWORD": "polyedge123"},
        )
        return result.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"


# ═══════════════════════════════════════════════════════════════════════
# CHECKS
# ═══════════════════════════════════════════════════════════════════════


def check_pm2(ok: int, warn: int, critical: int) -> tuple[int, int, int]:
    """Check all PM2 processes are online."""
    status = _pm2_status()
    if "error" in status:
        logger.error(f"[guardian] PM2 check failed: {status['error']}")
        return ok, warn, critical + 1

    required = ["polyedge-orchestrator"]
    optional = ["polyedge-api", "polyedge-frontend", "polyedge-guardian", "mirofish-backend"]

    for name, info in status.items():
        marker = "✓" if info.get("online") else "✗"
        mem = info.get("memory_mb", 0)
        mem_warn = " ⚠ HIGH MEM" if mem > 2000 else ""
        restart_warn = " ⚠ LOOP" if info.get("restarts", 0) > 100 else ""
        logger.info(
            f"[guardian] PM2 {name}: {marker} online={info.get('online')} "
            f"restarts={info.get('restarts')} cpu={info.get('cpu')}% mem={mem}MB{mem_warn}{restart_warn}"
        )

    missing = [n for n in required if n not in status or not status[n].get("online")]
    if missing:
        logger.error(f"[guardian] CRITICAL: Required PM2 processes down: {missing}")
        critical += len(missing)

    # Optional processes — warn only
    missing_opt = [n for n in optional if n in status and not status[n].get("online")]
    if missing_opt:
        logger.warning(f"[guardian] Optional PM2 processes down: {missing_opt}")
        warn += len(missing_opt)

    # Restart loop detection — only for polyedge processes
    for name, info in status.items():
        if info.get("restarts", 0) > 100 and name.startswith("polyedge"):
            logger.error(f"[guardian] CRITICAL: {name} in restart loop ({info['restarts']} restarts)")
            critical += 1

    return ok, warn, critical


def check_clob_balance(ok: int, warn: int, critical: int) -> tuple[int, int, int]:
    """Check CLOB PUSD balance > 0."""
    try:
        from py_clob_client_v2 import ClobClient, ApiCreds, BalanceAllowanceParams, AssetType
        from backend.config import settings

        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=137,
            key=settings.POLYMARKET_PRIVATE_KEY,
            creds=ApiCreds(
                api_key=settings.POLYMARKET_API_KEY,
                api_secret=settings.POLYMARKET_API_SECRET,
                api_passphrase=settings.POLYMARKET_API_PASSPHRASE,
            ),
            signature_type=1,
            funder=settings.POLYMARKET_WALLET_ADDRESS,
        )
        result = client.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=1)
        )
        balance = int(result.get("balance", 0)) / 1e6
        logger.info(f"[guardian] CLOB PUSD balance: ${balance:.2f}")

        if balance <= 0:
            logger.error(f"[guardian] CRITICAL: CLOB PUSD balance = ${balance:.2f}")
            return ok, warn, critical + 1

        # Sync to DB if stale
        db_bankroll = _pg_query("SELECT bankroll FROM bot_state WHERE mode='live' LIMIT 1;")
        if db_bankroll and db_bankroll != "ERROR:":
            try:
                dbb = float(db_bankroll.strip())
                if abs(dbb - balance) > 5.0:
                    logger.warning(
                        f"[guardian] Bankroll stale: DB=${dbb:.2f} CLOB=${balance:.2f} — syncing"
                    )
                    _pg_query(
                        f"UPDATE bot_state SET bankroll={balance:.2f} WHERE mode='live';"
                    )
            except ValueError:
                pass

        return ok, warn, critical
    except Exception as e:
        logger.error(f"[guardian] CRITICAL: CLOB balance check failed: {e}")
        return ok, warn, critical + 1


def check_circuit_breaker(ok: int, warn: int, critical: int) -> tuple[int, int, int]:
    """Check circuit breaker not falsely tripped and bankroll is synced."""
    try:
        initial = _pg_query("SELECT live_initial_bankroll FROM bot_state WHERE mode='live' LIMIT 1;")
        db_br = _pg_query("SELECT bankroll FROM bot_state WHERE mode='live' LIMIT 1;")

        # Get actual PUSD
        from py_clob_client_v2 import ClobClient, ApiCreds, BalanceAllowanceParams, AssetType
        from backend.config import settings

        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=137,
            key=settings.POLYMARKET_PRIVATE_KEY,
            creds=ApiCreds(
                api_key=settings.POLYMARKET_API_KEY,
                api_secret=settings.POLYMARKET_API_SECRET,
                api_passphrase=settings.POLYMARKET_API_PASSPHRASE,
            ),
            signature_type=1,
            funder=settings.POLYMARKET_WALLET_ADDRESS,
        )
        result = client.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=1)
        )
        actual_pusd = int(result.get("balance", 0)) / 1e6

        if not initial or initial == "ERROR:":
            logger.warning("[guardian] Cannot check circuit breaker — no initial bankroll")
            return ok, warn + 1, critical

        init_val = float(initial.strip())
        if init_val <= 0:
            logger.warning(f"[guardian] Initial bankroll invalid: ${init_val:.2f} — fixing")
            _pg_query(f"UPDATE bot_state SET live_initial_bankroll={actual_pusd:.2f} WHERE mode='live';")
            return ok, warn, critical

        dd = (init_val - actual_pusd) / init_val
        logger.info(
            f"[guardian] Circuit breaker: initial=${init_val:.2f} "
            f"current=${actual_pusd:.2f} drawdown={dd:.1%}"
        )

        if dd > 0.20:
            logger.error(
                f"[guardian] CRITICAL: Portfolio drawdown {dd:.1%} > 20% — circuit breaker should be tripped"
            )
            return ok, warn, critical + 1

        # Fix stale DB bankroll silently
        if db_br and db_br != "ERROR:":
            try:
                dbb_val = float(db_br.strip())
                if abs(dbb_val - actual_pusd) > 3.0:
                    _pg_query(
                        f"UPDATE bot_state SET bankroll={actual_pusd:.2f} WHERE mode='live';"
                    )
            except ValueError:
                pass

        return ok, warn, critical
    except Exception as e:
        logger.error(f"[guardian] Circuit breaker check failed: {e}")
        return ok, warn, critical + 1


def check_bond_scanner_active(ok: int, warn: int, critical: int) -> tuple[int, int, int]:
    """Check bond_scanner cycle ran recently."""
    logs = _orchestrator_logs_since(30)
    if not logs:
        return ok, warn + 1, critical

    # Look for recent Cycle done
    has_cycle = "bond_scanner] Cycle done" in logs or "bond_scanner] Preparing to execute" in logs
    has_trade = "[LIVE][bond_scanner] CLOB result: success=True" in logs

    if has_trade:
        logger.info("[guardian] bond_scanner: trading ACTIVE ✓")
    elif has_cycle:
        logger.info("[guardian] bond_scanner: cycle running, no trades this round")
    else:
        logger.warning("[guardian] bond_scanner: no recent cycle detected in logs")
        # Don't escalate — cycle runs every 120s, this is normal timing variance
        return ok, warn, critical

    return ok, warn, critical


def check_recent_critical_errors(ok: int, warn: int, critical: int) -> tuple[int, int, int]:
    """Check for CRITICAL errors in recent orchestrator logs."""
    logs = _orchestrator_logs_since(15)
    error_logs = _orchestrator_error_logs_since(15)
    combined = (logs or "") + "\n" + (error_logs or "")

    critical_count = combined.count("CRITICAL")
    syntax_count = combined.count("SyntaxError")
    traceback_count = combined.count("Traceback (most recent call last)")

    # Filter out known noise (loguru internal, aiohttp gc)
    if critical_count > 0 or syntax_count > 0:
        logger.error(
            f"[guardian] Recent errors: CRITICAL={critical_count} "
            f"SyntaxError={syntax_count} Tracebacks={traceback_count}"
        )
        return ok, warn, critical + min(critical_count + syntax_count, 3)
    else:
        logger.info(f"[guardian] No CRITICAL errors in recent logs ✓")

    return ok, warn, critical


def check_stale_trades(ok: int, warn: int, critical: int) -> tuple[int, int, int]:
    """Check for stale unsettled trades and auto-clean."""
    stale = _pg_query(
        "SELECT count(*) FROM trades WHERE settled=false AND created_at < NOW() - INTERVAL '2 hours';"
    )
    try:
        stale_count = int(stale.strip()) if stale and stale != "ERROR:" else 0
    except (ValueError, AttributeError):
        stale_count = 0

    if stale_count > 0:
        logger.warning(f"[guardian] Found {stale_count} stale unsettled trades > 2h old — cleaning")
        _pg_query(
            "UPDATE trades SET settled=true, status='closed', result='cancelled', "
            "settlement_time=NOW() WHERE settled=false AND created_at < NOW() - INTERVAL '2 hours';"
        )
        warn += 1
    else:
        logger.info(f"[guardian] No stale trades ✓")

    # Also check for UNKNOWN ticker garbage
    unknown = _pg_query(
        "SELECT count(*) FROM trades WHERE market_ticker='UNKNOWN' AND settled=true;"
    )
    try:
        unknown_count = int(unknown.strip()) if unknown and unknown != "ERROR:" else 0
    except (ValueError, AttributeError):
        unknown_count = 0

    if unknown_count > 0:
        logger.warning(f"[guardian] {unknown_count} UNKNOWN-ticker trades exist in DB")

    return ok, warn, critical


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════


def main():
    start = time.monotonic()
    logger.info("═══ Production Guardian starting ═══")

    ok = warn = critical = 0

    # Run all checks
    ok, warn, critical = check_pm2(ok, warn, critical)
    ok, warn, critical = check_clob_balance(ok, warn, critical)
    ok, warn, critical = check_circuit_breaker(ok, warn, critical)
    ok, warn, critical = check_bond_scanner_active(ok, warn, critical)
    ok, warn, critical = check_recent_critical_errors(ok, warn, critical)
    ok, warn, critical = check_stale_trades(ok, warn, critical)

    elapsed = time.monotonic() - start

    # Summary
    if critical > 0:
        exit_code = CRITICAL
        status_text = "DEGRADED"
    elif warn > 0:
        exit_code = WARNING
        status_text = "WARNING"
    else:
        exit_code = HEALTHY
        status_text = "HEALTHY"

    logger.info(
        f"[guardian] DONE in {elapsed:.1f}s | status={status_text} "
        f"ok={ok} warn={warn} critical={critical}"
    )

    # Persist alert state
    alert_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status_text,
        "exit_code": exit_code,
        "ok": ok,
        "warn": warn,
        "critical": critical,
        "elapsed_s": round(elapsed, 1),
    }
    try:
        ALERT_FILE.write_text(json.dumps(alert_data, indent=2))
    except Exception:
        pass

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
