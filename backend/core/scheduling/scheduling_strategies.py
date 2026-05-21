"""DEPRECATED: Use backend.core.scheduling_strategies instead.

Background job functions scheduled by APScheduler.

This module will be removed in a future release.
"""



import asyncio
import gc
from datetime import datetime, timezone
from sqlalchemy import func

from backend.config import settings
from backend.models.database import (
    Trade,
    BotState,
    Signal,
    PendingApproval,
    StrategyConfig,
)
from backend.core.signals import scan_universe_markets
from backend.core.heartbeat import update_heartbeat
from backend.core.decisions import record_decision
from backend.core.event_bus import _broadcast_event

from backend.core.position_monitor import position_monitor_job

__all__ = ["position_monitor_job"]

from loguru import logger


def _get_bankroll_for_mode(state, mode: str) -> float:
    """Read the correct bankroll field based on trading mode."""
    if mode == "paper":
        return (
            state.paper_bankroll
            if state.paper_bankroll is not None
            else settings.INITIAL_BANKROLL
        )
    elif mode == "testnet":
        return (
            state.testnet_bankroll
            if state.testnet_bankroll is not None
            else settings.INITIAL_BANKROLL
        )
    else:
        return (
            state.bankroll if state.bankroll is not None else settings.INITIAL_BANKROLL
        )


async def _process_signal_with_approval(
    signal,
    state,
    db,
    trades_executed: int,
    max_trades: int,
    effective_mode: str = None,
) -> int:
    from backend.core.scheduling.scheduler import log_event

    mode = effective_mode or settings.TRADING_MODE

    existing_trade = (
        db.query(Trade)
        .filter(
            Trade.event_slug == signal.market.slug,
            Trade.settled.is_(False),
            Trade.trading_mode == mode,
        )
        .first()
    )
    if existing_trade:
        logger.debug(f"Skipping {signal.market.slug}: already has open trade")
        return trades_executed

    if trades_executed >= max_trades:
        return trades_executed

    approval_mode = settings.SIGNAL_APPROVAL_MODE

    existing_pending = (
        db.query(PendingApproval)
        .filter(
            PendingApproval.market_id == signal.market.market_id,
            PendingApproval.status == "pending",
        )
        .first()
    )

    if existing_pending:
        if approval_mode == "manual":
            logger.debug(f"Skipping {signal.market.slug}: already has pending approval")
            return trades_executed
        else:
            existing_pending.status = "expired"
            db.flush()
            logger.debug(
                f"Auto-expired stale pending approval for {signal.market.slug} (mode={approval_mode})"
            )
    min_confidence = settings.AUTO_APPROVE_MIN_CONFIDENCE

    MAX_TRADE_FRACTION = settings.KELLY_FRACTION
    MIN_TRADE_SIZE = 5.0
    bankroll = _get_bankroll_for_mode(state, mode)
    trade_size = min(signal.suggested_size, bankroll * MAX_TRADE_FRACTION)
    trade_size = max(trade_size, MIN_TRADE_SIZE)

    if bankroll < MIN_TRADE_SIZE:
        log_event("warning", f"Bankroll too low: ${bankroll:.2f}")
        return trades_executed

    approval_signal = {
        "market_id": signal.market.market_id,
        "market_title": f"BTC {signal.market.window_start.strftime('%H:%M')} - {signal.market.window_end.strftime('%H:%M')} UTC",
        "side": signal.direction.upper(),
        "price": (
            signal.market.up_price
            if signal.direction == "up"
            else signal.market.down_price
        ),
        "size": trade_size,
        "confidence": signal.confidence,
        "model_probability": signal.model_probability,
        "market_probability": signal.market_probability,
        "edge": signal.edge,
        "direction": signal.direction,
        "slug": signal.market.slug,
        "up_token_id": signal.market.up_token_id,
        "down_token_id": signal.market.down_token_id,
    }

    if approval_mode == "auto_deny":
        record_decision(
            db,
            "btc_oracle",
            signal.market.market_id,
            "SKIP",
            confidence=signal.confidence,
            signal_data={
                "direction": signal.direction,
                "model_probability": signal.model_probability,
                "market_probability": signal.market_probability,
                "edge": signal.edge,
                "btc_price": getattr(signal, "btc_price", None),
                "sources": ["btc_oracle_scanner", "market_maker", "whale_tracker"],
            },
            reason="auto-deny mode: signal rejected",
        )
        log_event("info", f"Auto-denied signal for {signal.market.slug}")
        return trades_executed

    elif approval_mode == "auto_approve":
        if signal.confidence >= min_confidence:
            return await _execute_trade(
                signal, state, db, trade_size, trades_executed, mode=mode
            )
        else:
            log_event(
                "info",
                f"Auto-approve: skipping low-confidence signal ({signal.confidence:.2f} < {min_confidence}) for {signal.market.slug}",
            )
            record_decision(
                db,
                "btc_oracle",
                signal.market.market_id,
                "SKIP",
                confidence=signal.confidence,
                signal_data={
                    "direction": signal.direction,
                    "model_probability": signal.model_probability,
                    "market_probability": signal.market_probability,
                    "edge": signal.edge,
                    "btc_price": getattr(signal, "btc_price", None),
                    "sources": ["btc_oracle_scanner", "market_maker", "whale_tracker"],
                },
                reason=f"auto-approve: confidence {signal.confidence:.2f} below threshold {min_confidence}",
            )
            return trades_executed

    return await _queue_for_approval(
        signal, state, db, trade_size, approval_signal, trades_executed
    )


