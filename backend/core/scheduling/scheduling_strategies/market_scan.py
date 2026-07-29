"""Market scanning and trading jobs."""

import asyncio
from datetime import UTC, datetime

from loguru import logger

from backend.config import settings
from backend.core.heartbeat import update_heartbeat
from backend.models.database import Trade

from ._helpers import _get_bankroll_for_mode, _market_data_clob


async def scan_and_trade_job(mode: str):
    """Run enabled registry strategies for a mode.

    This legacy market-scan heartbeat used to run only BtcOracleStrategy and then
    optionally fall back to the general scanner. It now uses StrategyConfig plus
    STRATEGY_REGISTRY so the bot can scan every enabled strategy instead of only
    BTC 5-minute markets.
    """
    await asyncio.sleep(0)  # yield control to event loop
    from backend.core.scheduling.scheduler import log_event
    from backend.strategies.base import StrategyContext
    from backend.strategies.registry import STRATEGY_REGISTRY

    log_event("info", f"[{mode.upper()}] Running registry-driven market scan...")

    def _read_scan_config():
        import json as _json

        from backend.db.utils import get_db_session
        from backend.models.database import BotState, StrategyConfig

        with get_db_session() as db:
            state = db.query(BotState).filter_by(mode=mode).first()
            if not state:
                return {"error": "not_initialized"}
            if not state.is_running:
                return {"error": "paused"}
            configs = (
                db.query(StrategyConfig)
                .filter(StrategyConfig.enabled.is_(True))
                .filter(
                    (StrategyConfig.trading_mode == mode)
                    | (StrategyConfig.trading_mode.is_(None))
                )
                .all()
            )
            config_data = []
            for cfg in configs:
                params = {}
                if cfg.params:
                    try:
                        params = _json.loads(cfg.params)
                    except Exception:
                        logger.warning(
                            "scheduling_strategies: failed to parse strategy config params"
                        )
                config_data.append(
                    {"strategy_name": cfg.strategy_name, "params": params}
                )
            return {"configs": config_data}

    try:
        data = await asyncio.to_thread(_read_scan_config)
        if data.get("error") == "not_initialized":
            log_event("error", f"[{mode.upper()}] Bot state not initialized")
            return
        if data.get("error") == "paused":
            log_event("info", f"[{mode.upper()}] Bot is paused, skipping trades")
            return

        from backend.core.strategy_executor import execute_decisions
        from backend.markets.provider_registry import market_registry

        configs = data["configs"]
        total_decisions = 0
        total_trades = 0

        from backend.db.utils import get_db_session

        with get_db_session() as db:
            for cfg in configs:
                strategy_cls = STRATEGY_REGISTRY.get(cfg["strategy_name"])
                if strategy_cls is None:
                    continue
                from backend.models.database import BotState

                state = db.query(BotState).filter_by(mode=mode).first()
                bankroll = _get_bankroll_for_mode(state, mode) if state else 100.0
                strategy = strategy_cls()
                try:
                    async with _market_data_clob(mode) as clob:
                        strategy_ctx = StrategyContext(
                            db=db,
                            clob=clob,
                            settings=settings,
                            logger=logger,
                            params=cfg["params"],
                            mode=mode,
                            bankroll=bankroll,
                            market_registry=market_registry,
                        )
                        result = await asyncio.wait_for(
                            strategy.run(strategy_ctx), timeout=30.0
                        )
                except TimeoutError:
                    logger.error(
                        f"[{mode.upper()}] Strategy {cfg['strategy_name']} timed out after 30 seconds."
                    )
                    continue
                except Exception as e:
                    logger.error(
                        f"[{mode.upper()}] Strategy {cfg['strategy_name']} failed with error: {e}",
                        exc_info=True,
                    )
                    continue

                if not result:
                    continue
                # Record shadow trades in paper/testnet modes so AGI health check
                # can read win rate from ShadowTrade table.
                if (
                    mode in ("paper", "testnet")
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
                                    strategy_name=cfg["strategy_name"],
                                    token_id=decision["token_id"],
                                    side=decision.get("side", "BUY"),
                                    price=decision.get("price"),
                                    size_usd=decision.get("size_usd"),
                                    mode=mode,
                                )
                    except Exception as shadow_err:
                        logger.warning(
                            f"[{mode.upper()}] Shadow trade recording failed for "
                            f"{cfg['strategy_name']}: {shadow_err}"
                        )
                buy_decisions = [
                    d
                    for d in getattr(result, "decisions", [])
                    if isinstance(d, dict)
                    and d.get("decision") in ("BUY", "QUOTE")
                    and (d.get("market_ticker") or d.get("token_id"))
                ]
                total_decisions += len(buy_decisions)

                if not buy_decisions:
                    log_event(
                        "info",
                        f"[{mode.upper()}] {cfg['strategy_name']}: no actionable signals (errors={len(result.errors)})",
                    )
                    continue

                decisions_copy = []
                for decision in buy_decisions:
                    copied = dict(decision)
                    copied.setdefault("market_ticker", copied.get("token_id"))
                    copied["trading_mode"] = mode
                    decisions_copy.append(copied)
                executed = await execute_decisions(
                    decisions_copy, cfg["strategy_name"], mode=mode
                )
                total_trades += len(executed)
                log_event(
                    "success",
                    f"[{mode.upper()}] {cfg['strategy_name']}: executed {len(executed)} trade(s)",
                )

        log_event(
            "info",
            f"[{mode.upper()}] Registry market scan done: strategies={len(configs)} decisions={total_decisions} trades={total_trades}",
        )

        def _update_last_run():
            from backend.db.utils import get_db_session

            try:
                with get_db_session() as db:
                    state = db.query(BotState).filter_by(mode=mode).first()
                    if state:
                        state.last_run = datetime.now(UTC)
                        state.is_running = True
                        db.commit()
            except Exception as last_run_err:
                logger.warning(
                    f"[{mode.upper()}] Market scan completed but last_run update failed: {last_run_err}"
                )

        await asyncio.to_thread(_update_last_run)

    except Exception as e:
        log_event("error", f"[{mode.upper()}] Market scan error: {str(e)}")
        logger.exception(f"Error in scan_and_trade_job mode={mode}")


