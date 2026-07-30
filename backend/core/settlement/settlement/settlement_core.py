"""Main settlement engine — orchestrates trade settlement, reconciliation, and post-settlement actions."""

import json as _json
import time as _time
from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy.orm import Session

from backend.config import settings
from backend.data.shared_client import get_shared_client
from backend.models.database import Trade, BotState, TransactionEvent
from backend.core.alert_manager import AlertManager
from backend.core.event_bus import _broadcast_event
from backend.core.knowledge_graph import KnowledgeGraph
from backend.core.strategy_gate import check_risk_and_disable
from backend.db.utils import get_db_session
from backend.models.audit_logger import log_settlement_completed
from backend.monitoring.hft_metrics import record_execution, db_query_duration
from backend.monitoring.metrics import increment_settlement_by_status

from backend.core.settlement.settlement_helpers import (
    fetch_resolution_for_trade,
    calculate_pnl,
    _resolve_markets,
    process_settled_trade,
    total_loss_settlement_value,
    reconcile_positions,
    resolve_paper_trades,
)

from loguru import logger

from .helpers import _ensure_session, _settlement_lock, _closed_unresolved_grace
from .btc_settle import _settle_btc_5min_trade
from .learning import _run_learning_pipeline_background


# ---------------------------------------------------------------------------
# Phase 1 — Reconcile positions closed on-chain
# ---------------------------------------------------------------------------
async def _reconcile_closed_positions(db: Session, alert_manager: AlertManager) -> int:
    """Reconcile positions that are no longer open on-chain.

    Returns the number of trades closed during reconciliation.
    Returns -1 if the entire reconciliation failed.
    """
    try:
        trades_to_close = await reconcile_positions(db)

        if not trades_to_close:
            return 0

        now = datetime.now(timezone.utc)
        closed_count = 0

        # Batch fetch all trades by ID (replaces N+1 per-trade query)
        trade_map: dict = {}
        for chunk_start in range(0, len(trades_to_close), 500):
            chunk = trades_to_close[chunk_start: chunk_start + 500]
            for t in db.query(Trade).filter(Trade.id.in_(chunk)).all():
                trade_map[t.id] = t

        for trade_id in trades_to_close:
            trade = trade_map.get(trade_id)
            if trade and (not trade.settled or trade.pnl is None):
                await _process_closed_trade(trade, now, db)
                closed_count += 1

                _broadcast_trade_settled(trade)
                _store_trade_memory(trade)

        if closed_count > 0:
            _ensure_session(db)
            db.commit()
            logger.info(
                f"Position reconciliation: processed {closed_count} trades"
            )
        return closed_count

    except Exception as e:
        logger.opt(exception=True).error(
            "Position reconciliation failed: {}", e,
        )
        alert_manager.check_failed_settlement(
            trade_id=0,
            reason=f"Position reconciliation failed: {e}",
            mode="paper",
        )
        return -1


async def _process_closed_trade(trade: Trade, now: datetime, db: Session) -> None:
    """Attempt to resolve a single reconciled trade, with grace-period retry."""
    is_resolved, settlement_value = await fetch_resolution_for_trade(trade)

    if is_resolved and settlement_value is not None:
        pnl = calculate_pnl(trade, settlement_value)
        await process_settled_trade(trade, True, settlement_value, pnl, db)
        logger.info(
            f"Position reconciliation: trade {trade.id} settled with resolution (pnl=${pnl:+.2f})"
        )
        return

    # Position is gone but API couldn't confirm outcome — grace period
    await _ensure_grace_period_check(trade, now, db)


async def _ensure_grace_period_check(trade: Trade, now: datetime, db: Session) -> None:
    """Apply grace period before force-settling a closed-unresolved trade as loss."""
    first_detected = _closed_unresolved_grace.get(trade.id)
    if first_detected is None:
        _closed_unresolved_grace[trade.id] = now
        logger.warning(
            "Position reconciliation: trade {} position gone, "
            "resolution unavailable — will retry (market={})",
            trade.id,
            trade.market_ticker,
        )
        return

    grace_elapsed = (now - _closed_unresolved_grace.get(trade.id, now)).total_seconds()
    unresolved_grace_hours = getattr(settings, "CLOSED_UNRESOLVED_GRACE_HOURS", 6)

    if grace_elapsed < unresolved_grace_hours * 3600:
        await _retry_resolution(trade, now, db)
        return

    # Grace period exhausted — force-settle as loss
    _force_settle_closed_unresolved(trade, now)


async def _retry_resolution(trade: Trade, now: datetime, db: Session) -> None:
    """Re-attempt resolution once within the grace period."""
    try:
        re_resolved, re_value = await fetch_resolution_for_trade(trade)
        if re_resolved and re_value is not None:
            pnl = calculate_pnl(trade, re_value)
            await process_settled_trade(trade, True, re_value, pnl, db)
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