async def _execute_trade(
    signal, state, db, trade_size, trades_executed: int, mode: str = None
) -> int:
    """Execute a BTC trade by delegating to strategy_executor.execute_decision()."""
    from backend.core.scheduling.scheduler import log_event
    from backend.core.strategy_executor import execute_decision

    entry_price = (
        signal.market.up_price if signal.direction == "up" else signal.market.down_price
    )
    token_id = (
        signal.market.up_token_id
        if signal.direction == "up"
        else signal.market.down_token_id
    )

    decision = {
        "market_ticker": signal.market.market_id,
        "slug": signal.market.slug,
        "event_slug": signal.market.slug,
        "direction": signal.direction,
        "size": trade_size,
        "entry_price": entry_price,
        "edge": signal.edge,
        "confidence": signal.confidence,
        "model_probability": signal.model_probability,
        "token_id": token_id,
        "platform": settings.DEFAULT_VENUE,
        "reasoning": f"edge {signal.edge:.3f} >= threshold, {signal.direction} @ {entry_price:.0%}",
    }

    result = await execute_decision(decision, "btc_oracle", mode=mode)
    if result is None:
        return trades_executed

    trades_executed += 1

    try:
        from backend.bot.notifier import notify_btc_signal

        notify_btc_signal(signal, None)
    except Exception:
        logger.exception(
            f"[scheduling_strategies] BTC signal notification failed for {getattr(signal, 'market', None)}"
        )

    mode_label = f"[{mode.upper()}] " if mode != "paper" else ""
    log_event(
        "trade",
        f"{mode_label}BTC {signal.direction.upper()} ${trade_size:.0f} @ {entry_price:.0%} | {signal.market.slug}",
        {
            "slug": signal.market.slug,
            "direction": signal.direction,
            "size": trade_size,
            "edge": signal.edge,
            "entry_price": entry_price,
            "btc_price": getattr(signal, "btc_price", None),
        },
    )

    return trades_executed


