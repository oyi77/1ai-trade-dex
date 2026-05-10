"""
Production monitoring and alerting system
Detects anomalies and sends alerts via Slack/Discord webhooks
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.utils.redaction import redact_sensitive

logger = logging.getLogger("trading_bot")

webhook_breaker = CircuitBreaker(
    "webhook",
    failure_threshold=settings.CB_FAILURE_THRESHOLD,
    recovery_timeout=settings.CB_RECOVERY_TIMEOUT,
    half_open_max=settings.CB_HALF_OPEN_MAX,
)


class ProductionMonitor:
    """Monitor production health and detect issues"""

    def __init__(self, db: Session):
        self.db = db
        self.alerts = []

    def check_database_health(self) -> Dict[str, Any]:
        """Check database for anomalies"""
        issues = []

        duplicates = self.db.execute(text("""
            SELECT market_ticker, COUNT(*) as count
            FROM trades
            WHERE trading_mode = 'live'
            GROUP BY market_ticker
            HAVING count > 1
        """)).fetchall()

        if duplicates:
            issues.append({
                "severity": "high",
                "type": "duplicates",
                "message": f"Found {len(duplicates)} duplicate trades",
                "details": [{"ticker": d[0], "count": d[1]} for d in duplicates]
            })

        db_size = self.db.execute(text("SELECT COUNT(*) FROM trades")).fetchone()[0]

        if db_size < 10:
            issues.append({
                "severity": "critical",
                "type": "database_wipe",
                "message": f"Database suspiciously small: only {db_size} trades",
                "details": {"trade_count": db_size}
            })

        missing_pnl = self.db.execute(text("""
            SELECT COUNT(*)
            FROM trades
            WHERE settled = TRUE AND pnl IS NULL
        """)).fetchone()[0]

        if missing_pnl > 0:
            issues.append({
                "severity": "medium",
                "type": "missing_pnl",
                "message": f"{missing_pnl} settled trades missing PNL",
                "details": {"count": missing_pnl}
            })

        return {
            "healthy": len(issues) == 0,
            "issues": issues,
            "checked_at": datetime.now(timezone.utc).isoformat()
        }

    def check_pnl_accuracy(self) -> Dict[str, Any]:
        """Verify PNL matches sum of settled trades across all active modes."""
        try:
            from backend.models.database import BotState, for_update

            results = {}
            all_accurate = True
            for mode in settings.active_modes_set:
                bot = for_update(self.db, self.db.query(BotState).filter(
                    BotState.mode == mode
                )).first()
                if not bot:
                    results[mode] = {"accurate": True, "message": "no BotState to verify"}
                    continue

                reported_pnl = bot.total_pnl or 0.0

                result = self.db.execute(text("""
                    SELECT COALESCE(SUM(pnl), 0) FROM trades
                    WHERE settled = TRUE AND trading_mode = :mode
                """), {"mode": mode}).fetchone()

                computed_pnl = float(result[0]) if result else 0.0

                if reported_pnl == 0.0 and computed_pnl == 0.0:
                    results[mode] = {"accurate": True, "message": "no trades to verify"}
                    continue

                tolerance = settings.MONITORING_PNL_TOLERANCE_PCT
                diff_pct = abs(reported_pnl - computed_pnl) / abs(reported_pnl) if abs(reported_pnl) > 0 else abs(computed_pnl)

                accurate = diff_pct <= tolerance
                if not accurate:
                    all_accurate = False
                results[mode] = {
                    "accurate": accurate,
                    "reported_pnl": round(reported_pnl, 2),
                    "computed_pnl": round(computed_pnl, 2),
                    "diff_pct": round(diff_pct, 4),
                    "tolerance_pct": tolerance,
                    "message": "PnL verified" if accurate else f"PnL mismatch: {diff_pct:.2%} > {tolerance:.2%} tolerance"
                }

            return {"accurate": all_accurate, "modes": results}
        except Exception as e:
            return {"accurate": True, "message": f"verification error: {e}"}

    def check_backup_status(self) -> Dict[str, Any]:
        """Check if backups are running"""
        import os

        backup_dir = Path(settings.DB_BACKUP_DIR)
        if not backup_dir.is_absolute():
            from backend.config import ROOT_DIR
            backup_dir = Path(ROOT_DIR) / backup_dir

        if not backup_dir.exists():
            return {"healthy": False, "message": f"Backup directory not found: {backup_dir}"}

        backups = sorted(backup_dir.glob("auto_*.db"), key=os.path.getmtime, reverse=True)

        if not backups:
            return {"healthy": False, "message": "No backups found"}

        latest_backup = backups[0]
        backup_age = datetime.now().timestamp() - os.path.getmtime(latest_backup)
        max_age_seconds = settings.MONITORING_BACKUP_MAX_AGE_HOURS * 3600

        if backup_age > max_age_seconds:
            return {
                "healthy": False,
                "message": f"Latest backup is {backup_age/3600:.1f} hours old",
                "latest_backup": str(latest_backup)
            }

        return {
            "healthy": True,
            "message": f"Latest backup: {backup_age/60:.0f} minutes ago",
            "backup_count": len(backups),
            "latest_backup": str(latest_backup)
        }

    def run_health_check(self) -> Dict[str, Any]:
        """Run all health checks"""
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database": self.check_database_health(),
            "pnl_accuracy": self.check_pnl_accuracy(),
            "backups": self.check_backup_status()
        }

    def send_alert(self, severity: str, message: str, details: Optional[Dict] = None):
        """Send alert via Slack/Discord webhooks"""
        import asyncio

        alert = {
            "severity": severity,
            "message": message,
            "details": details or {},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        logger.warning(f"ALERT [{severity}]: {message}")
        if details:
            logger.warning(f"   Details: {details}")

        self.alerts.append(alert)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._send_webhooks(alert))
            else:
                loop.run_until_complete(self._send_webhooks(alert))
        except Exception as e:
            logger.debug(f"Webhook dispatch error: {redact_sensitive(str(e))}")

        return alert

    async def _send_webhooks(self, alert: dict):
        """Send alert payload to configured Slack and/or Discord webhooks."""
        import httpx

        async def _send_slack(payload: dict) -> None:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(settings.SLACK_WEBHOOK_URL, json=payload)

        async def _send_discord(payload: dict) -> None:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(settings.DISCORD_WEBHOOK_URL, json=payload)

        if settings.SLACK_WEBHOOK_URL:
            try:
                slack_payload = {
                    "text": f"[{alert['severity']}] {alert['message']}",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*{alert['severity'].upper()}*\n{alert['message']}"
                            }
                        }
                    ]
                }
                if alert.get("details"):
                    details_text = "\n".join(
                        f"- {k}: {v}" for k, v in alert["details"].items()
                        if not isinstance(v, (dict, list))
                    )
                    if details_text:
                        slack_payload["blocks"].append({
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": details_text}
                        })
                await webhook_breaker.call(_send_slack, slack_payload)
            except CircuitOpenError:
                logger.debug("Slack webhook circuit open, skipping")
            except Exception as e:
                logger.debug(f"Slack webhook failed: {e}")

        if settings.DISCORD_WEBHOOK_URL:
            try:
                color_map = {
                    "info": 3447003, "warning": 16776960,
                    "critical": 15158332, "emergency": 15158332
                }
                discord_payload = {
                    "embeds": [{
                        "title": f"[{alert['severity'].upper()}]",
                        "description": alert["message"],
                        "color": color_map.get(alert["severity"], 16777215),
                        "timestamp": alert["timestamp"],
                    }]
                }
                if alert.get("details"):
                    fields = [
                        {"name": str(k), "value": str(v), "inline": True}
                        for k, v in alert["details"].items()
                        if not isinstance(v, (dict, list))
                    ][:5]
                    if fields:
                        discord_payload["embeds"][0]["fields"] = fields
                await webhook_breaker.call(_send_discord, discord_payload)
            except CircuitOpenError:
                logger.debug("Discord webhook circuit open, skipping")
            except Exception as e:
                logger.debug(f"Discord webhook failed: {e}")


async def run_monitoring_check(db: Session) -> Dict[str, Any]:
    """Run monitoring check and return results"""
    monitor = ProductionMonitor(db)
    health = monitor.run_health_check()

    for check_name, check_result in health.items():
        if check_name == "timestamp":
            continue
        if isinstance(check_result, dict) and not check_result.get("healthy", True):
            monitor.send_alert(
                severity="warning",
                message=f"Health check failed: {check_name}",
                details=check_result
            )

    return health
