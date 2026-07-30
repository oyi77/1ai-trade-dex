# performance.py — extracted from scheduler.py
"""Scheduler sub-module: performance."""

from backend.config import settings
from backend.models.database import ScheduledJob, Trade
from datetime import datetime, timedelta, timezone
from loguru import logger

from .event_log import log_event

def auto_disable_losing_strategies():
    """Audit strategy performance and disable/throttle losers. Module-level so it can be tested.

    Uses two windows:
    1. Last 24 hours (recent performance, catches fresh losing streaks)
    2. Lifetime (catches strategies that have been losing for weeks but
       happen to have no recent trades)

    A strategy is disabled if EITHER window shows it's a loser.
    """
    from backend.models.database import Trade, StrategyConfig
    from backend.config import settings
    from backend.db.utils import get_db_session
    from datetime import datetime, timezone, timedelta

    disabled = []
    min_trades = getattr(settings, "AGI_AUTO_DISABLE_MIN_TRADES", 5)
    min_trades_lifetime = getattr(settings, "AGI_AUTO_DISABLE_MIN_TRADES_LIFETIME", 50)
    try:
        now = datetime.now(timezone.utc)
        since_24h = (now - timedelta(hours=24)).replace(tzinfo=None)
        with get_db_session() as db:
            # Batch fetch enabled configs and active modes
            enabled_configs = (
                db.query(StrategyConfig).filter(StrategyConfig.enabled).all()
            )
            strategy_names = [c.strategy_name for c in enabled_configs]
            active_modes = list(settings.active_modes_set)

            all_trades = (
                db.query(Trade)
                .filter(
                    Trade.strategy.in_(strategy_names),
                    Trade.settled,
                    Trade.trading_mode.in_(active_modes),
                )
                .all()
            )

            trades_by_key: dict[tuple[str, str], list] = {}
            lifetime_trades_by_key: dict[tuple[str, str], list] = {}
            for t in all_trades:
                key = (t.strategy, t.trading_mode)
                lifetime_trades_by_key.setdefault(key, []).append(t)
                if t.timestamp and t.timestamp >= since_24h:
                    trades_by_key.setdefault(key, []).append(t)

            from backend.core.maker_taker_analytics import maker_taker_analytics

            mt_stats = maker_taker_analytics.get_stats(db)

            for config in enabled_configs:
                config_mode = getattr(config, "mode", None) or "paper"
                for mode in active_modes:
                    if config_mode != mode:
                        continue
                    trades = trades_by_key.get((config.strategy_name, mode), [])
                    lifetime_trades = lifetime_trades_by_key.get(
                        (config.strategy_name, mode), []
                    )

                    recent_disabled = _evaluate_and_disable(
                        config, mode, trades, min_trades, "24h"
                    )
                    if recent_disabled:
                        disabled.append(recent_disabled)
                        break

                    if len(lifetime_trades) >= min_trades_lifetime:
                        lifetime_disabled = _evaluate_and_disable(
                            config, mode, lifetime_trades, min_trades, "lifetime"
                        )
                        if lifetime_disabled:
                            disabled.append(lifetime_disabled)
                            break

        if disabled:
            logger.warning(
                f"auto_disable_losing_strategies: disabled {len(disabled)} strategies: {disabled}"
            )
    except Exception as exc:
        logger.exception(f"auto_disable_losing_strategies failed: {exc}")
    return disabled