async def _queue_for_approval(
    signal, state, db, trade_size, approval_signal, trades_executed: int
) -> int:
    """Queue a signal for manual approval."""
    from backend.core.scheduling.scheduler import log_event

    pending = PendingApproval(
        market_id=signal.market.market_id,
        direction=signal.direction.upper(),
        size=trade_size,
        confidence=signal.confidence,
        signal_data=approval_signal,
        status="pending",
    )
    db.add(pending)
    db.flush()

    try:
        record_decision(
            db,
            "btc_oracle",
            signal.market.market_id,
            "PENDING",
            confidence=signal.confidence,
            signal_data={
                "direction": signal.direction,
                "model_probability": signal.model_probability,
                "market_probability": signal.market_probability,
                "edge": signal.edge,
                "btc_price": getattr(signal, "btc_price", None),
                "pending_id": pending.id,
                "trade_size": trade_size,
                "sources": ["btc_oracle_scanner", "market_maker", "whale_tracker"],
            },
            reason=f"queued for manual approval (conf {signal.confidence:.2f})",
        )
    except Exception as _de:
        logger.warning(f"Decision logging (PENDING) failed: {_de}")

    try:
        _broadcast_event(
            "signal_found",
            {
                "market_ticker": signal.market.market_id,
                "market_title": f"BTC {signal.market.window_start.strftime('%H:%M')} - {signal.market.window_end.strftime('%H:%M')} UTC",
                "direction": signal.direction,
                "model_probability": signal.model_probability,
                "market_probability": signal.market_probability,
                "edge": signal.edge,
                "confidence": signal.confidence,
                "suggested_size": trade_size,
                "reasoning": "Signal queued for approval",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "category": "trading",
                "btc_price": getattr(signal, "btc_price", None),
                "window_end": (
                    signal.market.window_end.isoformat()
                    if signal.market.window_end
                    else None
                ),
                "actionable": True,
                "event_slug": signal.market.slug,
            },
        )
    except Exception:
        logger.exception(
            f"[scheduling_strategies] Event broadcast 'signal_found' failed for {getattr(signal, 'market', None)}"
        )

    log_event(
        "info",
        f"Queued signal for approval: {signal.market.slug} (conf {signal.confidence:.2f})",
    )

    return trades_executed


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
                        pass
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
                strategy_ctx = StrategyContext(
                    db=db,
                    clob=None,
                    settings=settings,
                    logger=logger,
                    params=cfg["params"],
                    mode=mode,
                    market_registry=market_registry,
                )
                strategy = strategy_cls()
                result = await strategy.run(strategy_ctx)
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
                        state.last_run = datetime.now(timezone.utc)
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
            from backend.db.utils import get_db_session

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
                f"[{mode.upper()}] Weather allocation limit reached: ${weather_pending:.0f}/${MAX_WEATHER_ALLOCATION:.0f}",
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

            try:
                with get_db_session() as db:
                    state = db.query(BotState).filter_by(mode=mode).first()
                    if state:
                        state.last_run = datetime.now(timezone.utc)
                        db.commit()
            except Exception:
                pass

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


async def settlement_job():
    """Check and settle pending trades. Runs every 2 minutes."""
    await asyncio.sleep(0)  # yield control to event loop
    from backend.core.scheduling.scheduler import log_event

    log_event("info", "Checking BTC trade settlements...")

    def _read_pending_count():
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            return db.query(Trade).filter(Trade.settled.is_(False)).count()

    try:
        from backend.core.settlement import (
            settle_pending_trades,
            update_bot_state_with_settlements,
            reconcile_bot_state,
        )

        pending_count = await asyncio.to_thread(_read_pending_count)

        if pending_count == 0:
            log_event("data", "No pending trades to settle")
            return

        log_event("data", f"Processing {pending_count} pending trades")

        from backend.db.utils import get_db_session

        with get_db_session() as db:
            settled = await settle_pending_trades(db)

            if settled:
                await update_bot_state_with_settlements(db, settled)

                wins = sum(1 for t in settled if t.result == "win")
                losses = sum(1 for t in settled if t.result == "loss")
                total_pnl = sum(t.pnl for t in settled if t.pnl is not None)

                log_event(
                    "success",
                    f"Settled {len(settled)} trades: {wins}W/{losses}L, P&L: ${total_pnl:.2f}",
                    {
                        "settled_count": len(settled),
                        "wins": wins,
                        "losses": losses,
                        "pnl": total_pnl,
                    },
                )

                from backend.bot.notifier import notify_trade_settled

                for trade in settled:
                    result_prefix = "+" if trade.pnl and trade.pnl > 0 else ""
                    log_event(
                        "data",
                        f"  {trade.event_slug}: {trade.result.upper()} {result_prefix}${trade.pnl:.2f}",
                    )
                    notify_trade_settled(trade)
            else:
                log_event("info", "No trades ready for settlement")

            await reconcile_bot_state(db)

    except Exception as e:
        log_event("error", f"Settlement error: {str(e)}")
        logger.exception("Error in settlement_job")


async def news_feed_scan_job():
    """Periodically pull news feeds when NEWS_FEED_ENABLED."""
    from backend.core.scheduling.scheduler import log_event

    if not settings.NEWS_FEED_ENABLED:
        return
    try:
        from backend.data.feed_aggregator import FeedAggregator

        agg = FeedAggregator()
        items = await agg.fetch_all()
        log_event("data", f"News feed: {len(items)} items")
    except Exception as e:
        log_event("error", f"news_feed_scan error: {e}")


