"""Strategy rehabilitation logic — extracted from _scheduler_core.py."""

from datetime import datetime, timezone, timedelta
from loguru import logger

from backend.config import settings
from backend.db.utils import get_db_session, utcnow
from backend.models.database import Trade, StrategyConfig


def auto_rehabilitate_strategies():
    """Lite-rehabilitate disabled strategies after a cooldown period.

    Re-enables strategies whose cooldown has elapsed if recent trades meet
    the win-rate threshold. Strategies still below threshold get their
    disable window extended. Rehabilitated strategies enter paper mode
    with a reduced allocation.
    """
    cooldown_hours = getattr(settings, "AGI_REHAB_LITE_COOLDOWN_HOURS", 1)
    re_disable_hours = getattr(settings, "AGI_REHAB_LITE_RE_DISABLE_HOURS", 4)
    wr_threshold = getattr(settings, "AGI_REHAB_LITE_WIN_RATE_THRESHOLD", 0.30)

    rehabilitated = []
    re_disabled = []
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)
        with get_db_session() as db:
            disabled_configs = (
                db.query(StrategyConfig)
                .filter(
                    StrategyConfig.enabled.is_(True),
                    StrategyConfig.disabled_at.isnot(None),
                )
                .all()
            )

            for config in disabled_configs:
                if config.strategy_name in ("agi_orchestrator",):
                    continue

                disabled_at = config.disabled_at
                if disabled_at and disabled_at.tzinfo is None:
                    disabled_at = disabled_at.replace(tzinfo=timezone.utc)

                if not disabled_at or disabled_at > cutoff:
                    continue

                since_rehab = disabled_at
                for mode in settings.active_modes_set:
                    trades = (
                        db.query(Trade)
                        .filter(
                            Trade.strategy == config.strategy_name,
                            Trade.settled,
                            Trade.timestamp >= since_rehab,
                            Trade.trading_mode == mode,
                        )
                        .all()
                    )

                    if len(trades) < 3:
                        continue

                    wins = sum(1 for t in trades if t.result == "win")
                    win_rate = wins / len(trades) if trades else 0

                    if win_rate < wr_threshold:
                        config.disabled_at = utcnow() + timedelta(
                            hours=re_disable_hours - cooldown_hours
                        )
                        re_disabled.append(
                            f"{config.strategy_name}: WR={win_rate:.0%} < {wr_threshold:.0%}, extended disable {re_disable_hours}h"
                        )
                        logger.warning(
                            f"Re-disable {config.strategy_name}: WR={win_rate:.0%} below {wr_threshold:.0%}, extended for {re_disable_hours}h"
                        )
                        break
                else:
                    config.enabled = True
                    # Only set paper mode if strategy was previously disabled/rehabbing.
                    # Active live strategies keep their existing trading_mode.
                    if config.disabled_at is not None:
                        config.trading_mode = "paper"
                    config.disabled_at = None
                    if config.rehab_allocation_pct is None:
                        config.rehab_allocation_pct = getattr(
                            settings, "AGI_REHAB_ALLOCATION_PCT", 0.25
                        )
                    rehabilitated.append(config.strategy_name)
                    logger.info(
                        f"Rehabilitated {config.strategy_name} in paper mode at {config.rehab_allocation_pct:.0%} allocation (cooldown {cooldown_hours}h elapsed)"
                    )

        if rehabilitated:
            logger.info(
                f"Lite-rehabilitated {len(rehabilitated)} strategies: {rehabilitated}"
            )
        if re_disabled:
            logger.info(
                f"Extended disable for {len(re_disabled)} strategies: {re_disabled}"
            )
    except Exception as e:
        logger.warning(f"Lite rehabilitation check failed: {e}")