async def weather_scan_and_trade_job(mode: str):
    """Scan weather temperature markets and execute trades. Runs every 5 minutes."""
    from backend.core.scheduling.scheduler import log_event

    log_event("info", f"[{mode.upper()}] Scanning weather temperature markets...")

    try:
        from backend.core.weather_signals import scan_for_weather_signals

        signals = await scan_for_weather_signals(mode=mode)
        actionable = [s for s in signals if s.passes_threshold]

        log_event(
            "data",
            f"[{mode.upper()}] Weather: {len(signals)} signals, {len(actionable)} actionable",
            {
                "total_signals": len(signals),
                "actionable": len(actionable),
            },
        )

        if not actionable:
            log_event("info", f"[{mode.upper()}] No actionable weather signals")
            # Still update heartbeat so watchdog knows we ran
            await asyncio.to_thread(update_heartbeat, "weather_emos")
            return

        MAX_TRADES_PER_SCAN = settings.MAX_TRADES_PER_SCAN
        MIN_TRADE_SIZE = 10
        MAX_WEATHER_ALLOCATION = 500.0

        def _read_weather_state():
            from sqlalchemy import func

            from backend.db.utils import get_db_session
            from backend.models.database import BotState

            with get_db_session() as db:
                state = db.query(BotState).filter_by(mode=mode).first()
                if not state:
                    return {"error": "not_initialized"}
                if not state.is_running:
                    return {"error": "paused"}
                bankroll = _get_bankroll_for_mode(state, mode)
                weather_pending = float(
                    db.query(func.coalesce(func.sum(Trade.size), 0.0))
                    .filter(
                        Trade.settled.is_(False),
                        Trade.market_type == "weather",
                        Trade.trading_mode == mode,
                    )
                    .scalar()
                    or 0.0
                )
                existing_market_ids = {
                    row[0]
                    for row in db.query(Trade.market_ticker)
                    .filter(
                        Trade.settled.is_(False),
                        Trade.trading_mode == mode,
                    )
                    .all()
                }
                return {
                    "bankroll": bankroll,
                    "weather_pending": weather_pending,
                    "existing_market_ids": existing_market_ids,
                }

        ws = await asyncio.to_thread(_read_weather_state)
        if ws.get("error") == "not_initialized":
            log_event("error", f"[{mode.upper()}] Bot state not initialized")
            return
        if ws.get("error") == "paused":
            log_event(
                "info", f"[{mode.upper()}] Bot is paused, skipping weather trades"
            )
            return
        bankroll = ws["bankroll"]
        weather_pending = ws["weather_pending"]
        existing_market_ids = ws["existing_market_ids"]

        if weather_pending >= MAX_WEATHER_ALLOCATION:
            log_event(
                "info",
                f"[{mode.upper()}] Weather allocation limit reached: ${weather_pending:.0f}/{MAX_WEATHER_ALLOCATION:.0f}",
            )
            return

        trades_executed = 0
        for signal in actionable[:MAX_TRADES_PER_SCAN]:
            if signal.market.market_id in existing_market_ids:
                continue

            trade_size = min(signal.suggested_size, settings.WEATHER_MAX_TRADE_SIZE)
            trade_size = max(trade_size, MIN_TRADE_SIZE)

            if bankroll < MIN_TRADE_SIZE:
                log_event(
                    "warning", f"[{mode.upper()}] Bankroll too low: ${bankroll:.2f}"
                )
                break

            if trades_executed >= MAX_TRADES_PER_SCAN:
                break

            from backend.core.strategy_executor import execute_decision

            entry_price = (
                signal.market.yes_price
                if signal.direction == "yes"
                else signal.market.no_price
            )
            token_id = (
                getattr(signal.market, "token_id", None) or signal.market.market_id
            )

            decision = {
                "market_ticker": signal.market.market_id,
                "event_slug": signal.market.slug,
                "direction": signal.direction,
                "size": trade_size,
                "entry_price": entry_price,
                "edge": signal.edge,
                "confidence": signal.model_probability,
                "model_probability": signal.model_probability,
                "token_id": token_id,
                "platform": "polymarket",
                "market_type": "weather",
                "reasoning": f"weather signal: {signal.market.city_name}",
            }
            result = await execute_decision(decision, "weather_emos", mode=mode)
            if result is None:
                continue

            trades_executed += 1
            existing_market_ids.add(signal.market.market_id)
            log_event(
                "trade",
                f"[{mode.upper()}] WX {signal.market.city_name}: {signal.direction.upper()} "
                f"${trade_size:.0f} @ {entry_price:.0%}",
                {
                    "slug": signal.market.slug,
                    "direction": signal.direction,
                    "size": trade_size,
                    "edge": signal.edge,
                    "confidence": signal.model_probability,
                    "model_probability": signal.model_probability,
                    "token_id": token_id,
                    "platform": settings.DEFAULT_VENUE,
                    "market_type": "weather",
                    "reasoning": f"weather signal: {signal.market.city_name}",
                    "city": signal.market.city_name,
                },
            )

        def _update_weather_last_run():
            from backend.db.utils import get_db_session
            from backend.models.database import BotState

            try:
                with get_db_session() as db:
                    state = db.query(BotState).filter_by(mode=mode).first()
                    if state:
                        state.last_run = datetime.now(UTC)
                        state.is_running = True
                        db.commit()
            except Exception:
                logger.debug(
                    "scheduling_strategies: last_run update failed in weather scheduler"
                )

        await asyncio.to_thread(_update_weather_last_run)

        if trades_executed > 0:
            log_event(
                "success",
                f"[{mode.upper()}] Executed {trades_executed} weather trade(s)",
            )
        else:
            log_event("info", f"[{mode.upper()}] No new weather trades executed")

        await asyncio.to_thread(update_heartbeat, "weather_emos")

    except Exception as e:
        log_event("error", f"[{mode.upper()}] Weather scan error: {str(e)}")
        logger.exception(f"Error in weather_scan_and_trade_job mode={mode}")