async def arbitrage_scan_job():
    """Periodically scan for arbitrage opportunities when ARBITRAGE_DETECTOR_ENABLED."""
    from backend.core.scheduling.scheduler import log_event

    if not settings.ARBITRAGE_DETECTOR_ENABLED:
        return
    try:
        from backend.core.arbitrage_detector import ArbitrageDetector
        from backend.core.market_scanner import fetch_all_active_markets

        markets = await fetch_all_active_markets(limit=300)
        det = ArbitrageDetector()
        market_dicts = [
            {
                "market_id": m.ticker or m.slug,
                "yes_price": m.yes_price,
                "no_price": m.no_price,
                "question": m.question,
            }
            for m in markets
        ]
        ops = det.scan_all(market_dicts)
        log_event(
            "data",
            f"Arbitrage scan: {len(ops)} opportunities from {len(market_dicts)} markets",
        )
    except Exception as e:
        log_event("error", f"arbitrage_scan error: {e}")


async def auto_trader_job(mode: str):
    """Run AutoTrader against unexecuted signals when AUTO_TRADER_ENABLED."""
    await asyncio.sleep(0)  # yield control to event loop
    from backend.core.scheduling.scheduler import log_event
    from loguru import logger

    if not settings.AUTO_TRADER_ENABLED:
        return

    def _read_auto_trader_signals():
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            state = db.query(BotState).filter_by(mode=mode).first()
            if not state or not state.is_running:
                return None
            bankroll = _get_bankroll_for_mode(state, mode)
            signals = (
                db.query(Signal)
                .filter(
                    Signal.executed.is_(False),
                    Signal.execution_mode == mode,
                )
                .order_by(Signal.timestamp.desc())
                .limit(settings.AUTO_TRADER_BATCH_SIZE)
                .all()
            )
            if not signals:
                return {
                    "bankroll": bankroll,
                    "signal_rows": [],
                    "current_exposure": 0.0,
                }
            current_exposure = float(
                db.query(func.coalesce(func.sum(Trade.size), 0.0))
                .filter(
                    Trade.settled.is_(False),
                    Trade.trading_mode == mode,
                )
                .scalar()
                or 0.0
            )
            signal_rows = [
                {
                    "id": sig.id,
                    "market_ticker": sig.market_ticker,
                    "direction": sig.direction,
                    "confidence": sig.confidence,
                    "edge": sig.edge,
                    "model_probability": sig.model_probability,
                    "token_id": sig.token_id,
                    "track_name": sig.track_name,
                }
                for sig in signals
            ]
            return {
                "bankroll": bankroll,
                "signal_rows": signal_rows,
                "current_exposure": current_exposure,
            }

    try:
        from backend.core.auto_trader import AutoTrader
        from backend.core.risk_manager import RiskManager
        from backend.data.polymarket_clob import clob_from_settings

        from backend.core.wallet.registry import get_wallet_router

        trader = AutoTrader(
            RiskManager(), clob_factory=clob_from_settings, wallet_router=get_wallet_router()
        )
        data = await asyncio.to_thread(_read_auto_trader_signals)
        if data is None:
            return
        bankroll = data["bankroll"]
        signal_rows = data["signal_rows"]
        current_exposure = data["current_exposure"]
        signal_ids = [sig["id"] for sig in signal_rows]
        if not signal_rows:
            log_event("info", f"[{mode.upper()}] AutoTrader cycle: no pending signals")
            return

        executed = 0
        queued = 0
        skipped = 0
        processed_signal_ids = []
        for sig in signal_rows:
            token_id = sig["token_id"]
            market_ticker = sig["market_ticker"]
            if (
                mode in ("testnet", "live")
                and not token_id
                and not market_ticker.startswith("KX")
            ):
                processed_signal_ids.append(sig["id"])
                skipped += 1
                continue

            signal_dict = {
                "market_id": market_ticker,
                "market_ticker": market_ticker,
                "side": "BUY" if (sig["direction"] or "yes") == "yes" else "SELL",
                "confidence": sig["confidence"] or 0.0,
                "size": min(
                    settings.MAX_TRADE_SIZE, bankroll * settings.KELLY_FRACTION
                ),
                "price": sig["model_probability"] or 0.5,
                "token_id": token_id,
                "strategy": sig["track_name"] or "unknown",
            }
            result = await trader.execute_signal(
                signal_dict,
                bankroll=bankroll,
                current_exposure=current_exposure,
                mode=mode,
            )
            if result.executed:
                from backend.core.strategy_executor import execute_decision

                trade_size = min(
                    settings.MAX_TRADE_SIZE,
                    (bankroll or 100.0) * settings.KELLY_FRACTION,
                )
                decision = {
                    "market_ticker": market_ticker,
                    "direction": sig["direction"] or "yes",
                    "size": trade_size,
                    "entry_price": sig["model_probability"] or 0.5,
                    "edge": sig["edge"] or 0.0,
                    "confidence": sig["confidence"] or 0.0,
                    "model_probability": sig["model_probability"],
                    "token_id": token_id,
                    "platform": (
                        "kalshi"
                        if market_ticker.startswith("KX")
                        else settings.DEFAULT_VENUE
                    ),
                }
                source_strategy = sig["track_name"]
                if not source_strategy:
                    logger.warning(
                        f"Signal {sig['id']} has no track_name — skipping auto-trader"
                    )
                    skipped += 1
                    processed_signal_ids.append(sig["id"])
                    continue
                exec_result = await execute_decision(
                    decision, source_strategy, mode=mode
                )
                if exec_result is not None:
                    processed_signal_ids.append(sig["id"])
                    executed += 1
                    current_exposure += trade_size
            elif result.pending_approval:
                queued += 1
            else:
                # Mark as processed even when skipped/rejected so we don't
                # re-attempt the same stale signal every cycle.
                processed_signal_ids.append(sig["id"])
                skipped += 1

        if processed_signal_ids:

            def _mark_signals_executed():
                from backend.db.utils import get_db_session

                with get_db_session() as db:
                    db.query(Signal).filter(Signal.id.in_(processed_signal_ids)).update(
                        {Signal.executed: True}, synchronize_session=False
                    )
                    db.commit()

            await asyncio.to_thread(_mark_signals_executed)

        log_event(
            "info",
            f"AutoTrader cycle: executed={executed} queued={queued} skipped={skipped}",
        )
        if len(signal_ids) >= 5 and executed == 0 and queued == 0:
            logger.warning(
                "[ALERT] auto_trader processed %d signals but created 0 trade attempts — check filters",
                len(signal_ids),
            )
    except asyncio.CancelledError:
        logger.info(f"auto_trader_job({mode}) cancelled during shutdown")
        return
    except Exception as e:
        log_event("error", f"auto_trader_job error: {e}")


