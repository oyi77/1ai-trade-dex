"""Trade settlement logic using Polymarket API. Helpers live in settlement_helpers.py."""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List
from sqlalchemy.orm import Session

import re as _re

from backend.config import settings
from backend.models.database import Trade, BotState, botstate_mutex
from backend.core.alert_manager import AlertManager
from backend.monitoring.hft_metrics import record_execution, db_query_duration

from backend.core.settlement_helpers import (
    fetch_resolution_for_trade,
    check_market_settlement as check_market_settlement,
    calculate_pnl,
    _parse_market_resolution as _parse_market_resolution,
    _resolve_markets,
    process_settled_trade,
)

from loguru import logger
_settlement_lock = asyncio.Lock()


async def _fetch_pm_portfolio_value() -> float | None:
    """Fetch live total equity (USDC cash + open position value)."""
    from backend.core.bankroll_reconciliation import fetch_pm_total_equity

    return await fetch_pm_total_equity()


async def _settle_btc_5min_trade(trade: Trade, now: datetime) -> Trade | None:
    """Settle a BTC 5-min UP/DOWN market trade whose window has expired.

    Resolution strategy (in order of reliability):
    1. Polymarket API via fetch_btc_market_for_settlement (if market is closed)
    2. CEX BTC price at window end (Binance/Coinbase 1m klines) — determine if BTC
       went UP or DOWN relative to window start
    3. If both fail, mark as expired_unresolved instead of push (zero PnL misreports wins)
    """
    ticker = trade.market_ticker or ""
    match = _re.search(r"btc-updown-5m-(\d+)", ticker)
    if not match:
        return None

    window_start_ts = int(match.group(1))
    window_end = datetime.fromtimestamp(window_start_ts + 300, tz=timezone.utc)

    if now < window_end:
        return None

    entry_price = float(trade.entry_price or 0)
    size = float(trade.size or 0)
    direction = (trade.direction or "up").lower()

    try:
        from backend.data.btc_markets import fetch_btc_market_for_settlement
        btc_market = await fetch_btc_market_for_settlement(ticker)
        if btc_market and btc_market.closed:
            if direction == "up":
                won = btc_market.up_price > 0.9
            elif direction == "down":
                won = btc_market.down_price > 0.9
            else:
                won = False

            if won:
                trade.result = "win"
                trade.pnl = (1.0 - entry_price) * size if entry_price > 0 else 0.0
                trade.settlement_value = 1.0
                record_execution(strategy=trade.strategy or "btc_5min", side=trade.direction or "up", status="settled_win", latency_s=0.0)
            else:
                trade.result = "loss"
                trade.pnl = -(size * entry_price) if entry_price > 0 else -size
                trade.settlement_value = 0.0
                record_execution(strategy=trade.strategy or "btc_5min", side=trade.direction or "down", status="settled_loss", latency_s=0.0)

            trade.settled = True
            trade.settlement_time = now
            trade.settlement_source = "btc_5min_auto"
            return trade
    except Exception as e:
        logger.debug(f"btc_5min Polymarket settlement fetch failed for {ticker}: {e}")

    delayed_settle_seconds = 120
    if now < window_end + timedelta(seconds=delayed_settle_seconds):
        logger.info(
            f"BTC 5min {ticker}: window ended {delayed_settle_seconds}s ago, "
            "allowing more time for Polymarket resolution"
        )
        return None

    try:
        from backend.data.crypto import fetch_binance_klines
        klines = await fetch_binance_klines(limit=60)
        if klines and len(klines) > 1:
            start_price = None
            end_price = None
            for k in klines:
                k_ts_ms = int(float(k[0])) if isinstance(k[0], (int, float, str)) else 0
                k_ts_s = k_ts_ms // 1000
                if k_ts_s == window_start_ts:
                    start_price = float(k[4])
                if k_ts_s == window_start_ts + 300:
                    end_price = float(k[4])

            if start_price is not None and end_price is not None:
                went_up = end_price > start_price
                won = (direction == "up" and went_up) or (direction == "down" and not went_up)

                if won:
                    trade.result = "win"
                    trade.pnl = (1.0 - entry_price) * size if entry_price > 0 else 0.0
                    trade.settlement_value = 1.0
                else:
                    trade.result = "loss"
                    trade.pnl = -(size * entry_price) if entry_price > 0 else -size
                    trade.settlement_value = 0.0

                trade.settled = True
                trade.settlement_time = now
                trade.settlement_source = "btc_5min_cex_fallback"
                logger.info(
                    f"BTC 5min {ticker}: settled via CEX fallback start=${start_price:.2f} "
                    f"end=${end_price:.2f} dir={direction} won={won} pnl=${trade.pnl:+.2f}"
                )
                return trade
            elif end_price is not None or start_price is not None:
                _reference_price = end_price or start_price
                for k in klines:
                    k_ts_ms = int(float(k[0])) if isinstance(k[0], (int, float, str)) else 0
                    k_ts_s = k_ts_ms // 1000
                    if window_start_ts <= k_ts_s <= window_start_ts + 300:
                        if start_price is None:
                            start_price = float(k[4])
                        end_price = float(k[4])
                if start_price is not None and end_price is not None:
                    went_up = end_price > start_price
                    won = (direction == "up" and went_up) or (direction == "down" and not went_up)
                    if won:
                        trade.result = "win"
                        trade.pnl = (1.0 - entry_price) * size if entry_price > 0 else 0.0
                        trade.settlement_value = 1.0
                    else:
                        trade.result = "loss"
                        trade.pnl = -(size * entry_price) if entry_price > 0 else -size
                        trade.settlement_value = 0.0
                    trade.settled = True
                    trade.settlement_time = now
                    trade.settlement_source = "btc_5min_cex_fallback_scan"
                    logger.info(
                        f"BTC 5min {ticker}: settled via CEX scan start=${start_price:.2f} "
                        f"end=${end_price:.2f} dir={direction} won={won} pnl=${trade.pnl:+.2f}"
                    )
                    return trade
    except Exception as e:
        logger.warning(f"BTC 5min CEX fallback also failed for {ticker}: {e}")

    max_settle_age_hours = 24
    if now < trade.timestamp + timedelta(hours=max_settle_age_hours):
        logger.info(
            f"BTC 5min {ticker}: could not resolve yet, will retry next cycle"
        )
        return None

    trade.settled = True
    trade.result = "expired_unresolved"
    trade.pnl = -(size * entry_price) if entry_price > 0 else -size
    trade.settlement_time = now
    trade.settlement_source = "btc_5min_unresolved"
    trade.settlement_value = 0.0
    record_execution(strategy=trade.strategy or "btc_5min", side=trade.direction or "n/a", status="settled_expired", latency_s=0.0)
    logger.warning(
        f"BTC 5min {ticker}: could not resolve via Polymarket or CEX after {max_settle_age_hours}h, "
        f"marking as expired_unresolved (assumed loss)"
    )
    return trade


