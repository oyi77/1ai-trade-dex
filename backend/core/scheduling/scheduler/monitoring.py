# monitoring.py — extracted from scheduler.py
"""Scheduler sub-module: monitoring."""

from backend.core.scheduling.scheduling_strategies import (
    scan_and_trade_job,
    weather_scan_and_trade_job,
    settlement_job,
    news_feed_scan_job,
    arbitrage_scan_job,
    auto_trader_job,
    auto_redeem_job,
    heartbeat_job,
    strategy_cycle_job,
    sync_testnet_wallet,
    sync_live_wallet,
    verify_settlement_blockchain,
    market_universe_scan_job,
    position_monitor_job,
)
from loguru import logger

from .event_log import log_event

async def run_manual_scan(mode: str = "paper"):
    """Trigger a manual market scan."""
    log_event("info", f"Manual scan triggered for mode: {mode}")
    await scan_and_trade_job(mode)

async def run_manual_settlement():
    """Trigger a manual settlement check."""
    log_event("info", "Manual settlement triggered")
    await settlement_job()

async def monitoring_job():
    """Run production monitoring checks"""
    from backend.core.monitoring import run_monitoring_check
    from backend.models.database import get_db

    db = next(get_db())
    try:
        health = await run_monitoring_check(db)
        logger.info(f"✅ Monitoring check: {health['database']['healthy']}")
        return health
    except Exception as e:
        logger.error(f"❌ Monitoring check failed: {e}")
    finally:
        db.close()