def _evaluate_and_disable(
    config, mode: str, trades: list, min_trades: int, window_label: str
) -> str | None:
    """Evaluate trades and disable the strategy if it qualifies. Returns reason string or None."""

    # Skip auto-disable for strategies re-enabled after bug fixes.
    # Only check the 24h window; lifetime evaluation would kill them on
    # stale bad trades from the buggy period.
    import json as _json
    _params = {}
    try:
        if config.params:
            _params = _json.loads(config.params)
    except Exception:
        pass
    if _params.get("re_enabled_after_fix") and window_label != "24h":
        return None

    if len(trades) < min_trades:
        return None

    resolved = [t for t in trades if t.result in ("win", "loss")]
    if len(resolved) < max(3, min_trades // 2):
        return None

    wins = sum(1 for t in resolved if (t.pnl or 0) > 0)
    win_rate = wins / len(resolved)
    pnl = sum(t.pnl for t in trades if t.pnl)

    recent_losses = sorted(
        [t for t in trades if t.result == "loss"],
        key=lambda t: t.settlement_time or t.timestamp,
        reverse=True,
    )
    consecutive_losses = 0
    for t in recent_losses:
        consecutive_losses += 1
        if consecutive_losses >= 20:
            break
    if win_rate < 0.30 or pnl < -200.0 or consecutive_losses >= 20:
        from backend.core.strategy_health import disable_for_rehab

        reason_parts = []
        if win_rate < 0.30:
            reason_parts.append(f"win_rate={win_rate:.0%}")
        if pnl < -50.0:
            reason_parts.append(f"pnl=${pnl:.0f}")
        if consecutive_losses >= 10:
            reason_parts.append(f"{consecutive_losses}+ consecutive losses")
        reason_str = ", ".join(reason_parts)
        disable_for_rehab(config)
        logger.warning(
            f"Auto-disabled {config.strategy_name} ({mode}) [{window_label}]: {reason_str}"
        )
        return f"{config.strategy_name} ({mode}) [{window_label}]: {reason_str}"
    return None

def _throttle_maker_preference(
    config, mode: str, trades: list, mt_stats: dict
) -> str | None:
    """Throttle strategies where taker execution is losing money.

    Switches the strategy to maker-only mode (via params) to capture
    rebates and avoid taker fees on a strategy that's net negative ROI.
    """
    if not mt_stats:
        return None
    recommendation = mt_stats.get("recommendation", "insufficient_data")
    if recommendation not in ("reduce_taker", "prefer_maker"):
        return None
    maker_info = mt_stats.get("maker", {})
    taker_info = mt_stats.get("taker", {})
    taker_roi = taker_info.get("roi", 0)
    taker_count = taker_info.get("count", 0)
    if taker_count < 10:
        return None
    import json as _json

    if recommendation == "reduce_taker":
        reason = (
            f"Taker ROI ({taker_roi:.2%}) is negative "
            f"(n={taker_count} settled trades)"
        )
    else:
        maker_roi = maker_info.get("roi", 0)
        reason = (
            f"Maker ROI ({maker_roi:.2%}) significantly exceeds Taker ROI "
            f"({taker_roi:.2%}) over full trade history"
        )
    config.rehab_allocation_pct = 0.50
    try:
        params = _json.loads(config.params) if config.params else {}
    except Exception:
        params = {}
    params["force_maker_only"] = True
    config.params = _json.dumps(params)
    logger.warning(
        f"Throttled {config.strategy_name} ({mode}) due to Taker "
        f"underperformance: {reason}. Enforced maker-only execution."
    )
    return f"{config.strategy_name} ({mode}): {reason}"

def _cumulative_loss_disable(
    db, enabled_configs: list, active_modes: list
) -> list[str]:
    """Disable strategies with >$100 cumulative loss over the last 7 days."""
    from sqlalchemy import func as _func
    from backend.models.database import Trade
    from backend.core.strategy_health import disable_for_rehab

    disabled = []
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    for config in enabled_configs:
        if not config.enabled:
            continue
        for mode in active_modes:
            cum_pnl = (
                db.query(_func.coalesce(_func.sum(Trade.pnl), 0.0))
                .filter(
                    Trade.strategy == config.strategy_name,
                    Trade.trading_mode == mode,
                    Trade.settled,
                    Trade.timestamp >= week_ago,
                )
                .scalar()
                or 0.0
            )
            if cum_pnl < -100.0:
                disable_for_rehab(config)
                disabled.append(
                    f"{config.strategy_name} ({mode}): 7d cumulative loss ${abs(cum_pnl):.0f}"
                )
                logger.warning(
                    f"Auto-disabled {config.strategy_name} ({mode}): 7d cumulative loss ${abs(cum_pnl):.0f}"
                )
                break
    return disabled

def performance_decay_check_job():
    """G-09: Detect strategy performance decay by comparing 24h vs 7d win rates.

    Runs every PERFORMANCE_DECAY_CHECK_INTERVAL_HOURS (default 6h).
    If a strategy's 24h win rate drops by more than PERFORMANCE_DECAY_THRESHOLD
    (default 20%) compared to its 7d win rate, logs a warning.
    """
    from backend.models.database import Trade, StrategyConfig
    from backend.db.utils import get_db_session
    from datetime import datetime, timezone, timedelta

    threshold = getattr(settings, "PERFORMANCE_DECAY_THRESHOLD", 0.20)
    now = datetime.now(timezone.utc)
    day_start = now - timedelta(hours=24)
    week_start = now - timedelta(days=7)

    try:
        with get_db_session() as db:
            configs = (
                db.query(StrategyConfig).filter(StrategyConfig.enabled.is_(True)).all()
            )
            for config in configs:
                strategy_name = config.strategy_name

                # 7-day win rate
                week_trades = (
                    db.query(Trade)
                    .filter(
                        Trade.strategy == strategy_name,
                        Trade.settled.is_(True),
                        Trade.settlement_time >= week_start,
                        Trade.result.in_(["win", "loss"]),
                    )
                    .all()
                )

                if len(week_trades) < 5:
                    continue

                week_wins = sum(1 for t in week_trades if t.result == "win")
                week_wr = week_wins / len(week_trades)

                # 24-hour win rate
                day_trades = [t for t in week_trades if t.settlement_time >= day_start]
                if len(day_trades) < 3:
                    continue

                day_wins = sum(1 for t in day_trades if t.result == "win")
                day_wr = day_wins / len(day_trades)

                # Check for decay
                decay = week_wr - day_wr
                if decay > threshold:
                    logger.warning(
                        "[perf_decay] Strategy {} decay detected: "
                        "24h WR={:.1%} vs 7d WR={:.1%} (decay={:.1%} > threshold={:.1%})",
                        strategy_name,
                        day_wr,
                        week_wr,
                        decay,
                        threshold,
                    )
                    log_event(
                        "warning",
                        f"Performance decay: {strategy_name} "
                        f"24h WR={day_wr:.0%} vs 7d WR={week_wr:.0%}",
                    )
                else:
                    logger.debug(
                        "[perf_decay] Strategy {} healthy: 24h WR={:.1%}, 7d WR={:.1%}, decay={:.1%}",
                        strategy_name,
                        day_wr,
                        week_wr,
                        decay,
                    )

    except Exception as e:
        logger.warning("[perf_decay] Performance decay check failed: {}", e)