def _force_settle_closed_unresolved(trade: Trade, now: datetime) -> None:
    """Mark a trade as loss after grace period expiry."""
    _closed_unresolved_grace.pop(trade.id, None)
    trade.settled = True
    trade.result = "loss"
    trade.settlement_time = now
    trade.settlement_source = "closed_unresolved"
    loss_sv = total_loss_settlement_value(trade.direction)
    trade.pnl = calculate_pnl(trade, loss_sv)
    trade.settlement_value = loss_sv
    logger.warning(
        "Position reconciliation: trade {} position gone, "
        "resolution unavailable after {}h grace — "
        "marking closed_unresolved (market={})",
        trade.id,
        getattr(settings, "CLOSED_UNRESOLVED_GRACE_HOURS", 6),
        trade.market_ticker,
    )


def _broadcast_trade_settled(trade: Trade) -> None:
    """Fire-and-forget broadcast on the event bus."""
    try:
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


def _store_trade_memory(trade: Trade) -> None:
    """Store trade outcome in knowledge graph."""
    try:
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


# ---------------------------------------------------------------------------
# Phase 2 — Query pending trades
# ---------------------------------------------------------------------------
async def _query_pending_trades(db: Session) -> List[Trade]:
    """Return all trades still pending settlement."""
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
        return pending
    except Exception as e:
        logger.error(f"Failed to query pending trades: {e}")
        return []


# ---------------------------------------------------------------------------
# Phase 3 — Categorise, resolve, and settle trades
# ---------------------------------------------------------------------------
_CACHED_WEATHER_KEYWORDS = [
    "temperature", "weather", "rain", "snow", "wind",
    "hurricane", "typhoon",
]
_CACHED_SPORTS_KEYWORDS = [
    "fifa", "nba", "nfl", "mlb", "soccer", "football", "tennis",
    "golf", "dota", "esports", "esp-irq", "eng-", "match",
]
_CACHED_POLITICAL_KEYWORDS = [
    "election", "president", "congress", "senate",
    "governor", "nominee", "maguire",
]


def _categorise_ticker(ticker: str, market_type: str) -> str:
    """Auto-detect market type from ticker slug."""
    if market_type == "weather":
        return "weather"
    ticker_lower = ticker.lower()
    if any(k in ticker_lower for k in _CACHED_WEATHER_KEYWORDS):
        return "weather"
    if any(
        k in ticker_lower
        for k in _CACHED_SPORTS_KEYWORDS + _CACHED_POLITICAL_KEYWORDS
    ):
        return "event"
    return market_type


async def _resolve_and_settle_trades(
    db: Session,
    pending: List[Trade],
    now: datetime,
    alert_manager: AlertManager,
) -> List[Trade]:
    """Categorise pending trades, resolve their markets, and settle each one.

    Returns the list of successfully settled trades.
    """
    stale_threshold = now - timedelta(hours=settings.STALE_TRADE_HOURS)

    # Categorise tickers
    normal_tickers: set = set()
    weather_tickers: set = set()
    trade_slugs: dict = {}
    trade_platforms: dict = {}

    for trade in pending:
        market_type = getattr(trade, "market_type", "btc") or "btc"
        ticker = trade.market_ticker or ""
        market_type = _categorise_ticker(ticker, market_type)
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

    # Resolve ALL markets before processing
    resolutions = await _resolve_markets(
        normal_tickers, weather_tickers, trade_slugs, trade_platforms
    )

    settled_trades: List[Trade] = []

    for trade in pending:
        is_settled, settlement_value, pnl = _settlement_from_resolution(
            trade, resolutions
        )

        # BTC 5-min UP/DOWN market settlement
        if (
            not is_settled
            and trade.market_ticker
            and trade.market_ticker.startswith("btc-updown-5m-")
        ):
            btc_result = await _settle_btc_5min_trade(trade, now)
            if btc_result:
                settled_trades.append(btc_result)
                continue

        # Normal process_settled_trade path
        if await process_settled_trade(trade, is_settled, settlement_value, pnl, db):
            record_execution(
                strategy=getattr(trade, "strategy", "unknown") or "unknown",
                side=getattr(trade, "direction", "n/a") or "n/a",
                status=f"settled_{trade.result}" if trade.result else "settled",
                latency_s=0.0,
            )
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

        # Check expired markets
        if _handle_expired_trade(trade, now, alert_manager):
            settled_trades.append(trade)
            continue

        # Check stale trades
        await _handle_stale_trade(trade, now, stale_threshold)

    _log_settlement_summary(settled_trades)
    _commit_settlements(db, settled_trades, alert_manager)
    return settled_trades


