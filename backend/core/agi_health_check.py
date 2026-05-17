"""AGI system health check — validates strategy health, data freshness, budget, orphaned positions."""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.database import SessionLocal, Trade, StrategyConfig, BotState, for_update

from loguru import logger
class AGIHealthChecker:
    """Runs periodic system health checks for the AGI autonomy loop."""

    def run_checks(self, db: Optional[Session] = None) -> dict:
        _owned = db is None
        db = db or SessionLocal()
        results = {}
        try:
            results["strategy_health"] = self._check_strategies(db)
            results["data_freshness"] = self._check_data_freshness(db)
            results["budget"] = self._check_budget(db)
            results["scheduler"] = self._check_scheduler()
            results["orphaned_positions"] = self._check_orphaned_positions(db)
            results["disk_space"] = self._check_disk_space()

            passed = sum(1 for v in results.values() if v.get("healthy", False))
            total = len(results)
            results["summary"] = {
                "passed": passed,
                "total": total,
                "all_healthy": passed == total,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }

            if not results["summary"]["all_healthy"]:
                issues = [k for k, v in results.items() if k != "summary" and not v.get("healthy", False)]
                logger.warning("[AGIHealth] Issues detected: %s", issues)
            else:
                logger.info("[AGIHealth] All checks passed")

            return results
        except Exception as e:
            logger.error("[AGIHealth] Health check failed: %s", e)
            return {"error": str(e), "summary": {"passed": 0, "total": 0, "all_healthy": False}}
        finally:
            if _owned:
                db.close()

    def _check_strategies(self, db: Session) -> dict:
        try:
            configs = db.query(StrategyConfig).filter(StrategyConfig.enabled).all()
            if not configs:
                return {"healthy": True, "enabled_count": 0}

            now = datetime.now(timezone.utc)
            stale_threshold = timedelta(hours=settings.AGI_HEALTH_STALE_STRATEGY_HOURS)
            stale = []
            for c in configs:
                last_run = getattr(c, "last_run_at", None)
                if last_run:
                    if last_run.tzinfo is None:
                        last_run = last_run.replace(tzinfo=timezone.utc)
                    if now - last_run > stale_threshold:
                        stale.append(c.strategy_name)

            return {
                "healthy": len(stale) == 0,
                "enabled_count": len(configs),
                "stale_strategies": stale,
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    def _check_data_freshness(self, db: Session) -> dict:
        try:
            latest_signal = db.query(Trade.timestamp).order_by(Trade.timestamp.desc()).first()
            if not latest_signal or not latest_signal[0]:
                return {"healthy": True, "note": "no trades yet"}

            ts = latest_signal[0]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            return {
                "healthy": age_hours < settings.AGI_HEALTH_DATA_FRESHNESS_HOURS,
                "latest_trade_age_hours": round(age_hours, 1),
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    def _check_budget(self, db: Session) -> dict:
        try:
            from backend.config import settings

            unhealthy_modes = []
            for mode in settings.active_modes_set:
                bot = for_update(db, db.query(BotState).filter(
                    BotState.mode == mode
                )).first()
                if not bot:
                    unhealthy_modes.append({"mode": mode, "reason": "no BotState found"})
                    continue

                bankroll = bot.bankroll or 0.0
                if bankroll <= 0:
                    unhealthy_modes.append({"mode": mode, "reason": "bankroll depleted", "bankroll": bankroll})
                    continue

                daily_loss = bot.daily_pnl or 0.0
                loss_limit = settings.DAILY_LOSS_LIMIT
                near_limit = abs(daily_loss) > loss_limit * settings.AGI_HEALTH_BUDGET_NEAR_LIMIT_PCT if daily_loss < 0 else False

                if near_limit:
                    unhealthy_modes.append({"mode": mode, "reason": "near daily loss limit", "daily_loss": daily_loss})

            if unhealthy_modes:
                return {"healthy": False, "reason": "budget issues in active modes", "modes": unhealthy_modes}
            return {"healthy": True}
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    def _check_scheduler(self) -> dict:
        try:
            from backend.core.scheduler import scheduler
            jobs = scheduler.get_jobs()
            if not jobs:
                return {"healthy": False, "reason": "no scheduled jobs"}
            return {"healthy": True, "job_count": len(jobs)}
        except Exception as e:
            return {"healthy": True, "note": "scheduler not accessible", "error": str(e)}

    def _check_orphaned_positions(self, db: Session) -> dict:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=settings.AGI_HEALTH_ORPHAN_MAX_AGE_DAYS)
            orphans = (
                db.query(Trade)
                .filter(
                    Trade.settled.is_(False),
                    Trade.timestamp < cutoff,
                )
                .count()
            )
            return {"healthy": orphans == 0, "orphaned_count": orphans}
        except Exception as e:
            return {"healthy": False, "error": str(e)}


    def _check_disk_space(self) -> dict:
        """Check disk usage for the DB partition and data directories."""
        import shutil
        import os

        try:
            from backend.config import ROOT_DIR
            data_dir = str(ROOT_DIR)

            usage = shutil.disk_usage(data_dir)
            used_pct = (usage.used / usage.total) * 100
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)

            warn_pct = getattr(settings, "DISK_SPACE_WARN_PCT", 90.0)
            healthy = used_pct < warn_pct

            result = {
                "healthy": healthy,
                "used_pct": round(used_pct, 1),
                "free_gb": round(free_gb, 1),
                "total_gb": round(total_gb, 1),
            }

            # Check DB file size if SQLite
            db_url = settings.DATABASE_URL
            if db_url.startswith("sqlite"):
                db_path = db_url.replace("sqlite:///", "").replace("./", "")
                if not os.path.isabs(db_path):
                    db_path = os.path.join(data_dir, db_path)
                if os.path.exists(db_path):
                    db_size_mb = os.path.getsize(db_path) / (1024 ** 2)
                    max_db_mb = getattr(settings, "DISK_SPACE_MAX_DB_SIZE_MB", 5000.0)
                    result["db_size_mb"] = round(db_size_mb, 1)
                    result["max_db_size_mb"] = max_db_mb
                    if db_size_mb > max_db_mb:
                        result["healthy"] = False
                        result["db_oversized"] = True

            if not healthy:
                logger.warning(
                    "[AGIHealth] Disk usage at %.1f%% (threshold: %.1f%%), free: %.1f GB",
                    used_pct, warn_pct, free_gb,
                )

            return result
        except Exception as e:
            return {"healthy": False, "error": str(e)}


agi_health_checker = AGIHealthChecker()