async def settle_pending_trades(db: Session) -> List[Trade]:
    """Settle all pending trades using Polymarket API outcomes. Deduplicates API calls per ticker."""
    if _settlement_lock.locked():
        logger.info("Settlement already in progress, skipping")
        return []

    async with _settlement_lock:
        alert_manager = AlertManager(db)

        try:
            from backend.core.settlement_helpers import reconcile_positions

            trades_to_close = await reconcile_positions(db)

            if trades_to_close:
                now = datetime.now(timezone.utc)
                closed_count = 0

                for trade_id in trades_to_close:
                    trade = db.query(Trade).filter(Trade.id == trade_id).first()
                    if trade and (not trade.settled or trade.pnl is None):
                        is_resolved, settlement_value = await fetch_resolution_for_trade(trade)

                        if is_resolved and settlement_value is not None:
                            pnl = calculate_pnl(trade, settlement_value)
                            await process_settled_trade(
                                trade, True, settlement_value, pnl, db
                            )
                            logger.info(
                                f"Position reconciliation: trade {trade.id} settled with resolution (pnl=${pnl:+.2f})"
                            )
                        else:
                            trade.settled = True
                            trade.result = "loss"
                            trade.settlement_time = now
                            trade.settlement_source = "closed_unresolved"
                            if trade.pnl is None:
                                trade.pnl = -(float(trade.size or 0) * float(trade.entry_price or 1.0))
                            if trade.settlement_value is None:
                                trade.settlement_value = 0.0
                            logger.warning(
                                "Position reconciliation: trade {} position gone but resolution unavailable — "
                                "marking closed_unresolved to release exposure (market={})",
                                trade.id,
                                trade.market_ticker,
                            )

                        closed_count += 1

                        try:
                            from backend.core.event_bus import _broadcast_event

                            _broadcast_event(
                                "trade_settled",
                                {
                                    "trade_id": trade.id,
                                    "market_ticker": trade.market_ticker,
                                    "result": trade.result,
                                    "pnl": trade.pnl or 0.0,
                                    "mode": getattr(trade, "trading_mode", "paper"),
                                    "strategy_name": getattr(trade, "strategy", None),
                                    "genome_id": getattr(trade, "genome_id", None),
                                    "settlement_source": getattr(trade, "settlement_source", None),
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                },
                            )
                        except Exception as e:
                            logger.debug(f"Broadcast event failed: {e}")

                        # Store trade memory in Knowledge Graph
                        try:
                            from backend.core.knowledge_graph import KnowledgeGraph
                            from backend.db.utils import get_db_session
                            with get_db_session() as kg_db:
                                kg = KnowledgeGraph(session=kg_db)
                                kg.store_trade_memory(
                                    trade_id=trade.id,
                                    strategy=getattr(trade, "strategy", "unknown") or "unknown",
                                    market_id=trade.market_ticker or "unknown",
                                    signal_reasoning=getattr(trade, "reasoning", "") or "",
                                    outcome_pnl=trade.pnl or 0.0,
                                    outcome_correct=(trade.result == "win"),
                                )
                        except Exception as e:
                            logger.error(f"KG write failed for trade {trade.id}: {e}")

                if closed_count > 0:
                    db.commit()
                    logger.info(
                        f"Position reconciliation: processed {closed_count} trades"
                    )
        except Exception as e:
            logger.opt(exception=True).error(
                "Position reconciliation failed: {}",
                e,
            )
            alert_manager.check_failed_settlement(
                trade_id=0,
                reason=f"Position reconciliation failed: {e}",
                mode="paper",
            )

        try:
            import time as _time
            _qstart = _time.monotonic()
            pending = db.query(Trade).filter(
                (Trade.settled.is_(False)) | ((Trade.settled.is_(True)) & (Trade.pnl.is_(None)))
            ).all()
            try:
                db_query_duration.labels(query_type="settlement_pending").observe(_time.monotonic() - _qstart)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Failed to query pending trades: {e}")
            return []

        if not pending:
            logger.info("No pending trades to settle")
            return []

        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(hours=settings.STALE_TRADE_HOURS)

        normal_tickers: set = set()
        weather_tickers: set = set()
        trade_slugs: dict = {}
        trade_platforms: dict = {}

        for trade in pending:
            market_type = getattr(trade, "market_type", "btc") or "btc"
            ticker = trade.market_ticker
            trade_slugs[ticker] = getattr(trade, "event_slug", None)
            trade_platforms[ticker] = (
                getattr(trade, "platform", "polymarket") or "polymarket"
            )
            if market_type == "weather":
                weather_tickers.add(ticker)
            else:
                normal_tickers.add(ticker)

        unique_tickers = normal_tickers | weather_tickers
        logger.info(
            f"Settlement: {len(pending)} trades across {len(unique_tickers)} markets "
            f"(saved {len(pending) - len(unique_tickers)} API calls)"
        )

        # Resolve ALL markets before expiring stale trades — a stale trade
        # whose market already resolved must get proper PnL, not pnl=0.
        resolutions = await _resolve_markets(
            normal_tickers, weather_tickers, trade_slugs, trade_platforms
        )

        def _settlement_from_resolution(trade) -> tuple:
            ticker = trade.market_ticker
            if ticker not in resolutions:
                return False, None, None
            is_resolved, settlement_value = resolutions[ticker]
            if not is_resolved or settlement_value is None:
                return False, None, None
            pnl = calculate_pnl(trade, settlement_value)
            market_type = getattr(trade, "market_type", "btc") or "btc"
            if market_type != "weather":
                mapped_dir = "UP" if trade.direction in ("up", "yes") else "DOWN"
                outcome = "UP" if settlement_value == 1.0 else "DOWN"
                result = "WIN" if mapped_dir == outcome else "LOSS"
                logger.info(
                    f"Trade {trade.id} settled: {mapped_dir} @ {trade.entry_price:.0%} -> "
                    f"{result} P&L: ${pnl:+.2f}"
                )
            return True, settlement_value, pnl

        settled_trades = []

        for trade in pending:
            is_settled, settlement_value, pnl = _settlement_from_resolution(trade)

            # BTC 5-min UP/DOWN market settlement (btc-updown-5m-* tickers)
            if not is_settled and trade.market_ticker and trade.market_ticker.startswith("btc-updown-5m-"):
                btc_result = await _settle_btc_5min_trade(trade, now)
                if btc_result:
                    settled_trades.append(btc_result)
                    continue

            if await process_settled_trade(
                trade, is_settled, settlement_value, pnl, db
            ):
                record_execution(
                    strategy=getattr(trade, "strategy", "unknown") or "unknown",
                    side=getattr(trade, "direction", "n/a") or "n/a",
                    status=f"settled_{trade.result}" if trade.result else "settled",
                    latency_s=0.0,
                )
                from backend.models.audit_logger import log_settlement_completed
                log_settlement_completed(
                    db=db,
                    trade_id=trade.id,
                    old_state={
                        "settled": False,
                        "result": "pending",
                        "pnl": None,
                    },
                    new_state={
                        "settled": True,
                        "result": trade.result,
                        "pnl": trade.pnl,
                        "settlement_value": settlement_value,
                        "settlement_time": trade.settlement_time.isoformat() if trade.settlement_time else None,
                    },
                    user_id="system:settlement",
                )
                settled_trades.append(trade)
                continue

            # Check if market's end_date has passed - if so and API can't
            # resolve it, try one last direct resolution before assuming total loss.
            market_end = trade.market_end_date
            if market_end:
                if market_end.tzinfo is None:
                    market_end = market_end.replace(tzinfo=timezone.utc)
                if market_end < now:
                    expired_ago = (now - market_end).total_seconds()

                    expired_resolution_grace_hours = 72
                    if expired_ago < expired_resolution_grace_hours * 3600:
                        logger.info(
                            f"Trade {trade.id}: market expired {expired_ago/3600:.1f}h ago, "
                            f"deferring settlement (grace period {expired_resolution_grace_hours}h)"
                        )
                        continue

                    trade.settled = True
                    trade.result = "loss"
                    trade.settlement_time = now
                    trade.pnl = -(float(trade.size or 0) * float(trade.entry_price or 1.0))
                    trade.settlement_value = 0.0
                    trade.settlement_source = "expired_unresolved"
                    settled_trades.append(trade)
                    record_execution(
                        strategy=getattr(trade, "strategy", "unknown") or "unknown",
                        side=getattr(trade, "direction", "n/a") or "n/a",
                        status="settled_expired",
                        latency_s=0.0,
                    )
                    logger.warning(
                        f"Trade {trade.id}: market expired {expired_ago/3600:.1f}h ago, "
                        f"resolution unavailable after grace period (assumed loss)"
                    )
                    continue

            ts = trade.timestamp
            if ts and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts and ts < stale_threshold:
                trade_age_hours = (now - ts).total_seconds() / 3600
                stale_grace_hours = 72
                if trade_age_hours < stale_grace_hours:
                    logger.info(
                        f"Trade {trade.id}: stale ({trade_age_hours:.1f}h old) but within grace period, "
                        f"deferring settlement"
                    )
                    continue

                _still_open = False
                try:
                    import httpx
                    _wallet = settings.POLYMARKET_BUILDER_ADDRESS
                    if _wallet:
                        async with httpx.AsyncClient(timeout=8.0) as _client:
                            _resp = await _client.get(
                                f"{settings.DATA_API_URL}/positions",
                                params={"user": _wallet},
                            )
                        if _resp.status_code == 200:
                            _positions = _resp.json()
                            _ticker = trade.market_ticker or ""
                            for _pos in _positions:
                                _asset = _pos.get("asset", "")
                                _slug = _pos.get("slug", "")
                                if _ticker in (_asset, _slug) or _asset in _ticker or _slug in _ticker:
                                    if not _pos.get("redeemable", False):
                                        _still_open = True
                                        logger.info(
                                            f"Trade {trade.id}: stale but still open on-chain "
                                            f"({(_pos.get('title','') or '')[:40]}), deferring"
                                        )
                                        break
                except Exception:
                    logger.exception(f"settlement: failed to check on-chain position for stale trade {trade.id}")
                if _still_open:
                    continue

                trade.settled = True
                trade.result = "loss"
                trade.settlement_time = now
                trade.pnl = -float(trade.size or 0)
                trade.settlement_value = 0.0
                trade.settlement_source = "stale_expired"
                settled_trades.append(trade)
                record_execution(
                    strategy=getattr(trade, "strategy", "unknown") or "unknown",
                    side=getattr(trade, "direction", "n/a") or "n/a",
                    status="settled_expired",
                    latency_s=0.0,
                )

        unresolved_count = sum(
            1 for t in settled_trades
            if getattr(t, "settlement_source", None) in (
                "expired_unresolved", "closed_unresolved", "stale_expired"
            )
        )
        resolved_count = len(settled_trades) - unresolved_count
        try:
            from backend.monitoring.metrics import increment_settlement_by_status
            increment_settlement_by_status("resolved")
            increment_settlement_by_status("unresolved")
        except Exception:
            logger.exception("settlement: failed to increment settlement status metrics")
        if resolved_count:
            logger.info(f"Settled {resolved_count} trades with market resolution")
        if unresolved_count:
            logger.info(f"Marked {unresolved_count} unresolvable trades as total losses")
        if not settled_trades:
            logger.info("No trades ready for settlement (markets still open)")

        # Commit trade settlement state to DB so it persists even if
        # update_bot_state_with_settlements() fails or is never called.
        if settled_trades:
            try:
                db.commit()
            except Exception as e:
                logger.error(f"Failed to commit trade settlements: {e}")
                alert_manager.check_failed_settlement(
                    trade_id=0,
                    reason=f"Failed to commit settlements: {e}",
                    mode="paper",
                )
                db.rollback()

        # Resolve paper trades via Gamma outcome prices
        try:
            from backend.core.settlement_helpers import resolve_paper_trades
            paper_settled = await resolve_paper_trades(db)
            if paper_settled:
                logger.info(f"Settled {len(paper_settled)} paper trades via Gamma outcomes")
        except Exception as e:
            logger.warning(f"Paper trade settlement failed: {e}")

        # Auto-topup paper bankroll if depleted
        try:
            paper_min = settings.PAPER_MIN_BANKROLL
            paper_topup_amt = settings.PAPER_TOPUP_AMOUNT
            max_topups = settings.MAX_TOPUPS
            paper_state = db.query(BotState).filter_by(mode="paper").first()
            if paper_state:
                current = float(paper_state.paper_bankroll or 0)
                import json as _json
                try:
                    misc = _json.loads(paper_state.misc_data) if paper_state.misc_data else {}
                except (ValueError, TypeError):
                    misc = {}
                topup_count = int(misc.get("paper_topup_count", 0))
                if current < paper_min and topup_count < max_topups:
                    previous = current
                    paper_state.paper_bankroll = current + paper_topup_amt
                    paper_state._topup_count = topup_count + 1
                    # Update paper_initial_bankroll so reconciliation
                    # doesn't treat the topup as phantom PnL drift
                    prev_initial = float(paper_state.paper_initial_bankroll or settings.INITIAL_BANKROLL)
                    paper_state.paper_initial_bankroll = prev_initial + paper_topup_amt
                    # Persist topup count across restarts via misc_data
                    misc["paper_topup_count"] = topup_count + 1
                    paper_state.misc_data = _json.dumps(misc)
                    db.commit()
                    logger.info(
                        f"Paper bankroll auto-topup: ${paper_topup_amt:,.2f} "
                        f"(${previous:,.2f} → ${paper_state.paper_bankroll:,.2f}), "
                        f"topup #{topup_count + 1}/{max_topups}, "
                        f"initial_bankroll ${prev_initial:,.2f} → ${paper_state.paper_initial_bankroll:,.2f}"
                    )
                    # Record TransactionEvent for audit trail (deposit type)
                    try:
                        from backend.models.database import TransactionEvent
                        event = TransactionEvent(
                            type="deposit",
                            amount=paper_topup_amt,
                            balance_after=float(paper_state.paper_bankroll),
                            context={
                                "source": "auto_topup",
                                "topup_number": topup_count + 1,
                                "max_topups": max_topups,
                                "trigger": f"bankroll ${previous:.2f} < min ${paper_min:.2f}",
                            },
                            note=f"Paper auto-topup #{topup_count + 1}: +${paper_topup_amt:,.2f}",
                        )
                        db.add(event)
                        db.commit()
                    except Exception as tee:
                        logger.debug(f"TransactionEvent recording for auto-topup failed: {tee}")
        except Exception as e:
            logger.error(f"Paper bankroll top-up failed: {e}")

        # Learning pipeline: process settled trades asynchronously
        # (non-blocking — settlement must never wait for learning)
        if settled_trades:
            try:
                _run_learning_pipeline_background(settled_trades)
            except Exception as e:
                logger.debug(f"Learning pipeline scheduling failed: {e}")

        # Risk check: auto-disable strategies exceeding loss thresholds
        try:
            from backend.core.strategy_gate import check_risk_and_disable
            disabled = check_risk_and_disable(db)
            if disabled:
                logger.warning(f"[RISK] Auto-disabled strategies: {disabled}")
        except Exception as e:
            logger.debug(f"Risk check failed (non-fatal): {e}")

        return settled_trades