def _settlement_from_resolution(
    trade: Trade, resolutions: dict
) -> tuple[bool, float | None, float | None]:
    """Extract settlement outcome from resolved market data."""
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


def _handle_expired_trade(
    trade: Trade,
    now: datetime,
    alert_manager: AlertManager,
) -> bool:
    """Check if a trade's market has expired and settle accordingly.

    Returns True if the trade was settled as expired, False otherwise.
    """
    market_end = trade.market_end_date
    if not market_end:
        return False

    if market_end.tzinfo is None:
        market_end = market_end.replace(tzinfo=timezone.utc)
    if market_end >= now:
        return False

    expired_ago = (now - market_end).total_seconds()
    grace_hours = _expired_grace_hours(trade)
    if expired_ago < grace_hours * 3600:
        logger.info(
            f"Trade {trade.id}: market expired {expired_ago / 3600:.1f}h ago, "
            f"deferring settlement (grace period {grace_hours}h)"
        )
        return False

    trade.settled = True
    trade.result = "loss"
    trade.settlement_time = now
    loss_sv = total_loss_settlement_value(trade.direction)
    trade.pnl = calculate_pnl(trade, loss_sv)
    trade.settlement_value = loss_sv
    trade.settlement_source = "expired_unresolved"
    record_execution(
        strategy=getattr(trade, "strategy", "unknown") or "unknown",
        side=getattr(trade, "direction", "n/a") or "n/a",
        status="settled_expired",
        latency_s=0.0,
    )
    logger.warning(
        f"Trade {trade.id}: market expired {expired_ago / 3600:.1f}h ago, "
        f"resolution unavailable after grace period (assumed loss)"
    )
    return True


def _expired_grace_hours(trade: Trade) -> int:
    """Determine expired-trade grace period based on market type."""
    ticker = (trade.market_ticker or "").lower()
    if "5m" in ticker or "5-min" in ticker:
        return 1
    if any(
        k in ticker
        for k in [
            "temperature", "weather", "soccer", "football",
            "tennis", "dota", "nba", "nfl", "election",
            "senate", "governor",
        ]
    ):
        return 6
    return getattr(settings, "SETTLEMENT_GRACE_HOURS", 72)


async def _handle_stale_trade(
    trade: Trade,
    now: datetime,
    stale_threshold: datetime,
) -> None:
    """Check if a trade is stale and settle it if beyond grace period."""
    ts = trade.timestamp
    if ts and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if not ts or ts >= stale_threshold:
        return

    # Skip already-settled trades to prevent duplicate settlement
    if trade.settled:
        return

    trade_age_hours = (now - ts).total_seconds() / 3600
    stale_grace_hours = getattr(settings, "SETTLEMENT_GRACE_HOURS", 72)
    if trade_age_hours < stale_grace_hours:
        logger.info(
            f"Trade {trade.id}: stale ({trade_age_hours:.1f}h old) but within grace period, "
            f"deferring settlement"
        )
        return

    # Check on-chain position status
    if await _is_position_onchain(trade):
        logger.info(
            f"Trade {trade.id}: stale but still open on-chain, deferring"
        )
        return

    # Force settle as stale expired
    trade.settled = True
    trade.result = "loss"
    trade.settlement_time = now
    loss_sv = total_loss_settlement_value(trade.direction)
    trade.pnl = calculate_pnl(trade, loss_sv)
    trade.settlement_value = loss_sv
    trade.settlement_source = "stale_expired"
    record_execution(
        strategy=getattr(trade, "strategy", "unknown") or "unknown",
        side=getattr(trade, "direction", "n/a") or "n/a",
        status="settled_expired",
        latency_s=0.0,
    )


async def _is_position_onchain(trade: Trade) -> bool:
    """Check whether a trade's position is still open on-chain."""
    wallet = settings.POLYMARKET_BUILDER_ADDRESS
    if not wallet:
        return False
    try:
        client = get_shared_client()
        resp = await client.get(
            f"{settings.DATA_API_URL}/positions",
            params={"user": wallet},
        )
        if resp.status_code != 200:
            return False
        positions = resp.json()
        ticker = trade.market_ticker or ""
        for pos in positions:
            asset = pos.get("asset", "")
            slug = pos.get("slug", "")
            if ticker in (asset, slug) or asset in ticker or slug in ticker:
                if not pos.get("redeemable", False):
                    return True
    except Exception:
        logger.exception(
            f"settlement: failed to check on-chain position for stale trade {trade.id}"
        )
    return False