async def auto_redeem_job() -> None:
    """Automatically redeem resolved Polymarket positions when explicitly enabled."""
    await asyncio.sleep(0)  # yield control to event loop
    from backend.core.scheduling.scheduler import log_event

    if not getattr(settings, "AUTO_REDEEM_ENABLED", False):
        return

    wallet = (
        getattr(settings, "POLYMARKET_BUILDER_ADDRESS", None)
        or getattr(settings, "POLYMARKET_WALLET_ADDRESS", None)
        or ""
    )
    private_key = getattr(settings, "POLYMARKET_PRIVATE_KEY", None) or ""

    if not wallet or not private_key:
        log_event(
            "warning",
            "Auto-redeem skipped: POLYMARKET_BUILDER_ADDRESS/POLYMARKET_WALLET_ADDRESS or POLYMARKET_PRIVATE_KEY not set",
        )
        return

    dry_run = bool(getattr(settings, "AUTO_REDEEM_DRY_RUN", True))
    db_scan = bool(getattr(settings, "AUTO_REDEEM_DB_SCAN_ENABLED", True))
    timeout_seconds = float(getattr(settings, "AUTO_REDEEM_TIMEOUT_SECONDS", 120.0))

    try:
        from backend.core.auto_redeem import redeem_all_redeemable

        result = await asyncio.wait_for(
            asyncio.to_thread(
                redeem_all_redeemable,
                wallet=wallet,
                private_key=private_key,
                builder_api_key=getattr(settings, "POLYMARKET_BUILDER_API_KEY", None),
                builder_secret=getattr(settings, "POLYMARKET_BUILDER_SECRET", None),
                builder_passphrase=getattr(
                    settings, "POLYMARKET_BUILDER_PASSPHRASE", None
                ),
                dry_run=dry_run,
                db_scan=db_scan,
            ),
            timeout=timeout_seconds,
        )
        status = "dry-run" if dry_run else "executed"
        log_event(
            "info",
            f"Auto-redeem {status}: attempted={result.total_attempted} redeemed={result.total_redeemed} failed={result.total_failed}",
            {
                "attempted": result.total_attempted,
                "redeemed": result.total_redeemed,
                "failed": result.total_failed,
                "dry_run": dry_run,
                "errors": result.errors,
            },
        )
    except asyncio.TimeoutError:
        log_event("error", f"Auto-redeem timed out after {timeout_seconds:.0f}s")
    except Exception as e:
        log_event("error", f"Auto-redeem failed: {e}")
        logger.exception("auto_redeem_job failed")


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
    from backend.core.scheduling.scheduler import log_event
    from backend.core.heartbeat import update_heartbeat as _update_heartbeat

    from backend.strategies.registry import STRATEGY_REGISTRY
    import json

    from backend.db.utils import get_db_session

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
                "warning",
                f"Strategy {strategy_name} not in registry — updating heartbeat anyway",
            )

            _update_heartbeat(strategy_name)
            return

        params = config_data["params"]
        effective_mode = config_data["effective_mode"]

        from backend.strategies.base import StrategyContext
        from backend.config import settings as _settings
        from backend.markets.provider_registry import market_registry

        # Phase 2: Run strategy — sync DB reads happen inside strategy.run(),
        # so open the session in a thread to avoid blocking the event loop.
        def _open_db_session():
            from backend.db.utils import get_db_session
            ctx = get_db_session()
            return ctx, ctx.__enter__()

        _db_ctx, db = await asyncio.to_thread(_open_db_session)
        try:
            ctx = StrategyContext(
                db=db,
                clob=None,
                settings=_settings,
                logger=logger,
                params=params,
                mode=effective_mode,
                market_registry=market_registry,
            )

            strategy = strategy_cls()
            result = await strategy.run(ctx)

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

            _update_heartbeat(strategy_name)

            log_event(
                "info",
                f"Strategy {strategy_name} cycle done: decisions={result.decisions_recorded} trades={result.trades_placed} errors={len(result.errors)}",
            )
        finally:
            _db_ctx.__exit__(None, None, None)

    except asyncio.CancelledError:
        logger.info(f"strategy_cycle_job({strategy_name}) cancelled during shutdown")
        return
    except Exception as e:
        log_event("error", f"Strategy cycle job failed for {strategy_name}: {e}")
        logger.exception(f"strategy_cycle_job({strategy_name})")

    # Heartbeat AFTER db.close() so the pool connection is returned first
    try:
        _update_heartbeat(strategy_name)
    except Exception:
        logger.exception(
            f"[scheduling_strategies] Heartbeat update failed for {strategy_name} after cycle"
        )

    gc.collect()


