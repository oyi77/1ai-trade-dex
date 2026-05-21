"""Win-rate monitor for live trading strategies.

Checks rolling win rate over LOOKBACK_DAYS.  Auto-disables strategies that
fall below WR_THRESHOLD while losing money; warns on strategies below
threshold but still profitable.
"""

from datetime import datetime, timedelta, timezone

from loguru import logger

from backend.db.utils import get_db_session
from backend.models.database import StrategyConfig, Trade

MIN_TRADES = 10
WR_THRESHOLD = 0.50
CHECK_INTERVAL_HOURS = 6
LOOKBACK_DAYS = 3


def wr_monitor_job() -> None:
    """Evaluate rolling WR for every live strategy and disable losers."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=LOOKBACK_DAYS)

    disabled: list[str] = []
    try:
        with get_db_session() as db:
            configs = (
                db.query(StrategyConfig)
                .filter(StrategyConfig.enabled.is_(True))  # noqa: E712
                .all()
            )

            for cfg in configs:
                trades = (
                    db.query(Trade)
                    .filter(
                        Trade.strategy == cfg.strategy_name,
                        Trade.trading_mode == "live",
                        Trade.settled.is_(True),  # noqa: E712
                        Trade.settlement_time >= since,
                    )
                    .all()
                )

                if len(trades) < MIN_TRADES:
                    continue

                resolved = [t for t in trades if t.result in ("win", "loss")]
                if len(resolved) < MIN_TRADES:
                    continue

                wins = sum(1 for t in resolved if t.result == "win")
                wr = wins / len(resolved)
                pnl = sum(t.pnl for t in trades if t.pnl is not None)

                if wr < WR_THRESHOLD:
                    if pnl < 0:
                        # Losing money + low WR -> disable for rehab
                        from backend.core.strategy_health import disable_for_rehab
                        disable_for_rehab(cfg)
                        label = f"{cfg.strategy_name}: WR={wr:.0%}, pnl=${pnl:.2f}"
                        disabled.append(label)
                        logger.warning(
                            "[wr_monitor] Auto-disabled %s (WR=%.0f%% < %.0f%%, pnl=$%.2f)",
                            cfg.strategy_name,
                            wr * 100,
                            WR_THRESHOLD * 100,
                            pnl,
                        )
                    else:
                        # Profitable but WR below threshold -> warning only
                        logger.warning(
                            "[wr_monitor] Low WR warning %s: WR=%.0f%% < %.0f%% but pnl=$%.2f (profitable)",
                            cfg.strategy_name,
                            wr * 100,
                            WR_THRESHOLD * 100,
                            pnl,
                        )

        # Publish disable events after session closes
        if disabled:
            from backend.core.event_bus import event_bus

            for label in disabled:
                event_bus.publish(
                    "strategy_wr_disabled",
                    {"detail": label, "timestamp": now.isoformat()},
                )
            logger.info(
                "[wr_monitor] Disabled %d strategies: %s", len(disabled), disabled
            )

    except Exception as exc:
        logger.exception("[wr_monitor] WR monitor check failed: %s", exc)