def _run_learning_pipeline_background(settled_trades: List[Trade]) -> None:
    """Fire-and-forget learning pipeline for settled trades.

    Schedules an async task so settlement is never blocked.
    """
    from backend.core.learning_pipeline import get_learning_pipeline
    import asyncio

    async def _process_all() -> None:
        pipeline = get_learning_pipeline()
        for trade in settled_trades:
            if trade.result in ("win", "loss"):
                try:
                    await pipeline.process_settlement(
                        trade_id=trade.id,
                        strategy_name=getattr(trade, "strategy", "unknown") or "unknown",
                        market_id=trade.market_ticker or "unknown",
                        outcome=trade.result,
                        pnl_usd=trade.pnl or 0.0,
                        genome_id=getattr(trade, "genome_id", None),
                        regime_at_entry=getattr(trade, "regime", None),
                        signal_confidence=getattr(trade, "confidence", None),
                    )
                except Exception as e:
                    logger.debug(f"Learning pipeline failed for trade {trade.id}: {e}")

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_process_all())
    except RuntimeError:
        # No running loop — run in a thread
        import threading
        def _runner() -> None:
            try:
                asyncio.run(_process_all())
            except Exception as e:
                logger.debug(f"Learning pipeline thread failed: {e}")
        threading.Thread(target=_runner, name="learning-pipeline", daemon=True).start()