async def sync_testnet_wallet():
    """Testnet wallet sync — not yet implemented."""
    logger.warning("[sync_testnet_wallet] Not implemented — skipping")


async def sync_live_wallet():
    """Reconcile live wallet every 30 seconds."""
    from backend.db.utils import get_db_session

    try:
        from backend.core.wallet_reconciliation import WalletReconciler
        from backend.data.polymarket_clob import clob_from_settings
        from backend.core.bankroll_reconciliation import reconcile_bot_state

        logger.info("[sync_live_wallet] Starting reconciliation...")
        clob = clob_from_settings(mode="live")
        async with clob:
            await clob.create_or_derive_api_key()
            with get_db_session() as db:
                reconciler = WalletReconciler(clob, db, "live")
                result = await reconciler.full_reconciliation()

        logger.info(
            "[sync_live_wallet] Reconciliation done, updating BotState timestamp..."
        )

        def _update_bot_state_sync():
            from backend.db.utils import get_db_session

            with get_db_session() as db:
                state = db.query(BotState).filter_by(mode="live").first()
                if state and result.last_sync_at:
                    state.last_sync_at = result.last_sync_at
                    try:
                        db.flush()
                    except Exception as flush_err:
                        logger.warning(f"[sync_live_wallet] flush failed: {flush_err}")
                        db.rollback()

        await asyncio.to_thread(_update_bot_state_sync)

        logger.info("[sync_live_wallet] Calling reconcile_bot_state...")
        try:
            with get_db_session() as db:
                await reconcile_bot_state(
                    db,
                    modes=("live",),
                    apply=True,
                    commit=True,
                    source="live_wallet_sync_reconcile",
                )
            logger.info("[sync_live_wallet] reconcile_bot_state done")
        except Exception as recon_err:
            logger.exception(
                f"[sync_live_wallet] reconcile_bot_state failed: {recon_err}"
            )

        logger.info(
            f"Live wallet sync: imported={result.imported_count}, "
            f"updated={result.updated_count}, closed={result.closed_count}"
        )
    except Exception as e:
        logger.exception(f"Live wallet sync failed: {e}")


