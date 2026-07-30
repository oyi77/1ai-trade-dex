"""Heartbeat and strategy cycle dispatch jobs."""

import asyncio
from datetime import UTC, datetime

from loguru import logger

from backend.config import settings
from backend.models.database import BotState, StrategyConfig, Trade

from ._helpers import _get_bankroll_for_mode, _market_data_clob


async def heartbeat_job():
    """Periodic heartbeat. Runs every minute."""
    await asyncio.sleep(0)  # yield control to event loop
    from backend.core.scheduling.scheduler import log_event

    def _read_heartbeat_state():
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            state = db.query(BotState).first()
            pending = db.query(Trade).filter(Trade.settled.is_(False)).count()
            if state is None:
                return None
            return {
                "pending_trades": pending,
                "bankroll": state.bankroll,
                "is_running": state.is_running,
            }

    try:
        hb = await asyncio.to_thread(_read_heartbeat_state)
        if hb is None:
            log_event("warning", "Heartbeat: Bot state not initialized")
            return
        log_event(
            "data",
            f"Heartbeat: {hb['pending_trades']} pending trades, bankroll: ${hb['bankroll']:.2f}",
            hb,
        )
    except Exception as e:
        log_event("warning", f"Heartbeat failed: {str(e)}")


async def strategy_cycle_job(strategy_name: str, mode: str = "paper") -> None:
    """Generic strategy dispatcher — called by APScheduler for each enabled strategy.

    Args:
        strategy_name: Name of the strategy to run.
        mode: Trading mode (paper, testnet, live).
    """
    await asyncio.sleep(0)  # yield control to event loop
    import json

    from backend.core.heartbeat import update_heartbeat as _update_heartbeat
    from backend.core.scheduling.scheduler import log_event
    from backend.db.utils import get_db_session
    from backend.models.database import BotState
    from backend.strategies.registry import STRATEGY_REGISTRY

    def _update_botstate_last_run():
        with get_db_session() as db:
            state = db.query(BotState).filter_by(mode=mode).first()
            if state:
                state.last_run = datetime.now(UTC)
                state.is_running = True
                db.commit()

    try:
        await asyncio.to_thread(_update_botstate_last_run)
    except BaseException:
        pass

    # Phase 1: Read config in a thread to avoid blocking the event loop
    def _read_config():
        with get_db_session() as db:
            config = (
                db.query(StrategyConfig)
                .filter(
                    StrategyConfig.strategy_name == strategy_name,
                    StrategyConfig.enabled.is_(True),
                )
                .first()
            )
            if not config:
                return None
            params = {}
            if config.params:
                try:
                    params = json.loads(config.params)
                except Exception:
                    logger.exception(
                        f"[scheduling_strategies] Failed to parse StrategyConfig params JSON for {strategy_name}"
                    )
                    return None
            effective_mode = mode or config.trading_mode or settings.TRADING_MODE
            return {"params": params, "effective_mode": effective_mode}

    try:
        config_data = await asyncio.to_thread(_read_config)

        if config_data is None:
            log_event(
                "info", f"Strategy {strategy_name} disabled or not configured, skipping"
            )
            return

        strategy_cls = STRATEGY_REGISTRY.get(strategy_name)
        if not strategy_cls:
            log_event(
                "debug",
                f"Strategy {strategy_name} not in registry — updating heartbeat anyway",
            )

            _update_heartbeat(strategy_name)
            return

        params = config_data["params"]
        effective_mode = config_data["effective_mode"]

        from backend.config import settings as _settings
        from backend.markets.provider_registry import market_registry
        from backend.strategies.base import StrategyContext

        # Phase 2: Run strategy — sync DB reads happen inside strategy.run(),
        # so open the session in a thread to avoid blocking the event loop.
        def _open_db_session():
            from backend.db.utils import get_db_session

            ctx = get_db_session()
            return ctx, ctx.__enter__()

        _db_ctx, db = await asyncio.to_thread(_open_db_session)
        try:
            # Read bankroll for dynamic position sizing
            from backend.models.database import BotState

            state = db.query(BotState).first()
            bankroll = _get_bankroll_for_mode(state, effective_mode) if state else 100.0
            # For live mode, cap bankroll to available CLOB cash (not position value)
            if effective_mode == "live":
                try:
                    from backend.core.wallet.bankroll_reconciliation import (
                        fetch_pm_total_equity,
                    )

                    actual_equity = await fetch_pm_total_equity()
                    if actual_equity and actual_equity > 0:
                        bankroll = min(
                            bankroll, actual_equity * 0.75
                        )  # Use 75% of equity for live trading
                except Exception:
                    logger.warning("scheduling_strategies: failed to fetch PM equity for arb sizing")
            strategy = strategy_cls()
            async with _market_data_clob(effective_mode) as clob:
                ctx = StrategyContext(
                    db=db,
                    clob=clob,
                    settings=_settings,
                    logger=logger,
                    params=params,
                    mode=effective_mode,
                    bankroll=bankroll,
                    market_registry=market_registry,
                )
                result = await asyncio.wait_for(strategy.run(ctx), timeout=120)

            # Record shadow trades in paper/testnet modes so AGI health check
            # can read win rate from ShadowTrade table.
            if (
                effective_mode in ("paper", "testnet")
                and hasattr(result, "decisions")
                and result.decisions
            ):
                try:
                    from backend.application.strategy.shadow_runner import (
                        DBSessionShadowRunner,
                    )

                    shadow_runner = DBSessionShadowRunner(db)
                    for decision in result.decisions:
                        if isinstance(decision, dict) and decision.get("token_id"):
                            shadow_runner.record_signal(
                                strategy_name=strategy_name,
                                token_id=decision["token_id"],
                                side=decision.get("side", "BUY"),
                                price=decision.get("price"),
                                size_usd=decision.get("size_usd"),
                                mode=effective_mode,
                            )
                except Exception as shadow_err:
                    logger.warning(
                        f"[{effective_mode.upper()}] Shadow trade recording failed for "
                        f"{strategy_name}: {shadow_err}"
                    )

            from backend.core.strategy_executor import (
                execute_decisions as _exec_decisions,
            )

            buy_decisions = [
                d
                for d in getattr(result, "decisions", [])
                if isinstance(d, dict)
                and d.get("decision") in ("BUY", "QUOTE")
                and (d.get("market_ticker") or d.get("token_id"))
            ]

            execution_modes = []
            if effective_mode == "live":
                execution_modes = [
                    "live",
                    "paper",
                ]  # live first so duplicate guard doesn't block real trades
                logger.info(
                    f"[{strategy_name}] effective_mode=live, will execute in BOTH live+paper modes"
                )
            elif effective_mode in ("paper", "testnet"):
                execution_modes = [effective_mode]
                logger.info(
                    f"[{strategy_name}] effective_mode={effective_mode}, will execute in {effective_mode} mode only"
                )
            else:
                execution_modes = sorted(_settings.active_modes_set)
                logger.info(
                    f"[{strategy_name}] No specific mode, will execute in all active modes: {execution_modes}"
                )

            for mode in execution_modes:
                logger.info(
                    f"[{strategy_name}] Preparing to execute {len(buy_decisions)} decisions in {mode} mode"
                )
                trade_results = []
                if buy_decisions:
                    decisions_copy = [d.copy() for d in buy_decisions]
                    for d in decisions_copy:
                        d["trading_mode"] = mode
                    logger.info(
                        f"[{strategy_name}] Calling _exec_decisions with {len(decisions_copy)} decisions, mode={mode}"
                    )
                    # Each execute_decision opens its own DB session — don't pass
                    # the caller's session to avoid holding it open during trade execution
                    trade_results = await _exec_decisions(
                        decisions_copy, strategy_name, mode
                    )
                    result.trades_placed += len(trade_results)
                    logger.info(
                        f"[{strategy_name}] PARALLEL: executed {len(trade_results)} trades in {mode} mode (input decisions: {len(decisions_copy)})"
                    )
                else:
                    logger.info(f"[{strategy_name}] No buy_decisions to execute")

                # Compute scan stats for this mode
                markets_scanned = getattr(result, "markets_scanned", 0)
                signals_had_edge = len(buy_decisions)
                trades_executed = len(trade_results)
                signals_rejected = signals_had_edge - trades_executed

                # Log structured scan outcome
                logger.info(
                    f"scanned {markets_scanned} markets, {signals_had_edge} had edge, "
                    f"{signals_rejected} rejected by edge filter, {trades_executed} executed"
                )

                # Update in-memory scan stats
                from backend.core.heartbeat import update_scan_stats

                try:
                    update_scan_stats(
                        strategy_name=strategy_name,
                        mode=mode,
                        markets_scanned=markets_scanned,
                        signals_had_edge=signals_had_edge,
                        signals_rejected=signals_rejected,
                        trades_executed=trades_executed,
                    )
                except Exception as stats_err:
                    logger.warning(
                        f"Failed to update scan stats for {strategy_name} ({mode}): {stats_err}"
                    )

            _update_heartbeat(strategy_name)

            log_event(
                "info",
                f"Strategy {strategy_name} cycle done: decisions={result.decisions_recorded} trades={result.trades_placed} errors={len(result.errors)}",
            )
        finally:
            _db_ctx.__exit__(None, None, None)

    except TimeoutError:
        log_event("error", f"Strategy {strategy_name} cycle timed out (60s limit)")
        logger.error(f"strategy_cycle_job({strategy_name}) timed out after 60s")
    except asyncio.CancelledError:
        logger.info(f"strategy_cycle_job({strategy_name}) cancelled during shutdown")
        return
    except Exception as e:
        log_event("error", f"Strategy cycle job failed for {strategy_name}: {e}")
        logger.exception(f"strategy_cycle_job({strategy_name})")

    try:
        _update_heartbeat(strategy_name)
    except Exception:
        logger.exception(
            f"[scheduling_strategies] Heartbeat update failed for {strategy_name} after cycle"
        )