def _log_settlement_summary(settled_trades: List[Trade]) -> None:
    """Log aggregate settlement results."""
    unresolved_count = sum(
        1
        for t in settled_trades
        if getattr(t, "settlement_source", None)
        in ("expired_unresolved", "closed_unresolved", "stale_expired")
    )
    resolved_count = len(settled_trades) - unresolved_count

    try:
        if resolved_count > 0:
            increment_settlement_by_status("resolved")
        if unresolved_count > 0:
            increment_settlement_by_status("unresolved")
    except Exception:
        logger.exception("settlement: failed to increment settlement status metrics")

    if resolved_count:
        logger.info(f"Settled {resolved_count} trades with market resolution")
    if unresolved_count:
        logger.info(f"Marked {unresolved_count} unresolvable trades as total losses")
    if not settled_trades:
        logger.info("No trades ready for settlement (markets still open)")


def _commit_settlements(
    db: Session,
    settled_trades: List[Trade],
    alert_manager: AlertManager,
) -> None:
    """Commit settled trades to DB so state persists even if post-processing fails."""
    if not settled_trades:
        return
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


# ---------------------------------------------------------------------------
# Phase 4 — Paper trade settlement and bankroll topup
# ---------------------------------------------------------------------------
async def _settle_paper_trades(db: Session) -> None:
    """Resolve paper trades via Gamma outcome prices."""
    try:
        paper_settled = await resolve_paper_trades(db)
        if paper_settled:
            logger.info(
                f"Settled {len(paper_settled)} paper trades via Gamma outcomes"
            )
    except Exception as e:
        logger.warning(f"Paper trade settlement failed: {e}")
        db.rollback()


async def _auto_topup_paper_bankroll(db: Session) -> None:
    """Top-up paper bankroll if depleted below minimum."""
    try:
        paper_min = settings.PAPER_MIN_BANKROLL
        paper_topup_amt = settings.PAPER_TOPUP_AMOUNT
        max_topups = settings.MAX_TOPUPS
        paper_state = db.query(BotState).filter_by(mode="paper").first()
        if not paper_state:
            return

        current = float(paper_state.paper_bankroll or 0)
        try:
            misc = (
                _json.loads(paper_state.misc_data)
                if paper_state.misc_data
                else {}
            )
        except (ValueError, TypeError):
            misc = {}

        topup_count = int(misc.get("paper_topup_count", 0))
        if current >= paper_min or topup_count >= max_topups:
            return

        previous = current
        paper_state.paper_bankroll = current + paper_topup_amt
        paper_state._topup_count = topup_count + 1
        prev_initial = float(
            paper_state.paper_initial_bankroll or settings.INITIAL_BANKROLL
        )
        paper_state.paper_initial_bankroll = prev_initial + paper_topup_amt
        misc["paper_topup_count"] = topup_count + 1
        paper_state.misc_data = _json.dumps(misc)
        db.commit()
        logger.info(
            f"Paper bankroll auto-topup: ${paper_topup_amt:,.2f} "
            f"(${previous:,.2f} → ${paper_state.paper_bankroll:,.2f}), "
            f"topup #{topup_count + 1}/{max_topups}, "
            f"initial_bankroll ${prev_initial:,.2f} → "
            f"${paper_state.paper_initial_bankroll:,.2f}"
        )
        # Record TransactionEvent for audit trail
        try:
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
            db.rollback()
    except Exception as e:
        logger.error(f"Paper bankroll top-up failed: {e}")
        db.rollback()


# ---------------------------------------------------------------------------
# Phase 5 — Post-settlement actions
# ---------------------------------------------------------------------------
def _run_post_settlement_actions(
    settled_trades: List[Trade],
    db: Session,
) -> None:
    """Fire learning pipeline and check risk thresholds after settlement."""
    if settled_trades:
        try:
            _run_learning_pipeline_background(settled_trades)
        except Exception as e:
            logger.debug(f"Learning pipeline scheduling failed: {e}")

    try:
        disabled = check_risk_and_disable(db)
        if disabled:
            logger.warning(f"[RISK] Auto-disabled strategies: {disabled}")
    except Exception as e:
        logger.debug(f"Risk check failed (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
async def settle_pending_trades(db: Session) -> List[Trade]:
    """Settle all pending trades using Polymarket API outcomes. Deduplicates API calls per ticker."""
    if _settlement_lock.locked():
        logger.info("Settlement already in progress, skipping")
        return []

    async with _settlement_lock:
        _ensure_session(db)
        alert_manager = AlertManager(db)

        # Phase 1 — Reconciliation
        _ = await _reconcile_closed_positions(db, alert_manager)

        # Phase 2 — Query pending
        pending = await _query_pending_trades(db)
        if not pending:
            return []

        # Phase 3 — Resolve and settle
        now = datetime.now(timezone.utc)
        settled_trades = await _resolve_and_settle_trades(
            db, pending, now, alert_manager,
        )

        # Phase 4 — Paper trades + topup
        await _settle_paper_trades(db)
        await _auto_topup_paper_bankroll(db)

        # Phase 5 — Post-settlement
        _run_post_settlement_actions(settled_trades, db)

        return settled_trades