async def verify_settlement_blockchain():
    """Check unsettled trades and update with blockchain-verified settlement data."""
    await asyncio.sleep(0)  # yield control to event loop
    from backend.core.scheduling.scheduler import log_event
    from backend.core.settlement_helpers import (
        fetch_resolution_for_trade,
        calculate_pnl,
    )

    def _read_unsettled_trades():
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            unsettled = db.query(Trade).filter(Trade.settled.is_(False)).all()
            if not unsettled:
                state = db.query(BotState).first()
                if state:
                    state.settlement_last_check_at = datetime.now(timezone.utc)
                    db.flush()
                return []
            return [
                {
                    "id": t.id,
                    "market_ticker": t.market_ticker,
                    "settled": t.settled,
                    "settlement_value": t.settlement_value,
                    "pnl": t.pnl,
                    "result": t.result,
                    "direction": t.direction,
                    "size": t.size,
                    "entry_price": t.entry_price,
                    "event_slug": t.event_slug,
                    "token_id": t.token_id,
                    "trading_mode": t.trading_mode,
                    "market_type": t.market_type,
                    "outcome": t.outcome,
                }
                for t in unsettled
            ]

    try:
        trade_dicts = await asyncio.to_thread(_read_unsettled_trades)
        if not trade_dicts:
            log_event("data", "Settlement verification: no unsettled trades")
            return

        settled_count = 0
        error_count = 0
        settlements = []

        from backend.db.utils import get_db_session

        with get_db_session() as db:
            unsettled_trades = db.query(Trade).filter(Trade.settled.is_(False)).all()
            trade_map = {t.id: t for t in unsettled_trades}

            for td in trade_dicts:
                trade = trade_map.get(td["id"])
                if not trade:
                    continue
                try:
                    is_resolved, settlement_value = await fetch_resolution_for_trade(
                        trade
                    )

                    if is_resolved and settlement_value is not None:
                        pnl = calculate_pnl(trade, settlement_value)

                        trade.settled = True
                        trade.settlement_value = settlement_value
                        trade.pnl = pnl
                        trade.settlement_time = datetime.now(timezone.utc)
                        trade.blockchain_verified = True

                        if pnl is not None and pnl > 0:
                            trade.result = "win"
                        elif pnl is not None and pnl < 0:
                            trade.result = "loss"
                        else:
                            trade.result = "push"

                        settled_count += 1
                        settlements.append(
                            {
                                "id": trade.id,
                                "market": trade.market_ticker,
                                "result": trade.result,
                                "pnl": pnl,
                            }
                        )

                except Exception as e:
                    error_count += 1
                    logger.warning(
                        f"Settlement verification failed for trade {td['id']}: {e}"
                    )
                    continue

            state = db.query(BotState).first()
            if state:
                state.settlement_last_check_at = datetime.now(timezone.utc)

            db.commit()

        for s in settlements:
            logger.info(
                f"Settlement verified: trade_id={s['id']} market={s['market']} "
                f"result={s['result']} pnl=${s['pnl']:.2f}"
            )

        log_event(
            "success" if settled_count > 0 else "info",
            f"Settlement verified: {settled_count} trades settled, {error_count} errors",
            {
                "settled_count": settled_count,
                "error_count": error_count,
                "total_checked": len(trade_dicts),
            },
        )

    except Exception as e:
        log_event("error", f"Settlement verification job failed: {e}")
        logger.exception("Error in verify_settlement_blockchain")


async def market_universe_scan_job() -> None:
    """Periodic job to refresh the universal market universe cache.

    Scans all available markets across platforms (Polymarket, Kalshi) via
    DataProvider abstraction and caches results for fast lookup by downstream
    strategies. Runs every MARKET_UNIVERSE_CACHE_TTL_SECONDS (default 300s).
    """
    from backend.core.scheduling.scheduler import log_event

    try:
        markets = await scan_universe_markets(limit=settings.AUTO_TRADER_BATCH_SIZE)
        log_event(
            "info",
            f"Universe scan: {len(markets)} markets cached",
            {"market_count": len(markets)},
        )
    except Exception as e:
        log_event("error", f"Market universe scan job failed: {e}")
        logger.exception("Error in market_universe_scan_job")