async def update_bot_state_with_settlements(
    db: Session, settled_trades: List[Trade]
) -> None:
    """Update bot state with P&L from settled trades."""
    if not settled_trades:
        return

    try:
        async with botstate_mutex:
            for trade in settled_trades:
                if trade.pnl is None:
                    continue

                trading_mode = getattr(trade, "trading_mode", "paper") or "paper"
                is_real_trade = trade.result in ("win", "loss")
                is_expired_or_push = trade.result in ("expired", "push", "closed")

                state = db.query(BotState).filter_by(mode=trading_mode).first()
                if not state:
                    logger.warning(f"Bot state not found for mode {trading_mode}")
                    continue

                if trading_mode == "paper":
                    if is_real_trade:
                        state.paper_pnl = (state.paper_pnl or 0.0) + trade.pnl
                        state.paper_bankroll = max(
                            0.0, (state.paper_bankroll or 0.0) + trade.size + trade.pnl
                        )
                        state.paper_trades = (state.paper_trades or 0) + 1
                        if trade.result == "win":
                            state.paper_wins = (state.paper_wins or 0) + 1
                    elif is_expired_or_push or trade.result in ("expired_unresolved", "btc_5min_unresolved"):
                        state.paper_bankroll = (state.paper_bankroll or 0.0) + trade.size
                        logger.info(
                            f"Expired/push trade {trade.id}: returned ${trade.size:.2f} to paper bankroll"
                        )
                elif trading_mode == "testnet":
                    if is_real_trade:
                        state.testnet_pnl = (state.testnet_pnl or 0.0) + trade.pnl
                        state.testnet_bankroll = max(
                            0.0, (state.testnet_bankroll or 0.0) + trade.size + trade.pnl
                        )
                        state.testnet_trades = (state.testnet_trades or 0) + 1
                        if trade.result == "win":
                            state.testnet_wins = (state.testnet_wins or 0) + 1
                    elif is_expired_or_push or trade.result in ("expired_unresolved", "btc_5min_unresolved"):
                        state.testnet_bankroll = (state.testnet_bankroll or 0.0) + trade.size
                        logger.info(
                            f"Expired/push trade {trade.id}: returned ${trade.size:.2f} to testnet bankroll"
                        )
                elif trading_mode == "live":
                    if is_real_trade:
                        state.total_trades = (state.total_trades or 0) + 1
                        if trade.result == "win":
                            state.winning_trades = (state.winning_trades or 0) + 1

            db.commit()

        modes_with_settlements = {
            getattr(t, "trading_mode", "paper") or "paper"
            for t in settled_trades
            if t.pnl is not None
        }

        # Sync live bankroll from authoritative total equity source.
        if "live" in modes_with_settlements:
            try:
                from backend.core.bankroll_reconciliation import reconcile_bot_state as _reconcile

                reports = await _reconcile(
                    db,
                    modes=("live",),
                    apply=True,
                    commit=True,
                    source="settlement_live_sync",
                )
                if reports:
                    report = reports[0]
                    logger.info(
                        "Live bankroll reconciled after settlement: $%.2f (source=%s)",
                        report.new_bankroll,
                        report.source,
                    )
            except Exception as exc:
                db.rollback()
                logger.warning("Live bankroll reconciliation after settlement failed: %s", exc)

        # Log stats for ALL modes that had settlements
        for m in sorted(modes_with_settlements):
            state = db.query(BotState).filter_by(mode=m).first()
            if not state:
                logger.warning(f"Bot state not found while logging mode {m}")
                continue
            if m == "paper":
                logger.info(
                    f"Updated bot state (paper): Bankroll ${state.paper_bankroll:.2f}, "
                    f"P&L ${state.paper_pnl:+.2f}, {state.paper_trades} trades"
                )
            elif m == "testnet":
                logger.info(
                    f"Updated bot state (testnet): Bankroll ${state.testnet_bankroll:.2f}, "
                    f"P&L ${state.testnet_pnl:+.2f}, {state.testnet_trades} trades"
                )
            else:
                logger.info(
                    f"Updated bot state (live): Bankroll ${state.bankroll:.2f}, "
                    f"P&L ${state.total_pnl:+.2f}, {state.total_trades} trades"
                )
    except Exception as e:
        logger.error(f"Failed to update bot state: {e}")
        db.rollback()


async def reconcile_bot_state(db: Session) -> None:
    """Recalculate bot_state from trade history to prevent drift.

    For live mode, cross-checks against Polymarket API portfolio value
    as the source of truth when on-chain wallet is available.
    """
    try:
        from backend.core.bankroll_reconciliation import reconcile_bot_state as _reconcile

        await _reconcile(db, apply=True, commit=True, source="settlement_reconcile")
        logger.debug("Bot state reconciliation complete")

    except Exception as e:
        logger.error(f"Bot state reconciliation failed: {e}")
        db.rollback()
