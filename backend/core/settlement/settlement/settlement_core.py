"""Main settlement engine — orchestrates trade settlement, reconciliation, and post-settlement actions."""

import time as _time
from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy.orm import Session

from backend.config import settings
from backend.data.shared_client import get_shared_client
from backend.models.database import Trade, BotState, botstate_mutex
from backend.core.alert_manager import AlertManager
from backend.monitoring.hft_metrics import record_execution, db_query_duration

from backend.core.settlement.settlement_helpers import (
    fetch_resolution_for_trade,
    calculate_pnl,
    _resolve_markets,
    process_settled_trade,
    total_loss_settlement_value,
)

from loguru import logger

from .helpers import _ensure_session, _settlement_lock, _closed_unresolved_grace
from .btc_settle import _settle_btc_5min_trade
from .learning import _run_learning_pipeline_background


async def settle_pending_trades(db: Session) -> List[Trade]:
    """Settle all pending trades using Polymarket API outcomes. Deduplicates API calls per ticker."""
    if _settlement_lock.locked():
        logger.info("Settlement already in progress, skipping")
        return []

    async with _settlement_lock:
        _ensure_session(db)
        alert_manager = AlertManager(db)

        try:
            from backend.core.settlement.settlement_helpers import reconcile_positions

            trades_to_close = await reconcile_positions(db)

            if trades_to_close:
                now = datetime.now(timezone.utc)
                closed_count = 0

                # Batch fetch all trades by ID (replaces N+1 per-trade query)
                trade_map: dict = {}
                for chunk_start in range(0, len(trades_to_close), 500):
                    chunk = trades_to_close[chunk_start : chunk_start + 500]
                    for t in db.query(Trade).filter(Trade.id.in_(chunk)).all():
                        trade_map[t.id] = t

                for trade_id in trades_to_close:
                    trade = trade_map.get(trade_id)
                    if trade and (not trade.settled or trade.pnl is None):
                        # BUG FIX: Previously, if fetch_resolution_for_trade returned
                        # False (API timeout/error), the trade was immediately marked as
                        # loss. This corrupted PnL/WR when the actual outcome was a win.
                        # Now: retry resolution with grace period before force-settling.
                        is_resolved, settlement_value = (
                            await fetch_resolution_for_trade(trade)
                        )

                        if is_resolved and settlement_value is not None:
                            pnl = calculate_pnl(trade, settlement_value)
                            await process_settled_trade(
                                trade, True, settlement_value, pnl, db
                            )
                            logger.info(
                                f"Position reconciliation: trade {trade.id} settled with resolution (pnl=${pnl:+.2f})"
                            )
                        else:
                            # Position is gone but API couldn't confirm outcome.
                            # Apply grace period before force-settling as loss.
                            first_detected = _closed_unresolved_grace.get(trade.id)
                            if first_detected is None:
                                # First detection — record and attempt resolution once more
                                _closed_unresolved_grace[trade.id] = now
                                logger.warning(
                                    "Position reconciliation: trade {} position gone, "
                                    "resolution unavailable — will retry (market={})",
                                    trade.id,
                                    trade.market_ticker,
                                )

                            grace_elapsed = (
                                now - _closed_unresolved_grace.get(trade.id, now)
                            ).total_seconds()
                            unresolved_grace_hours = getattr(
                                settings, "CLOSED_UNRESOLVED_GRACE_HOURS", 6
                            )

                            if grace_elapsed < unresolved_grace_hours * 3600:
                                # Still within grace period — try resolution one more time
                                try:
                                    re_resolved, re_value = (
                                        await fetch_resolution_for_trade(trade)
                                    )
                                    if re_resolved and re_value is not None:
                                        pnl = calculate_pnl(trade, re_value)
                                        await process_settled_trade(
                                            trade, True, re_value, pnl, db
                                        )
                                        _closed_unresolved_grace.pop(trade.id, None)
                                        logger.info(
                                            f"Position reconciliation: trade {trade.id} "
                                            f"resolved on retry within grace period (pnl=${pnl:+.2f})"
                                        )
                                except Exception:
                                    logger.exception(
                                        "Failed to re-resolve position for trade %d during grace period",
                                        trade.id,
                                    )
                                # Leave unsettled for next cycle
                                continue

                            # Grace period exhausted — force-settle as loss
                            _closed_unresolved_grace.pop(trade.id, None)
                            trade.settled = True
                            trade.result = "loss"
                            trade.settlement_time = now
                            trade.settlement_source = "closed_unresolved"
                            # Always recalculate — pre-set pnl may be wrong
                            # closed_unresolved = position gone, settle as loss
                            loss_sv = total_loss_settlement_value(trade.direction)
                            trade.pnl = calculate_pnl(trade, loss_sv)
                            trade.settlement_value = loss_sv
                            logger.warning(
                                "Position reconciliation: trade {} position gone, "
                                "resolution unavailable after {}h grace — "
                                "marking closed_unresolved (market={})",
                                trade.id,
                                unresolved_grace_hours,
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
                                    "settlement_source": getattr(
                                        trade, "settlement_source", None
                                    ),
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
                                    strategy=getattr(trade, "strategy", "unknown")
                                    or "unknown",
                                    market_id=trade.market_ticker or "unknown",
                                    signal_reasoning=getattr(trade, "reasoning", "")
                                    or "",
                                    outcome_pnl=trade.pnl or 0.0,
                                    outcome_correct=(trade.result == "win"),
                                )
                        except Exception as e:
                            logger.error(f"KG write failed for trade {trade.id}: {e}")

                if closed_count > 0:
                    _ensure_session(db)
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
            _ensure_session(db)
            _qstart = _time.monotonic()
            pending = (
                db.query(Trade)
                .filter(
                    (Trade.settled.is_(False))
                    | ((Trade.settled.is_(True)) & (Trade.pnl.is_(None)))
                )
                .all()
            )
            try:
                db_query_duration.labels(query_type="settlement_pending").observe(
                    _time.monotonic() - _qstart
                )
            except Exception:
                logger.debug("settlement: Prometheus metric recording failed")
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
            ticker = trade.market_ticker or ""
            # Auto-detect weather/sports/politics from ticker slug
            ticker_lower = ticker.lower()
            WEATHER_KEYWORDS = ["temperature", "weather", "rain", "snow", "wind", "hurricane", "typhoon"]
            SPORTS_KEYWORDS = ["fifa", "nba", "nfl", "mlb", "soccer", "football", "tennis", "golf", "dota", "esports", "esp-irq", "eng-", "match"]
            POLITICAL_KEYWORDS = ["election", "president", "congress", "senate", "governor", "nominee", "maguire"]
            if market_type != "weather" and any(k in ticker_lower for k in WEATHER_KEYWORDS):
                market_type = "weather"
            elif any(k in ticker_lower for k in SPORTS_KEYWORDS + POLITICAL_KEYWORDS):
                market_type = "event"
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
            if (
                not is_settled
                and trade.market_ticker
                and trade.market_ticker.startswith("btc-updown-5m-")
            ):
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
                        "settlement_time": (
                            trade.settlement_time.isoformat()
                            if trade.settlement_time
                            else None
                        ),
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

                    # Grace period by market type
                    market_type = getattr(trade, "market_type", "btc") or "btc"
                    ticker = (trade.market_ticker or "").lower()
                    if "5m" in ticker or "5-min" in ticker:
                        expired_resolution_grace_hours = 1
                    elif any(k in ticker for k in ["temperature", "weather", "soccer", "football", "tennis", "dota", "nba", "nfl", "election", "senate", "governor"]):
                        # Weather/sports/politics: settle within 6 hours
                        expired_resolution_grace_hours = 6
                    else:
                        expired_resolution_grace_hours = getattr(
                            settings, "SETTLEMENT_GRACE_HOURS", 72
                        )
                    if expired_ago < expired_resolution_grace_hours * 3600:
                        logger.info(
                            f"Trade {trade.id}: market expired {expired_ago/3600:.1f}h ago, "
                            f"deferring settlement (grace period {expired_resolution_grace_hours}h)"
                        )
                        continue

                    trade.settled = True
                    trade.result = "loss"
                    trade.settlement_time = now
                    loss_sv = total_loss_settlement_value(trade.direction)
                    trade.pnl = calculate_pnl(trade, loss_sv)
                    trade.settlement_value = loss_sv
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
                # BUG FIX: Skip already-settled trades to prevent duplicate settlement
                # (e.g. trade settled by closed_unresolved in reconciliation, then
                # re-processed here as stale_expired, corrupting PnL/WR)
                if trade.settled:
                    continue

                trade_age_hours = (now - ts).total_seconds() / 3600
                stale_grace_hours = getattr(settings, "SETTLEMENT_GRACE_HOURS", 72)
                if trade_age_hours < stale_grace_hours:
                    logger.info(
                        f"Trade {trade.id}: stale ({trade_age_hours:.1f}h old) but within grace period, "
                        f"deferring settlement"
                    )
                    continue

                _still_open = False
                try:
                    _wallet = settings.POLYMARKET_BUILDER_ADDRESS
                    if _wallet:
                        _client = get_shared_client()
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
                                if (
                                    _ticker in (_asset, _slug)
                                    or _asset in _ticker
                                    or _slug in _ticker
                                ):
                                    if not _pos.get("redeemable", False):
                                        _still_open = True
                                        logger.info(
                                            f"Trade {trade.id}: stale but still open on-chain "
                                            f"({(_pos.get('title','') or '')[:40]}), deferring"
                                        )
                                        break
                except Exception:
                    logger.exception(
                        f"settlement: failed to check on-chain position for stale trade {trade.id}"
                    )
                if _still_open:
                    continue

                trade.settled = True
                trade.result = "loss"
                trade.settlement_time = now
                loss_sv = total_loss_settlement_value(trade.direction)
                trade.pnl = calculate_pnl(trade, loss_sv)
                trade.settlement_value = loss_sv
                trade.settlement_source = "stale_expired"
                settled_trades.append(trade)
                record_execution(
                    strategy=getattr(trade, "strategy", "unknown") or "unknown",
                    side=getattr(trade, "direction", "n/a") or "n/a",
                    status="settled_expired",
                    latency_s=0.0,
                )

        unresolved_count = sum(
            1
            for t in settled_trades
            if getattr(t, "settlement_source", None)
            in ("expired_unresolved", "closed_unresolved", "stale_expired")
        )
        resolved_count = len(settled_trades) - unresolved_count
        try:
            from backend.monitoring.metrics import increment_settlement_by_status

            if resolved_count > 0:
                increment_settlement_by_status("resolved")
            if unresolved_count > 0:
                increment_settlement_by_status("unresolved")
        except Exception:
            logger.exception(
                "settlement: failed to increment settlement status metrics"
            )
        if resolved_count:
            logger.info(f"Settled {resolved_count} trades with market resolution")
        if unresolved_count:
            logger.info(
                f"Marked {unresolved_count} unresolvable trades as total losses"
            )
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
            from backend.core.settlement.settlement_helpers import resolve_paper_trades

            paper_settled = await resolve_paper_trades(db)
            if paper_settled:
                logger.info(
                    f"Settled {len(paper_settled)} paper trades via Gamma outcomes"
                )
        except Exception as e:
            logger.warning(f"Paper trade settlement failed: {e}")
            db.rollback()

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
                    misc = (
                        _json.loads(paper_state.misc_data)
                        if paper_state.misc_data
                        else {}
                    )
                except (ValueError, TypeError):
                    misc = {}
                topup_count = int(misc.get("paper_topup_count", 0))
                if current < paper_min and topup_count < max_topups:
                    previous = current
                    paper_state.paper_bankroll = current + paper_topup_amt
                    paper_state._topup_count = topup_count + 1
                    # Update paper_initial_bankroll so reconciliation
                    # doesn't treat the topup as phantom PnL drift
                    prev_initial = float(
                        paper_state.paper_initial_bankroll or settings.INITIAL_BANKROLL
                    )
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
                        logger.debug(
                            f"TransactionEvent recording for auto-topup failed: {tee}"
                        )
                        db.rollback()
        except Exception as e:
            logger.error(f"Paper bankroll top-up failed: {e}")
            db.rollback()

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
