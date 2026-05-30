"""Execute strategy decisions — create trades in paper mode, place orders in live mode."""

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional
import threading

from backend.config import settings
from backend.models.database import (
    Trade,
    Signal,
    BotState,
    StrategyConfig,
    botstate_mutex,
)
from backend.core.risk_manager import RiskManager
from backend.core.event_bus import _broadcast_event
from backend.core.mode_context import get_context
from backend.core.alert_manager import AlertManager
from backend.core.validation import (
    TradeValidator,
    SignalValidator,
    ValidationError,
    log_validation_error,
)
from backend.core.external_rate_limiter import TokenBucketRateLimiter
from backend.core.trade_attempts import TradeAttemptRecorder
from backend.core.paper_slippage import get_simulator
from sqlalchemy import case, func, and_, update
from sqlalchemy.exc import OperationalError
from backend.core.retry import retry

from loguru import logger

risk_manager = RiskManager()

# Per-asset locks allow concurrent execution across different markets while
# serializing same-market orders to prevent bankroll/exposure double-counting.
# A global semaphore caps total concurrent trades.
_trade_locks: dict[str, asyncio.Lock] = {}
_trade_locks_mutex = asyncio.Lock()
MAX_CONCURRENT_TRADES = settings.MAX_CONCURRENT_TRADES
_trade_semaphore = asyncio.Semaphore(MAX_CONCURRENT_TRADES)

_rate_limiter: Optional[TokenBucketRateLimiter] = None


@retry(max_attempts=3, retryable_exceptions=(OperationalError,))
def _commit_with_retry(db) -> None:
    """Commit a DB session with retry on OperationalError."""
    try:
        db.commit()
    except OperationalError:
        db.rollback()
        raise


def _get_rate_limiter() -> TokenBucketRateLimiter:
    """Lazily instantiate the global rate limiter."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = TokenBucketRateLimiter(
            per_market_limit=int(getattr(settings, "ORDER_RATE_LIMIT_PER_MARKET", 1)),
            per_market_window=10.0,
            global_limit=int(getattr(settings, "ORDER_RATE_LIMIT_GLOBAL", 3)),
            global_window=1.0,
        )
    return _rate_limiter


# Threading lock for BotState mutations inside thread-offloaded execution.
# Used instead of asyncio.Lock when running in a thread pool.
_botstate_threading_lock = threading.Lock()
_MAX_LOCK_RETRY_ATTEMPTS = 4
_LOCK_RETRY_BASE_DELAY_SECONDS = 0.2


class _BotStateLockRetry(RuntimeError):
    """Signal that trade execution should retry after BotState lock contention."""


def _is_lock_timeout_error(exc: OperationalError) -> bool:
    """Return True for PostgreSQL lock-timeout / lock-not-available failures."""

    orig = getattr(exc, "orig", None)
    pgcode = getattr(orig, "pgcode", None)
    if pgcode == "55P03":
        return True

    message = str(exc).lower()
    return (
        "lock timeout" in message
        or "locknotavailable" in message
        or "could not obtain lock" in message
        or "canceling statement due to lock timeout" in message
    )


def _lock_retry_delay(attempt: int) -> float:
    return _LOCK_RETRY_BASE_DELAY_SECONDS * (2**attempt)


def _update_botstate_after_trade(db, mode: str, adjusted_size: float) -> None:
    """Atomically update BotState counters without taking an ORM row lock."""

    if mode == "paper":
        paper_balance_after_trade = (
            func.coalesce(BotState.paper_bankroll, 0.0) - adjusted_size
        )
        db.execute(
            update(BotState)
            .where(BotState.mode == mode)
            .values(
                paper_bankroll=case(
                    (paper_balance_after_trade < 0.0, 0.0),
                    else_=paper_balance_after_trade,
                ),
                paper_trades=func.coalesce(BotState.paper_trades, 0) + 1,
            )
        )
    elif mode == "testnet":
        testnet_balance_after_trade = (
            func.coalesce(BotState.testnet_bankroll, 0.0) - adjusted_size
        )
        db.execute(
            update(BotState)
            .where(BotState.mode == mode)
            .values(
                testnet_bankroll=case(
                    (testnet_balance_after_trade < 0.0, 0.0),
                    else_=testnet_balance_after_trade,
                ),
                testnet_trades=func.coalesce(BotState.testnet_trades, 0) + 1,
            )
        )
    elif mode == "live":
        db.execute(
            update(BotState)
            .where(BotState.mode == mode)
            .values(total_trades=func.coalesce(BotState.total_trades, 0) + 1)
        )


async def _get_asset_lock(asset_key: str) -> asyncio.Lock:
    async with _trade_locks_mutex:
        if asset_key not in _trade_locks:
            _trade_locks[asset_key] = asyncio.Lock()
        return _trade_locks[asset_key]


def _cfg(key: str, default=None):
    val = getattr(settings, key, default) if hasattr(settings, key) else default
    if default is not None and not isinstance(val, (int, float, str, bool)):
        return default
    return val


def _fetch_orderbook_depth(token_id: str | None) -> float:
    """Sync read of orderbook depth from the in-memory cache.

    Returns total depth (bids + asks) in USD, or 0.0 if unavailable.
    Safe to call from sync context — accesses the cache dict directly.
    """
    if not token_id:
        return 0.0
    try:
        from backend.data.orderbook_cache import get_orderbook_cache

        cache = get_orderbook_cache()
        # Access internal cache dict directly (sync context, no async lock needed)
        book = cache._cache.get(token_id)
        max_age = getattr(cache, "_max_age", 30.0)
        if book and book.age_seconds < max_age:
            bid_depth = sum(
                float(b.get("price", 0)) * float(b.get("size", 0)) for b in book.bids
            )
            ask_depth = sum(
                float(a.get("price", 0)) * float(a.get("size", 0)) for a in book.asks
            )
            return bid_depth + ask_depth
    except Exception as e:
        logger.debug("orderbook depth fetch failed for %s: %s", token_id, e)
    return 0.0


def _record_unexpected_attempt_failure(
    db,
    decision: dict,
    strategy_name: str,
    mode: str,
    reason: str,
    attempt_id: str | None = None,
) -> None:
    """Best-effort persistence for unexpected failures after transaction rollback."""

    try:
        recorder = None
        if attempt_id:
            from backend.models.database import TradeAttempt

            existing_attempt = (
                db.query(TradeAttempt)
                .filter(TradeAttempt.attempt_id == attempt_id)
                .first()
            )
            if existing_attempt is not None:
                recorder = TradeAttemptRecorder.__new__(TradeAttemptRecorder)
                recorder.db = db
                recorder.started_at = time.perf_counter()
                recorder.attempt = existing_attempt
        if recorder is None:
            recorder = TradeAttemptRecorder(db, decision, strategy_name, mode)
        recorder.record_failed(reason, phase="error")
        db.commit()
    except Exception as record_exc:
        try:
            db.rollback()
        except Exception:
            logger.exception(
                "[strategy_executor] db.rollback failed after TradeAttempt record failure"
            )
        logger.opt(exception=True).warning(
            "[strategy_executor.execute_decision] failed to record unexpected TradeAttempt failure: %s",
            record_exc,
        )


def _execute_decision_paper_or_kalshi(
    decision: dict, strategy_name: str, mode: str, db=None
) -> Optional[dict]:
    """Synchronous trade execution path for paper/testnet/Kalshi modes.

    Runs entirely in a thread pool — no async I/O, all DB operations are
    synchronous SQLAlchemy calls. The caller acquires async coordination
    locks on the event loop before calling this.

    If db is provided (e.g. in tests), that session is used directly.
    Otherwise a fresh session is opened via get_db_session().
    """
    market_ticker = decision.get("market_ticker", "")
    direction = decision.get("direction", "")
    size = float(decision.get("size", 0.0))
    entry_price = float(decision.get("entry_price", 0.5))
    edge = float(decision.get("edge", 0.0))
    confidence = float(decision.get("confidence", 0.0))
    model_probability = float(decision.get("model_probability", confidence))
    token_id = decision.get("token_id")
    platform = decision.get("platform", "polymarket")
    reasoning = decision.get("reasoning", "")
    market_type = decision.get("market_type", "btc")
    market_end_date_str = decision.get("market_end_date")

    from contextlib import nullcontext

    from backend.db.utils import get_db_session

    ctx = nullcontext(db) if db is not None else get_db_session()
    with ctx as db:
        attempt_recorder = None
        try:
            attempt_recorder = TradeAttemptRecorder(db, decision, strategy_name, mode)

            try:
                context = get_context(mode)
            except KeyError:
                logger.error(f"[{strategy_name}] No execution context for mode: {mode}")
                attempt_recorder.record_blocked(
                    f"No execution context for mode: {mode}",
                    phase="context",
                    reason_code="BLOCKED_NO_EXECUTION_CONTEXT",
                )
                db.commit()
                return None

            event_slug = decision.get("slug") or decision.get("event_slug")
            filters = [
                Trade.settled.is_(False),
                Trade.trading_mode == mode,
            ]
            if event_slug:
                filters.append(
                    and_(
                        Trade.market_ticker == market_ticker,
                        Trade.event_slug == event_slug,
                    )
                )
            else:
                filters.append(Trade.market_ticker == market_ticker)
            existing = db.query(Trade).filter(*filters, Trade.strategy != strategy_name).first()
            if existing:
                logger.info(
                    f"[{strategy_name}] Duplicate execution blocked for {market_ticker}/{event_slug}"
                )
                attempt_recorder.record_blocked(
                    "Duplicate open position for market",
                    phase="preflight",
                    reason_code="BLOCKED_DUPLICATE_OPEN_POSITION",
                    trade_id=existing.id,
                )
                db.commit()
                return None

            state = db.query(BotState).filter_by(mode=mode).first()
            if not state or not state.is_running:
                logger.info(
                    f"[{strategy_name}] Bot not running, skipping decision for {market_ticker}"
                )

                strategy_config = (
                    db.query(StrategyConfig)
                    .filter_by(strategy_name=strategy_name)
                    .first()
                )
                if not strategy_config or not strategy_config.enabled:
                    logger.warning(
                        f"[{strategy_name}] Skipping execution as strategy is disabled or missing in config"
                    )
                    attempt_recorder.record_blocked(
                        "Strategy disabled or missing",
                        phase="preflight",
                        reason_code="BLOCKED_STRATEGY_DISABLED",
                    )
                    db.commit()
                    return None
                attempt_recorder.record_blocked(
                    "Bot not running for selected mode",
                    phase="preflight",
                    reason_code="BLOCKED_BOT_NOT_RUNNING",
                )
                db.commit()
                return None

            # --- G-16: Cooldown after consecutive losses ---
            cooldown_losses = int(_cfg("COOLDOWN_CONSECUTIVE_LOSSES", 3) or 3)
            cooldown_minutes = int(_cfg("COOLDOWN_MINUTES", 60) or 60)
            if cooldown_losses > 0:
                from datetime import timedelta as _td

                recent_trades = (
                    db.query(Trade)
                    .filter(
                        Trade.strategy == strategy_name,
                        Trade.settled.is_(True),
                        Trade.trading_mode == mode,
                    )
                    .order_by(Trade.settlement_time.desc())
                    .limit(cooldown_losses)
                    .all()
                )
                if len(recent_trades) >= cooldown_losses:
                    all_losses = all(t.result == "loss" for t in recent_trades)
                    if all_losses:
                        last_loss_time = recent_trades[0].settlement_time
                        if last_loss_time and last_loss_time.tzinfo is None:
                            last_loss_time = last_loss_time.replace(tzinfo=timezone.utc)
                        cooldown_until = last_loss_time + _td(minutes=cooldown_minutes)
                        now_utc = datetime.now(timezone.utc)
                        if now_utc < cooldown_until:
                            remaining = (
                                cooldown_until - now_utc
                            ).total_seconds() / 60.0
                            logger.info(
                                f"[{strategy_name}] Cooldown active: {cooldown_losses} consecutive losses, "
                                f"pausing for {remaining:.1f} more minutes"
                            )
                            attempt_recorder.record_blocked(
                                f"Cooldown: {cooldown_losses} consecutive losses, {remaining:.1f}min remaining",
                                phase="cooldown",
                                reason_code="BLOCKED_COOLDOWN",
                            )
                            db.commit()
                            return None

            if mode == "paper":
                bankroll = (
                    state.paper_bankroll if state.paper_bankroll is not None else 0.0
                )
            elif mode == "testnet":
                bankroll = (
                    state.testnet_bankroll
                    if state.testnet_bankroll is not None
                    else 0.0
                )
            else:
                bankroll = (
                    state.bankroll
                    if state.bankroll is not None
                    else _cfg("INITIAL_BANKROLL", 1000.0)
                )

            # Bankroll reconciliation is async — skip in thread path, log warning
            if bankroll < 0:
                logger.warning(
                    "[%s] Negative bankroll ($%.2f) detected in thread-offloaded path; "
                    "skipping async reconciliation — using floor $0.00",
                    mode.upper(),
                    bankroll,
                )
                bankroll = 0.0

            # --- Hard safety guards: per-trade max loss, daily cap, portfolio breaker ---
            safety_block = _pre_trade_safety_checks(db, strategy_name, mode, bankroll, size)
            if safety_block is not None:
                logger.warning(f"[{strategy_name}] Safety guard blocked: {safety_block}")
                attempt_recorder.record_blocked(
                    safety_block,
                    phase="safety_guard",
                    reason_code="BLOCKED_SAFETY_GUARD",
                )
                db.commit()
                return None

            current_exposure = _get_current_exposure(db, trading_mode=mode)
            attempt_recorder.update(
                phase="risk_gate",
                status="RISK_EVALUATING",
                reason_code="RISK_EVALUATING",
                reason="Risk manager evaluating trade",
                bankroll=bankroll,
                current_exposure=current_exposure,
                factors_json={
                    "bankroll": bankroll,
                    "current_exposure": current_exposure,
                    "requested_size": size,
                    "confidence": confidence,
                    "market_ticker": market_ticker,
                    "mode": mode,
                },
            )

            risk = context.risk_manager.validate_trade(
                size=size,
                current_exposure=current_exposure,
                bankroll=bankroll,
                confidence=confidence,
                market_ticker=market_ticker,
                db=db,
                mode=mode,
                strategy_name=strategy_name,
                direction=direction if direction else None,
            )
            if not risk.allowed:
                logger.info(
                    f"[{strategy_name}] Risk rejected {market_ticker}: {risk.reason}"
                )
                attempt_recorder.record_rejected(
                    risk.reason,
                    phase="risk_gate",
                    risk_allowed=False,
                    risk_reason=risk.reason,
                    adjusted_size=risk.adjusted_size,
                )
                db.commit()
                return None

            adjusted_size = risk.adjusted_size
            attempt_recorder.update(
                status="RISK_APPROVED",
                phase="risk_gate",
                reason_code="RISK_APPROVED",
                reason="Risk gate approved trade",
                risk_allowed=True,
                risk_reason=risk.reason,
                adjusted_size=adjusted_size,
            )

            min_size = _cfg("MIN_ORDER_USDC", 5.0)
            if adjusted_size < min_size:
                logger.info(
                    f"[{mode.upper()}][{strategy_name}] Order rejected for {market_ticker}: "
                    f"Size ${adjusted_size:.2f} below minimum ${min_size}"
                )
                attempt_recorder.record_rejected(
                    f"Size ${adjusted_size:.2f} below minimum ${min_size:.2f}",
                    phase="sizing",
                    reason_code="REJECTED_ORDER_TOO_SMALL",
                    adjusted_size=adjusted_size,
                )
                db.commit()
                return None

            # --- Stale-market filter: dynamic threshold based on market lifetime ---
            from datetime import timedelta

            market_end_date = None
            if market_end_date_str:
                try:
                    market_end_date = datetime.fromisoformat(
                        market_end_date_str.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    logger.exception(
                        f"[{strategy_name}] failed to parse market_end_date for stale check: {market_ticker}"
                    )
            if market_end_date is not None:
                _now = datetime.now(timezone.utc)
                _time_to_resolution = (market_end_date - _now).total_seconds() / 60.0
                # Dynamic threshold: 2 min for short-lived (5m/15m) markets, 60 min otherwise
                _is_short_lived = "-5m-" in str(market_ticker) or "-15m-" in str(
                    market_ticker
                )
                _stale_threshold = 2.0 if _is_short_lived else 60.0
                if _time_to_resolution < _stale_threshold:
                    logger.info(
                        f"[{strategy_name}] Stale market blocked: {market_ticker} resolves in "
                        f"{_time_to_resolution:.1f} min (< {_stale_threshold:.0f} min threshold)"
                    )
                    attempt_recorder.record_rejected(
                        f"Stale market: {market_ticker} resolves in {_time_to_resolution:.1f} min",
                        phase="stale_market",
                        reason_code="REJECTED_STALE_MARKET",
                        adjusted_size=adjusted_size,
                    )
                    db.commit()
                    return None

            # --- Duplicate market guard: block if same strategy+ticker traded recently (same mode only) ---
            _cooldown_sec = _cfg("DUPLICATE_TRADE_COOLDOWN_SEC", 60)
            _cutoff = datetime.now(timezone.utc) - timedelta(seconds=_cooldown_sec)
            _dup_query = (
                db.query(Trade)
                .filter(
                    Trade.strategy == strategy_name,
                    Trade.market_ticker == market_ticker,
                    Trade.timestamp >= _cutoff,
                )
            )
            if mode:
                _dup_query = _dup_query.filter(Trade.trading_mode == mode)
            _recent_dup = _dup_query.first()
            if _recent_dup is not None:
                logger.warning(
                    f"[{strategy_name}] Duplicate blocked: already traded {market_ticker} "
                    f"(any direction) within {_cooldown_sec} sec (trade #{_recent_dup.id})"
                )
                attempt_recorder.record_rejected(
                    f"Duplicate: {market_ticker} already traded in last {_cooldown_sec} sec (any direction)",
                    phase="duplicate_guard",
                    reason_code="REJECTED_DUPLICATE_MARKET",
                    adjusted_size=adjusted_size,
                )
                db.commit()
                return None

            # --- Per-market position cap: max 1 open position per event per mode ---
            _existing_open = (
                db.query(Trade)
                .filter(
                    Trade.market_ticker == market_ticker,
                    Trade.settled == False,  # noqa: E712
                    Trade.trading_mode == mode,
                    Trade.strategy != strategy_name,
                )
                .first()
            )
            if _existing_open is not None:
                logger.warning(
                    f"[{strategy_name}] Position cap blocked: already have open position "
                    f"on {market_ticker} (trade #{_existing_open.id})"
                )
                attempt_recorder.record_rejected(
                    f"Position cap: already have open position on {market_ticker}",
                    phase="position_cap",
                    reason_code="REJECTED_POSITION_CAP",
                    adjusted_size=adjusted_size,
                )
                db.commit()
                return None

            clob_order_id = None
            fill_price = entry_price
            filled_size = None
            AlertManager(db)

            if mode == "paper":
                simulator = get_simulator()
                orderbook_depth_usd = _fetch_orderbook_depth(token_id)
                simulation_result = simulator.simulate_fill(
                    entry_price=entry_price,
                    size=adjusted_size,
                    direction=direction,
                    market_ticker=market_ticker,
                    orderbook_depth_usd=orderbook_depth_usd,
                    db=db,
                )

                if simulation_result["rejected"]:
                    logger.warning(
                        f"[PAPER][{strategy_name}] Trade rejected: {simulation_result['rejection_reason']} "
                        f"for {market_ticker} {direction} ${adjusted_size:.2f}"
                    )
                    attempt_recorder.record_rejected(
                        f"Paper trade rejected: {simulation_result['rejection_reason']}",
                        phase="execution",
                        reason_code="REJECTED_LIQUIDITY",
                        adjusted_size=adjusted_size,
                    )
                    db.commit()
                    return None

                fill_price = simulation_result["fill_price"]
                if simulation_result["slippage_bps"] > 0:
                    logger.info(
                        f"[PAPER][{strategy_name}] Slippage: {simulation_result['slippage_bps']:.1f}bps, "
                        f"Fee: ${simulation_result['fee_usd']:.2f}, "
                        f"Fill: {fill_price:.4f} (was {entry_price:.4f})"
                    )

            is_kalshi = market_ticker.startswith("KX") or platform == "kalshi"

            # Warn when live/testnet mode but token_id is missing — silently broken strategies
            if mode in ("testnet", "live") and not is_kalshi and not token_id:
                logger.warning(
                    f"[{mode.upper()}][{strategy_name}] No token_id for {market_ticker} — "
                    f"CLOB order will be skipped; strategy may be producing incomplete decisions"
                )
                attempt_recorder.record_blocked(
                    "No token_id for CLOB order",
                    phase="execution",
                    reason_code="BLOCKED_MISSING_TOKEN_ID",
                    adjusted_size=adjusted_size,
                )
                db.commit()
                return None

            if is_kalshi and mode in ("testnet", "live"):
                try:
                    from backend.markets.provider_registry import market_registry

                    _client = market_registry.get("kalshi")
                    logger.info(
                        f"[{mode.upper()}][{strategy_name}] Kalshi order via registry for {market_ticker}"
                    )
                except Exception as kalshi_err:
                    logger.warning(
                        f"[strategy_executor] Kalshi registry lookup failed for {market_ticker}: {kalshi_err}"
                        f" — falling back to legacy client"
                    )
                    try:
                        from backend.data.kalshi_client import KalshiClient

                        _client = KalshiClient()
                    except Exception as legacy_err:
                        logger.error(
                            f"[strategy_executor] Kalshi execution error: {legacy_err}"
                        )
                        attempt_recorder.record_failed(
                            f"Kalshi execution error: {legacy_err}",
                            phase="execution",
                            adjusted_size=adjusted_size,
                        )
                        db.commit()
                        return None
                clob_order_id = None
                fill_price = entry_price

            market_end_date = None
            if market_end_date_str:
                try:
                    market_end_date = datetime.fromisoformat(
                        market_end_date_str.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    logger.exception(
                        "[strategy_executor] failed to parse market_end_date for trade recording"
                    )

            slippage = (
                abs(fill_price - entry_price) / entry_price if entry_price > 0 else 0.0
            )
            fee = None

            if mode == "paper":
                if (
                    "simulation_result" in dir()
                    and simulation_result
                    and not simulation_result.get("rejected", True)
                ):
                    fee = simulation_result.get("fee_usd", 0.0)

            from backend.core.trade_forensics import classify_trade_role_sync

            role, maker_size, taker_size = classify_trade_role_sync(
                platform=platform,
                mode=mode,
                clob_order_id=clob_order_id,
                price=fill_price,
                size=adjusted_size,
                direction=direction,
                decision=decision,
                db_session=db,
            )

            trade_data = {
                "market_ticker": market_ticker,
                "platform": platform,
                "direction": direction,
                "entry_price": fill_price,
                "size": adjusted_size,
                "model_probability": model_probability,
                "market_price_at_entry": entry_price,
                "edge_at_entry": edge,
                "trading_mode": mode,
                "confidence": confidence,
                "result": "pending",
            }

            try:
                TradeValidator.validate_trade_data(trade_data)
            except ValidationError as e:
                log_validation_error(e, context=f"execute_decision:{strategy_name}")
                logger.error(f"[{strategy_name}] Trade validation failed: {e.message}")
                attempt_recorder.record_rejected(
                    f"Trade validation failed: {e.message}",
                    phase="validation",
                    reason_code="REJECTED_TRADE_VALIDATION",
                    adjusted_size=adjusted_size,
                )
                db.commit()
                return None

            trade = Trade(
                market_ticker=market_ticker,
                platform=platform,
                direction=direction,
                entry_price=fill_price,
                size=adjusted_size,
                model_probability=model_probability,
                market_price_at_entry=entry_price,
                edge_at_entry=edge,
                trading_mode=mode,
                strategy=strategy_name,
                confidence=confidence,
                clob_order_id=clob_order_id,
                filled_size=filled_size,
                fee=fee,
                slippage=slippage,
                market_type=market_type,
                market_end_date=market_end_date,
                token_id=token_id,
                condition_id=decision.get("condition_id") or decision.get("slug"),
                role=role,
                maker_size=maker_size,
                taker_size=taker_size,
            )

            db.add(trade)
            db.flush()

            from backend.models.audit_logger import log_trade_created

            log_trade_created(
                db=db,
                trade_id=trade.id,
                trade_data={
                    "market_ticker": market_ticker,
                    "direction": direction,
                    "entry_price": fill_price,
                    "size": adjusted_size,
                    "trading_mode": mode,
                    "strategy": strategy_name,
                    "confidence": confidence,
                    "edge": edge,
                    "clob_order_id": clob_order_id,
                },
                user_id=f"strategy:{strategy_name}",
            )

            # Serialize the short BotState mutation in-process, but rely on a
            # single atomic SQL UPDATE instead of a SELECT ... FOR UPDATE row lock.
            with _botstate_threading_lock:
                _update_botstate_after_trade(db, mode, adjusted_size)
                db.commit()

            signal_data = {
                "direction": direction,
                "model_probability": model_probability,
                "market_price": entry_price,
                "edge": edge,
                "confidence": confidence,
                "kelly_fraction": 0.0,
                "suggested_size": adjusted_size,
            }

            try:
                SignalValidator.validate_signal_data(signal_data)
            except ValidationError as e:
                log_validation_error(
                    e, context=f"execute_decision:signal:{strategy_name}"
                )
                logger.error(f"[{strategy_name}] Signal validation failed: {e.message}")
                attempt_recorder.record_rejected(
                    f"Signal validation failed: {e.message}",
                    phase="validation",
                    reason_code="REJECTED_SIGNAL_VALIDATION",
                    trade_id=trade.id,
                    adjusted_size=adjusted_size,
                )
                db.commit()
                return None

            signal_record = Signal(
                market_ticker=market_ticker,
                platform=platform,
                direction=direction,
                model_probability=model_probability,
                market_price=entry_price,
                edge=edge,
                confidence=confidence,
                kelly_fraction=0.0,
                suggested_size=adjusted_size,
                reasoning=reasoning,
                track_name=strategy_name,
                execution_mode=mode,
                token_id=token_id,
                executed=True,
            )
            db.add(signal_record)
            db.flush()
            trade.signal_id = signal_record.id
            attempt_recorder.record_executed(
                trade.id,
                adjusted_size=adjusted_size,
                order_id=clob_order_id,
                risk_allowed=True,
                risk_reason=risk.reason,
            )

            _commit_with_retry(db)

            trade_dict = {
                "id": trade.id,
                "market_ticker": market_ticker,
                "direction": direction,
                "fill_price": fill_price,
                "size": adjusted_size,
                "edge": edge,
                "confidence": confidence,
                "trading_mode": mode,
                "clob_order_id": clob_order_id,
                "strategy": strategy_name,
            }

            try:
                _broadcast_event(
                    "trade_opened",
                    {
                        **trade_dict,
                        "trade_id": trade.id,
                        "entry_price": fill_price,
                        "mode": mode,
                    },
                )
            except Exception as e:
                logger.opt(exception=True).warning(
                    f"[strategy_executor.execute_decision] {type(e).__name__}: event broadcast failed (non-fatal): {e}",
                )

            try:
                from backend.core.event_bus import publish_event

                publish_event(
                    "trade_executed",
                    {
                        "trade_id": trade.id,
                        "market_ticker": market_ticker,
                        "direction": direction,
                        "fill_price": fill_price,
                        "size": adjusted_size,
                        "confidence": confidence,
                        "edge": edge,
                        "strategy_name": strategy_name,
                        "genome_id": decision.get("genome_id"),
                        "trading_mode": mode,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception as e:
                logger.warning(
                    f"[strategy_executor.execute_decision] publish_event trade_executed failed (non-fatal): {e}"
                )

            logger.info(
                f"[{strategy_name}] Trade created: {direction.upper()} {market_ticker} "
                f"${adjusted_size:.2f} @ {fill_price:.3f} (mode={mode})"
            )
            return trade_dict

        except OperationalError as exc:
            logger.opt(exception=True).error(
                f"[strategy_executor.execute_decision] OperationalError: execute_decision failed for {market_ticker}: {exc}",
            )
            try:
                db.rollback()
            except Exception as e:
                logger.opt(exception=True).warning(
                    f"[strategy_executor.execute_decision] {type(e).__name__}: db.rollback failed after OperationalError (non-fatal): {e}",
                )
            if _is_lock_timeout_error(exc):
                raise _BotStateLockRetry(str(exc)) from exc
            return None
        except Exception as exc:
            logger.exception(
                f"[strategy_executor.execute_decision] {type(exc).__name__}: execute_decision failed for {market_ticker}: {exc}"
            )
            try:
                db.rollback()
            except Exception as e:
                logger.opt(exception=True).warning(
                    f"[strategy_executor.execute_decision] {type(e).__name__}: db.rollback failed (non-fatal): {e}",
                )
            if attempt_recorder is not None:
                _record_unexpected_attempt_failure(
                    db,
                    decision,
                    strategy_name,
                    mode,
                    f"Unexpected execution error: {type(exc).__name__}: {exc}",
                    attempt_id=getattr(attempt_recorder.attempt, "attempt_id", None),
                )
            return None


async def execute_decision(
    decision: dict, strategy_name: str, mode: str, db=None
) -> Optional[dict]:
    """Execute a single trade decision.

    Acquires async coordination locks on the event loop, then offloads
    synchronous DB-heavy work to a thread pool to avoid blocking the
    event loop. Paper/testnet/Kalshi paths run entirely in the thread.
    Live CLOB paths acquire locks on event loop then call CLOB async.
    """
    asset_key = decision.get("condition_id") or decision.get("slug") or strategy_name
    market_id = str(asset_key)

    # Rate limit check: smoothly wait for tokens instead of skipping
    await _get_rate_limiter().wait_and_acquire(market_id)

    asset_lock = await _get_asset_lock(str(asset_key))
    async with _trade_semaphore:
        async with asset_lock:
            # Paper/testnet/Kalshi: no async CLOB calls — offload entirely to thread
            is_live_clob = (
                mode == "live"
                and not (
                    decision.get("market_ticker", "").startswith("KX")
                    or decision.get("platform") == "kalshi"
                )
                and decision.get("token_id") is not None
            )
            if mode == "live" and not is_live_clob and not decision.get("token_id"):
                logger.warning(
                    f"[{strategy_name}] Live mode but no token_id in decision for "
                    f"{decision.get('market_ticker', '?')} — falling back to paper path"
                )
            for lock_attempt in range(_MAX_LOCK_RETRY_ATTEMPTS):
                try:
                    if not is_live_clob:
                        if db is not None:
                            # db was provided (e.g. in tests) — run synchronously to
                            # avoid crossing thread boundaries with a caller-owned session
                            return _execute_decision_paper_or_kalshi(
                                decision,
                                strategy_name,
                                mode,
                                db,
                            )
                        return await asyncio.to_thread(
                            _execute_decision_paper_or_kalshi,
                            decision,
                            strategy_name,
                            mode,
                        )

                    # Live mode with CLOB: must stay on event loop for async HTTP calls
                    # but still wrap DB ops where possible
                    return await _execute_decision_live_clob(
                        decision,
                        strategy_name,
                        mode,
                        db,
                    )
                except _BotStateLockRetry:
                    if lock_attempt >= _MAX_LOCK_RETRY_ATTEMPTS - 1:
                        logger.opt(exception=True).error(
                            "[strategy_executor.execute_decision] BotState lock contention persisted after {} attempts for {}",
                            _MAX_LOCK_RETRY_ATTEMPTS,
                            decision.get("market_ticker", ""),
                        )
                        return None

                    delay = _lock_retry_delay(lock_attempt)
                    logger.warning(
                        "[strategy_executor.execute_decision] BotState lock contention for {}; retrying in {:.2f}s (attempt {}/{})",
                        decision.get("market_ticker", ""),
                        delay,
                        lock_attempt + 1,
                        _MAX_LOCK_RETRY_ATTEMPTS,
                    )
                    await asyncio.sleep(delay)


# Maker-first execution config (overridable via settings).
MAKER_WAIT_SECONDS = float(getattr(settings, "MAKER_WAIT_SECONDS", 5.0))
MAKER_POLL_INTERVAL_SECONDS = float(
    getattr(settings, "MAKER_POLL_INTERVAL_SECONDS", 2.0)
)
MAKER_FIRST_ENABLED = bool(getattr(settings, "MAKER_FIRST_ENABLED", True))


async def _maker_first_execute(
    clob,
    token_id: str,
    side: str,
    price: float,
    size: float,
    strategy_name: str,
    mode: str,
    market_ticker: str,
    force_maker_only: bool = False,
):
    """Execute an order maker-first with taker escalation.

    Workflow:
      1. Place maker (GTC limit) order at `price`.
      2. Poll `get_open_orders` up to MAKER_WAIT_SECONDS; if order is no
         longer in the open-orders set, treat as filled.
      3. If still open after the wait, cancel and submit the remaining size
         as a taker (IOC) order crossing the spread.

    Returns the *terminal* OrderResult-like object that callers should treat
    as the final fill (with attributes `success`, `order_id`, `fill_price`,
    `fill_size`, `error`). When taker escalation runs, fill_size is the
    cumulative amount filled across both legs.
    """
    from types import SimpleNamespace

    maker_result = await clob.place_limit_order(
        token_id=token_id,
        side=side,
        price=price,
        size=size,
        order_type="GTC",
    )
    if not maker_result.success:
        logger.warning(
            f"[{mode.upper()}][{strategy_name}] Maker order rejected for {market_ticker}: "
            f"{maker_result.error}"
        )
        return maker_result

    maker_filled = float(getattr(maker_result, "fill_size", 0.0) or 0.0)
    maker_fill_price = getattr(maker_result, "fill_price", None) or price
    maker_order_id = maker_result.order_id

    if maker_filled >= size - 1e-9:
        logger.info(
            f"[{mode.upper()}][{strategy_name}] Maker order fully filled on placement: "
            f"{maker_order_id} ({maker_filled:.4f}@{maker_fill_price:.4f})"
        )
        return SimpleNamespace(
            success=True,
            order_id=maker_order_id,
            fill_price=maker_fill_price,
            fill_size=maker_filled,
            maker_filled=False,
            maker_size=0.0,
            taker_size=maker_filled,
            error=None,
        )

    logger.info(
        f"[{mode.upper()}][{strategy_name}] Maker order resting ({maker_order_id}); "
        f"waiting up to {MAKER_WAIT_SECONDS:.1f}s for fill"
    )

    waited = 0.0
    while waited < MAKER_WAIT_SECONDS:
        await asyncio.sleep(MAKER_POLL_INTERVAL_SECONDS)
        waited += MAKER_POLL_INTERVAL_SECONDS
        try:
            open_orders = await clob.get_open_orders()
        except Exception as poll_err:
            logger.warning(
                f"[{mode.upper()}][{strategy_name}] get_open_orders failed during maker wait: {poll_err}"
            )
            continue
        still_open = any(
            (o.get("id") or o.get("orderID") or o.get("order_id")) == maker_order_id
            for o in (open_orders or [])
        )
        if not still_open:
            logger.info(
                f"[{mode.upper()}][{strategy_name}] Maker order {maker_order_id} no longer open — treating as filled"
            )
            m_size = size - maker_filled
            return SimpleNamespace(
                success=True,
                order_id=maker_order_id,
                fill_price=maker_fill_price,
                fill_size=size,
                maker_filled=m_size > 0,
                maker_size=m_size,
                taker_size=maker_filled,
                error=None,
            )

    logger.warning(
        f"[{mode.upper()}][{strategy_name}] Maker order {maker_order_id} unfilled after "
        f"{MAKER_WAIT_SECONDS:.1f}s; cancelling and escalating to taker"
    )
    try:
        cancelled = await clob.cancel_order(maker_order_id)
        logger.info(
            f"[{mode.upper()}][{strategy_name}] Cancel maker {maker_order_id}: success={cancelled}"
        )
    except Exception as cancel_err:
        logger.error(
            f"[{mode.upper()}][{strategy_name}] Cancel of maker {maker_order_id} failed: {cancel_err}"
        )

    if force_maker_only:
        logger.warning(
            f"[{mode.upper()}][{strategy_name}] force_maker_only is enabled; skipping taker escalation."
        )
        return SimpleNamespace(
            success=maker_filled > 0,
            order_id=maker_order_id,
            fill_price=maker_fill_price,
            fill_size=maker_filled,
            maker_filled=maker_filled > 0,
            maker_size=maker_filled,
            taker_size=0.0,
            error="force_maker_only GTC timeout" if maker_filled == 0 else None,
        )

    remaining = size - maker_filled
    if remaining <= 0:
        return maker_result

    # Cross the spread for taker IOC: BUY at price+1 tick, SELL at price-1 tick (capped to [0.01, 0.99]).
    tick = 0.01
    if side.upper() == "BUY":
        taker_price = min(0.99, price + tick)
    else:
        taker_price = max(0.01, price - tick)

    logger.info(
        f"[{mode.upper()}][{strategy_name}] Escalating to taker IOC: "
        f"size={remaining:.4f} @ {taker_price:.4f}"
    )
    taker_result = await clob.place_limit_order(
        token_id=token_id,
        side=side,
        price=taker_price,
        size=remaining,
        order_type="FAK",  # Fill-and-Kill (IOC) — taker
    )
    if not taker_result.success:
        logger.error(
            f"[{mode.upper()}][{strategy_name}] Taker escalation rejected: {taker_result.error}"
        )
        # Preserve any maker-leg fill in the returned error result.
        if maker_filled > 0:
            return SimpleNamespace(
                success=True,
                order_id=maker_order_id,
                fill_price=maker_fill_price,
                fill_size=maker_filled,
                maker_filled=False,
                maker_size=0.0,
                taker_size=maker_filled,
                error=f"Taker escalation rejected: {taker_result.error}",
            )
        return taker_result

    taker_filled = float(getattr(taker_result, "fill_size", 0.0) or 0.0)
    taker_fill_price = getattr(taker_result, "fill_price", None) or taker_price
    total_filled = maker_filled + taker_filled

    if total_filled > 0:
        avg_price = (
            (maker_fill_price * maker_filled) + (taker_fill_price * taker_filled)
        ) / total_filled
    else:
        avg_price = maker_fill_price

    return SimpleNamespace(
        success=True,
        order_id=taker_result.order_id or maker_order_id,
        fill_price=avg_price,
        fill_size=total_filled,
        maker_filled=False,
        maker_size=0.0,
        taker_size=total_filled,
        error=None,
    )


async def _execute_decision_live_clob(
    decision: dict, strategy_name: str, mode: str, db=None
) -> Optional[dict]:
    """Live CLOB execution path — stays on event loop for async HTTP calls."""
    market_ticker = decision.get("market_ticker", "")
    direction = decision.get("direction", "")
    size = float(decision.get("size", 0.0))
    entry_price = float(decision.get("entry_price", 0.5))
    edge = float(decision.get("edge", 0.0))
    confidence = float(decision.get("confidence", 0.0))
    model_probability = float(decision.get("model_probability", confidence))
    token_id = decision.get("token_id")
    platform = decision.get("platform", "polymarket")
    reasoning = decision.get("reasoning", "")
    market_type = decision.get("market_type", "btc")
    market_end_date_str = decision.get("market_end_date")

    from backend.db.utils import get_db_session
    from contextlib import nullcontext

    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)
    with ctx as db:
        attempt_recorder = None
        try:
            attempt_recorder = TradeAttemptRecorder(db, decision, strategy_name, mode)

            try:
                context = get_context(mode)
            except KeyError:
                logger.error(f"[{strategy_name}] No execution context for mode: {mode}")
                attempt_recorder.record_blocked(
                    f"No execution context for mode: {mode}",
                    phase="context",
                    reason_code="BLOCKED_NO_EXECUTION_CONTEXT",
                )
                db.commit()
                return None

            event_slug = decision.get("slug") or decision.get("event_slug")
            filters = [
                Trade.settled.is_(False),
                Trade.trading_mode == mode,
            ]
            if event_slug:
                filters.append(
                    and_(
                        Trade.market_ticker == market_ticker,
                        Trade.event_slug == event_slug,
                    )
                )
            else:
                filters.append(Trade.market_ticker == market_ticker)
            existing = db.query(Trade).filter(*filters, Trade.strategy != strategy_name).first()
            if existing:
                logger.info(
                    f"[{strategy_name}] Duplicate execution blocked for {market_ticker}/{event_slug}"
                )
                attempt_recorder.record_blocked(
                    "Duplicate open position for market",
                    phase="preflight",
                    reason_code="BLOCKED_DUPLICATE_OPEN_POSITION",
                    trade_id=existing.id,
                )
                db.commit()
                return None

            state = db.query(BotState).filter_by(mode=mode).first()
            if not state or not state.is_running:
                logger.info(
                    f"[{strategy_name}] Bot not running, skipping decision for {market_ticker}"
                )

                strategy_config = (
                    db.query(StrategyConfig)
                    .filter_by(strategy_name=strategy_name)
                    .first()
                )
                if not strategy_config or not strategy_config.enabled:
                    logger.warning(
                        f"[{strategy_name}] Skipping execution as strategy is disabled or missing in config"
                    )
                    attempt_recorder.record_blocked(
                        "Strategy disabled or missing",
                        phase="preflight",
                        reason_code="BLOCKED_STRATEGY_DISABLED",
                    )
                    db.commit()
                    return None
                attempt_recorder.record_blocked(
                    "Bot not running for selected mode",
                    phase="preflight",
                    reason_code="BLOCKED_BOT_NOT_RUNNING",
                )
                db.commit()
                return None

            # --- G-16: Cooldown after consecutive losses (live CLOB path) ---
            cooldown_losses = int(_cfg("COOLDOWN_CONSECUTIVE_LOSSES", 3) or 3)
            cooldown_minutes = int(_cfg("COOLDOWN_MINUTES", 60) or 60)
            if cooldown_losses > 0:
                from datetime import timedelta as _td

                recent_trades = (
                    db.query(Trade)
                    .filter(
                        Trade.strategy == strategy_name,
                        Trade.settled.is_(True),
                        Trade.trading_mode == mode,
                    )
                    .order_by(Trade.settlement_time.desc())
                    .limit(cooldown_losses)
                    .all()
                )
                if len(recent_trades) >= cooldown_losses:
                    all_losses = all(t.result == "loss" for t in recent_trades)
                    if all_losses:
                        last_loss_time = recent_trades[0].settlement_time
                        if last_loss_time and last_loss_time.tzinfo is None:
                            last_loss_time = last_loss_time.replace(tzinfo=timezone.utc)
                        cooldown_until = last_loss_time + _td(minutes=cooldown_minutes)
                        now_utc = datetime.now(timezone.utc)
                        if now_utc < cooldown_until:
                            remaining = (
                                cooldown_until - now_utc
                            ).total_seconds() / 60.0
                            logger.info(
                                f"[{strategy_name}] Cooldown active: {cooldown_losses} consecutive losses, "
                                f"pausing for {remaining:.1f} more minutes"
                            )
                            attempt_recorder.record_blocked(
                                f"Cooldown: {cooldown_losses} consecutive losses, {remaining:.1f}min remaining",
                                phase="cooldown",
                                reason_code="BLOCKED_COOLDOWN",
                            )
                            db.commit()
                            return None

            if mode == "paper":
                bankroll = (
                    state.paper_bankroll if state.paper_bankroll is not None else 0.0
                )
            elif mode == "testnet":
                bankroll = (
                    state.testnet_bankroll
                    if state.testnet_bankroll is not None
                    else 0.0
                )
            else:
                bankroll = (
                    state.bankroll
                    if state.bankroll is not None
                    else _cfg("INITIAL_BANKROLL", 1000.0)
                )

            # Skip async bankroll reconciliation in this path —
            # floor negative bankroll to $0 to avoid blocking event loop
            if bankroll < 0:
                logger.warning(
                    "[%s] Negative bankroll ($%.2f) detected; flooring to $0.00",
                    mode.upper(),
                    bankroll,
                )
                bankroll = 0.0

            # --- Hard safety guards: per-trade max loss, daily cap, portfolio breaker ---
            safety_block = _pre_trade_safety_checks(db, strategy_name, mode, bankroll, size)
            if safety_block is not None:
                logger.warning(f"[{strategy_name}] Safety guard blocked: {safety_block}")
                attempt_recorder.record_blocked(
                    safety_block,
                    phase="safety_guard",
                    reason_code="BLOCKED_SAFETY_GUARD",
                )
                db.commit()
                return None

            current_exposure = _get_current_exposure(db, trading_mode=mode)
            attempt_recorder.update(
                phase="risk_gate",
                status="RISK_EVALUATING",
                reason_code="RISK_EVALUATING",
                reason="Risk manager evaluating trade",
                bankroll=bankroll,
                current_exposure=current_exposure,
                factors_json={
                    "bankroll": bankroll,
                    "current_exposure": current_exposure,
                    "requested_size": size,
                    "confidence": confidence,
                    "market_ticker": market_ticker,
                    "mode": mode,
                },
            )

            risk = context.risk_manager.validate_trade(
                size=size,
                current_exposure=current_exposure,
                bankroll=bankroll,
                confidence=confidence,
                market_ticker=market_ticker,
                db=db,
                mode=mode,
                strategy_name=strategy_name,
                direction=direction if direction else None,
            )
            if not risk.allowed:
                logger.info(
                    f"[{strategy_name}] Risk rejected {market_ticker}: {risk.reason}"
                )
                attempt_recorder.record_rejected(
                    risk.reason,
                    phase="risk_gate",
                    risk_allowed=False,
                    risk_reason=risk.reason,
                    adjusted_size=risk.adjusted_size,
                )
                db.commit()
                return None

            adjusted_size = risk.adjusted_size
            attempt_recorder.update(
                status="RISK_APPROVED",
                phase="risk_gate",
                reason_code="RISK_APPROVED",
                reason="Risk gate approved trade",
                risk_allowed=True,
                risk_reason=risk.reason,
                adjusted_size=adjusted_size,
            )

            min_size = _cfg("MIN_ORDER_USDC", 5.0)
            if adjusted_size < min_size:
                logger.info(
                    f"[{mode.upper()}][{strategy_name}] Order rejected for {market_ticker}: "
                    f"Size ${adjusted_size:.2f} below minimum ${min_size}"
                )
                attempt_recorder.record_rejected(
                    f"Size ${adjusted_size:.2f} below minimum ${min_size:.2f}",
                    phase="sizing",
                    reason_code="REJECTED_ORDER_TOO_SMALL",
                    adjusted_size=adjusted_size,
                )
                db.commit()
                return None

            # --- Stale-market filter: dynamic threshold based on market lifetime ---
            from datetime import timedelta

            market_end_date = None
            if market_end_date_str:
                try:
                    market_end_date = datetime.fromisoformat(
                        market_end_date_str.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    logger.exception(
                        f"[{strategy_name}] failed to parse market_end_date for stale check: {market_ticker}"
                    )
            if market_end_date is not None:
                _now = datetime.now(timezone.utc)
                _time_to_resolution = (market_end_date - _now).total_seconds() / 60.0
                # Dynamic threshold: 2 min for short-lived (5m/15m) markets, 60 min otherwise
                _is_short_lived = "-5m-" in str(market_ticker) or "-15m-" in str(
                    market_ticker
                )
                _stale_threshold = 2.0 if _is_short_lived else 60.0
                if _time_to_resolution < _stale_threshold:
                    logger.info(
                        f"[{strategy_name}] Stale market blocked: {market_ticker} resolves in "
                        f"{_time_to_resolution:.1f} min (< {_stale_threshold:.0f} min threshold)"
                    )
                    attempt_recorder.record_rejected(
                        f"Stale market: {market_ticker} resolves in {_time_to_resolution:.1f} min",
                        phase="stale_market",
                        reason_code="REJECTED_STALE_MARKET",
                        adjusted_size=adjusted_size,
                    )
                    db.commit()
                    return None

            # --- Duplicate market guard: block if same strategy+ticker traded recently (same mode only) ---
            _cooldown_sec = _cfg("DUPLICATE_TRADE_COOLDOWN_SEC", 60)
            _cutoff = datetime.now(timezone.utc) - timedelta(seconds=_cooldown_sec)
            _dup_query = (
                db.query(Trade)
                .filter(
                    Trade.strategy == strategy_name,
                    Trade.market_ticker == market_ticker,
                    Trade.timestamp >= _cutoff,
                )
            )
            if mode:
                _dup_query = _dup_query.filter(Trade.trading_mode == mode)
            _recent_dup = _dup_query.first()
            if _recent_dup is not None:
                logger.warning(
                    f"[{strategy_name}] Duplicate blocked: already traded {market_ticker} "
                    f"(any direction) within {_cooldown_sec} sec (trade #{_recent_dup.id})"
                )
                attempt_recorder.record_rejected(
                    f"Duplicate: {market_ticker} already traded in last {_cooldown_sec} sec (any direction)",
                    phase="duplicate_guard",
                    reason_code="REJECTED_DUPLICATE_MARKET",
                    adjusted_size=adjusted_size,
                )
                db.commit()
                return None

            # --- Per-market position cap: max 1 open position per event per mode ---
            _existing_open = (
                db.query(Trade)
                .filter(
                    Trade.market_ticker == market_ticker,
                    Trade.settled == False,  # noqa: E712
                    Trade.trading_mode == mode,
                    Trade.strategy != strategy_name,
                )
                .first()
            )
            if _existing_open is not None:
                logger.warning(
                    f"[{strategy_name}] Position cap blocked: already have open position "
                    f"on {market_ticker} (trade #{_existing_open.id})"
                )
                attempt_recorder.record_rejected(
                    f"Position cap: already have open position on {market_ticker}",
                    phase="position_cap",
                    reason_code="REJECTED_POSITION_CAP",
                    adjusted_size=adjusted_size,
                )
                db.commit()
                return None

            clob_order_id = None
            fill_price = entry_price
            filled_size = None
            alert_manager = AlertManager(db)
            role = "unknown"
            maker_size = None
            taker_size = None

            if mode == "paper":
                simulator = get_simulator()
                orderbook_depth_usd = _fetch_orderbook_depth(token_id)
                simulation_result = simulator.simulate_fill(
                    entry_price=entry_price,
                    size=adjusted_size,
                    direction=direction,
                    market_ticker=market_ticker,
                    orderbook_depth_usd=orderbook_depth_usd,
                    db=db,
                )

                if simulation_result["rejected"]:
                    logger.warning(
                        f"[PAPER][{strategy_name}] Trade rejected: {simulation_result['rejection_reason']} "
                        f"for {market_ticker} {direction} ${adjusted_size:.2f}"
                    )
                    attempt_recorder.record_rejected(
                        f"Paper trade rejected: {simulation_result['rejection_reason']}",
                        phase="execution",
                        reason_code="REJECTED_LIQUIDITY",
                        adjusted_size=adjusted_size,
                    )
                    db.commit()
                    return None

                fill_price = simulation_result["fill_price"]
                if simulation_result["slippage_bps"] > 0:
                    logger.info(
                        f"[PAPER][{strategy_name}] Slippage: {simulation_result['slippage_bps']:.1f}bps, "
                        f"Fee: ${simulation_result['fee_usd']:.2f}, "
                        f"Fill: {fill_price:.4f} (was {entry_price:.4f})"
                    )

            if mode in ("testnet", "live") and token_id:
                from backend.core.strategy_gate import StrategyGate

                gate = StrategyGate.can_execute_live(strategy_name, db)
                if not gate[0]:
                    logger.warning(
                        f"[GATE][{strategy_name}] Blocked live order: {gate[1]}"
                    )
                    attempt_recorder.record_rejected(
                        f"Strategy gate blocked: {gate[1]}",
                        phase="gate",
                        reason_code="BLOCKED_STRATEGY_GATE",
                        adjusted_size=adjusted_size,
                    )
                    db.commit()
                    return None
                force_maker_only = False
                cfg = db.query(StrategyConfig).filter_by(strategy_name=strategy_name).first()
                if cfg and cfg.params:
                    try:
                        params = _json.loads(cfg.params) if isinstance(cfg.params, str) else cfg.params
                        if params.get("force_maker_only") or params.get("maker_only"):
                            force_maker_only = True
                    except Exception:
                        logger.warning("strategy_executor: failed to parse strategy params JSON")

                for clob_attempt in range(2):
                    try:
                        async with context.clob_client as clob:
                            await clob.create_or_derive_api_key()
                            if MAKER_FIRST_ENABLED or force_maker_only:
                                result = await _maker_first_execute(
                                    clob,
                                    token_id=token_id,
                                    side="BUY",
                                    price=entry_price,
                                    size=adjusted_size,
                                    strategy_name=strategy_name,
                                    mode=mode,
                                    market_ticker=market_ticker,
                                    force_maker_only=force_maker_only,
                                )
                            else:
                                result = await clob.place_limit_order(
                                    token_id=token_id,
                                    side="BUY",
                                    price=entry_price,
                                    size=adjusted_size,
                                )
                        if result.success:
                            clob_order_id = result.order_id
                            fill_price = result.fill_price or fill_price
                            if (
                                hasattr(result, "filled_size")
                                and result.filled_size is not None
                            ):
                                filled_size = result.fill_size

                            from backend.core.trade_forensics import classify_trade_role

                            best_ask = None
                            best_bid = None
                            try:
                                book = await clob.get_order_book(token_id)
                                if book:
                                    best_ask = book.best_ask
                                    best_bid = book.best_bid
                            except Exception:
                                logger.warning("strategy_executor: get_order_book failed")

                            execution_decision = dict(decision)
                            if best_ask is not None:
                                execution_decision["best_ask"] = best_ask
                            if best_bid is not None:
                                execution_decision["best_bid"] = best_bid

                            base_size = filled_size if (filled_size is not None and filled_size > 0) else adjusted_size

                            role, maker_size, taker_size = await classify_trade_role(
                                platform=platform,
                                mode=mode,
                                clob_order_id=clob_order_id,
                                price=fill_price,
                                size=base_size,
                                direction=direction,
                                decision=execution_decision,
                                db_session=db,
                            )

                            logger.info(
                                f"[{mode.upper()}][{strategy_name}] Order placed: {clob_order_id}"
                            )
                            break
                        err_msg = result.error or "CLOB order rejected"
                        logger.warning(
                            f"[{mode.upper()}][{strategy_name}] Order rejected for {market_ticker}: {err_msg}"
                        )
                        if (
                            clob_attempt == 0
                            and "order_version_mismatch" in err_msg.lower()
                        ):
                            try:
                                fresh_mid = await context.clob_client.get_mid_price(
                                    token_id
                                )
                                entry_price = fresh_mid
                                logger.warning(
                                    f"[{mode.upper()}][{strategy_name}] Retrying with refreshed mid price {entry_price:.4f}"
                                )
                                continue
                            except Exception:
                                logger.exception(
                                    "Failed to refresh mid price"
                                )
                        attempt_recorder.record_rejected(
                            err_msg,
                            phase="execution",
                            reason_code="REJECTED_BROKER_ORDER",
                            adjusted_size=adjusted_size,
                            order_id=getattr(result, "order_id", None),
                        )
                        db.commit()
                        return None
                    except Exception as clob_err:
                        err_str = f"{type(clob_err).__name__}: {clob_err}"
                        logger.opt(exception=True).error(
                            f"[strategy_executor.execute_decision] {err_str} for {market_ticker}"
                        )
                        if (
                            clob_attempt == 0
                            and "order_version_mismatch" in str(clob_err).lower()
                        ):
                            try:
                                fresh_mid = await context.clob_client.get_mid_price(
                                    token_id
                                )
                                entry_price = fresh_mid
                                logger.warning(
                                    f"[{mode.upper()}][{strategy_name}] Retrying after exception with refreshed mid price {entry_price:.4f}"
                                )
                                continue
                            except Exception as refresh_err:
                                logger.warning(
                                    f"Failed to refresh mid price: {refresh_err}"
                                )
                        attempt_recorder.record_failed(
                            f"CLOB execution error: {err_str}",
                            phase="execution",
                            adjusted_size=adjusted_size,
                        )
                        db.commit()
                        return None
                if clob_order_id is None:
                    return None
                alert_manager.check_high_slippage(
                    trade_id=0,
                    expected_price=entry_price,
                    actual_price=fill_price,
                    position_value=adjusted_size,
                    mode=mode,
                )
            elif mode in ("testnet", "live") and not token_id:
                logger.warning(
                    f"[{mode.upper()}][{strategy_name}] No token_id for {market_ticker}, skipping order"
                )
                attempt_recorder.record_blocked(
                    "No token_id for CLOB order",
                    phase="execution",
                    reason_code="BLOCKED_MISSING_TOKEN_ID",
                    adjusted_size=adjusted_size,
                )
                db.commit()
                return None

            market_end_date = None
            if market_end_date_str:
                try:
                    market_end_date = datetime.fromisoformat(
                        market_end_date_str.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    logger.exception(
                        "[strategy_executor] failed to parse market_end_date for trade recording"
                    )

            slippage = (
                abs(fill_price - entry_price) / entry_price if entry_price > 0 else 0.0
            )
            fee = None

            trade_data = {
                "market_ticker": market_ticker,
                "platform": platform,
                "direction": direction,
                "entry_price": fill_price,
                "size": adjusted_size,
                "model_probability": model_probability,
                "market_price_at_entry": entry_price,
                "edge_at_entry": edge,
                "trading_mode": mode,
                "confidence": confidence,
                "result": "pending",
            }

            try:
                TradeValidator.validate_trade_data(trade_data)
            except ValidationError as e:
                log_validation_error(e, context=f"execute_decision:{strategy_name}")
                logger.error(f"[{strategy_name}] Trade validation failed: {e.message}")
                attempt_recorder.record_rejected(
                    f"Trade validation failed: {e.message}",
                    phase="validation",
                    reason_code="REJECTED_TRADE_VALIDATION",
                    adjusted_size=adjusted_size,
                )
                db.commit()
                return None

            trade = Trade(
                market_ticker=market_ticker,
                platform=platform,
                direction=direction,
                entry_price=fill_price,
                size=adjusted_size,
                model_probability=model_probability,
                market_price_at_entry=entry_price,
                edge_at_entry=edge,
                trading_mode=mode,
                strategy=strategy_name,
                confidence=confidence,
                clob_order_id=clob_order_id,
                filled_size=filled_size,
                fee=fee,
                slippage=slippage,
                market_type=market_type,
                market_end_date=market_end_date,
                token_id=token_id,
                condition_id=decision.get("condition_id") or decision.get("slug"),
                role=role,
                maker_size=maker_size,
                taker_size=taker_size,
            )

            db.add(trade)
            db.flush()

            from backend.models.audit_logger import log_trade_created

            log_trade_created(
                db=db,
                trade_id=trade.id,
                trade_data={
                    "market_ticker": market_ticker,
                    "direction": direction,
                    "entry_price": fill_price,
                    "size": adjusted_size,
                    "trading_mode": mode,
                    "strategy": strategy_name,
                    "confidence": confidence,
                    "edge": edge,
                    "clob_order_id": clob_order_id,
                },
                user_id=f"strategy:{strategy_name}",
            )

            async with botstate_mutex:
                _update_botstate_after_trade(db, mode, adjusted_size)
                db.commit()

            signal_data = {
                "direction": direction,
                "model_probability": model_probability,
                "market_price": entry_price,
                "edge": edge,
                "confidence": confidence,
                "kelly_fraction": 0.0,
                "suggested_size": adjusted_size,
            }

            try:
                SignalValidator.validate_signal_data(signal_data)
            except ValidationError as e:
                log_validation_error(
                    e, context=f"execute_decision:signal:{strategy_name}"
                )
                logger.error(f"[{strategy_name}] Signal validation failed: {e.message}")
                attempt_recorder.record_rejected(
                    f"Signal validation failed: {e.message}",
                    phase="validation",
                    reason_code="REJECTED_SIGNAL_VALIDATION",
                    trade_id=trade.id,
                    adjusted_size=adjusted_size,
                )
                db.commit()
                return None

            signal_record = Signal(
                market_ticker=market_ticker,
                platform=platform,
                direction=direction,
                model_probability=model_probability,
                market_price=entry_price,
                edge=edge,
                confidence=confidence,
                kelly_fraction=0.0,
                suggested_size=adjusted_size,
                reasoning=reasoning,
                track_name=strategy_name,
                execution_mode=mode,
                token_id=token_id,
                executed=True,
            )
            db.add(signal_record)
            db.flush()
            trade.signal_id = signal_record.id
            attempt_recorder.record_executed(
                trade.id,
                adjusted_size=adjusted_size,
                order_id=clob_order_id,
                risk_allowed=True,
                risk_reason=risk.reason,
            )

            _commit_with_retry(db)

            trade_dict = {
                "id": trade.id,
                "market_ticker": market_ticker,
                "direction": direction,
                "fill_price": fill_price,
                "size": adjusted_size,
                "edge": edge,
                "confidence": confidence,
                "trading_mode": mode,
                "clob_order_id": clob_order_id,
                "strategy": strategy_name,
            }

            try:
                _broadcast_event(
                    "trade_opened",
                    {
                        **trade_dict,
                        "trade_id": trade.id,
                        "entry_price": fill_price,
                        "mode": mode,
                    },
                )
            except Exception as e:
                logger.opt(exception=True).warning(
                    f"[strategy_executor.execute_decision] {type(e).__name__}: event broadcast failed (non-fatal): {e}",
                )

            try:
                from backend.core.event_bus import publish_event

                publish_event(
                    "trade_executed",
                    {
                        "trade_id": trade.id,
                        "market_ticker": market_ticker,
                        "direction": direction,
                        "fill_price": fill_price,
                        "size": adjusted_size,
                        "confidence": confidence,
                        "edge": edge,
                        "strategy_name": strategy_name,
                        "genome_id": decision.get("genome_id"),
                        "trading_mode": mode,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception as e:
                logger.warning(
                    f"[strategy_executor.execute_decision] publish_event trade_executed failed (non-fatal): {e}"
                )

            logger.info(
                f"[{strategy_name}] Trade created: {direction.upper()} {market_ticker} "
                f"${adjusted_size:.2f} @ {fill_price:.3f} (mode={mode})"
            )
            return trade_dict

        except OperationalError as exc:
            logger.opt(exception=True).error(
                f"[strategy_executor.execute_decision] OperationalError: execute_decision failed for {market_ticker}: {exc}",
            )
            try:
                db.rollback()
            except Exception as e:
                logger.opt(exception=True).warning(
                    f"[strategy_executor.execute_decision] {type(e).__name__}: db.rollback failed after OperationalError (non-fatal): {e}",
                )
            if _is_lock_timeout_error(exc):
                raise _BotStateLockRetry(str(exc)) from exc
            return None
        except Exception as exc:
            logger.exception(
                f"[strategy_executor.execute_decision] {type(exc).__name__}: execute_decision failed for {market_ticker}: {exc}"
            )
            try:
                db.rollback()
            except Exception as e:
                logger.opt(exception=True).warning(
                    f"[strategy_executor.execute_decision] {type(e).__name__}: db.rollback failed (non-fatal): {e}",
                )
            if attempt_recorder is not None:
                _record_unexpected_attempt_failure(
                    db,
                    decision,
                    strategy_name,
                    mode,
                    f"Unexpected execution error: {type(exc).__name__}: {exc}",
                    attempt_id=getattr(attempt_recorder.attempt, "attempt_id", None),
                )
            return None


def _pre_trade_safety_checks(
    db, strategy_name: str, mode: str, bankroll: float, size: float
) -> Optional[str]:
    """Run hard safety guards before any trade executes.

    Returns None if all checks pass, or a rejection reason string.
    """
    from datetime import datetime, timedelta, timezone

    # 1. Per-trade max loss: no single trade > 5% of bankroll
    max_trade_pct = float(_cfg("PER_TRADE_MAX_LOSS_PCT", 0.05))
    if bankroll > 0 and size > bankroll * max_trade_pct:
        return (
            f"per-trade size ${size:.2f} > {max_trade_pct:.0%} of bankroll "
            f"(${bankroll * max_trade_pct:.2f})"
        )

    # 2. Daily max trades per strategy: no more than 50
    max_daily_trades = int(_cfg("MAX_DAILY_TRADES_PER_STRATEGY", 50))
    if max_daily_trades > 0:
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        daily_count = (
            db.query(func.count(Trade.id))
            .filter(
                Trade.strategy == strategy_name,
                Trade.trading_mode == mode,
                Trade.timestamp >= today_start,
            )
            .scalar()
            or 0
        )
        if daily_count >= max_daily_trades:
            return (
                f"daily trade limit reached: {daily_count}/{max_daily_trades} "
                f"trades today for {strategy_name}"
            )

    # 3. Portfolio circuit breaker: if total portfolio down > 20% from peak, disable ALL
    max_portfolio_dd = float(_cfg("PORTFOLIO_CIRCUIT_BREAKER_PCT", 0.20))
    if max_portfolio_dd > 0:
        state = db.query(BotState).filter_by(mode=mode).first()
        if state:
            try:
                initial = (
                    getattr(state, f"{mode}_initial_bankroll", None)
                    or getattr(state, "paper_initial_bankroll", None)
                    or float(_cfg("INITIAL_BANKROLL", 1000.0))
                )
            except (TypeError, ValueError):
                initial = bankroll  # fallback: no drawdown detected
            current = bankroll
            if initial and initial > 0:
                dd_pct = (initial - current) / initial
                if dd_pct > max_portfolio_dd:
                    # Emergency: disable ALL strategies for this mode
                    logger.critical(
                        "[CIRCUIT BREAKER] Portfolio down %.1f%% from initial $%.2f "
                        "(current $%.2f). Disabling ALL %s strategies.",
                        dd_pct * 100, initial, current, mode,
                    )
                    from backend.core.strategy_health import disable_for_rehab
                    all_configs = (
                        db.query(StrategyConfig)
                        .filter(StrategyConfig.enabled.is_(True))
                        .all()
                    )
                    for cfg in all_configs:
                        disable_for_rehab(cfg)
                    db.commit()
                    return (
                        f"PORTFOLIO CIRCUIT BREAKER: down {dd_pct:.1%} from "
                        f"${initial:.2f} (current ${current:.2f}) — all strategies disabled"
                    )

    return None


def _get_current_exposure(db, trading_mode: str = None) -> float:
    """Sum of open (unsettled) trade sizes for current trading mode."""
    from sqlalchemy import func

    mode = trading_mode or _cfg("TRADING_MODE", "paper")

    result = (
        db.query(func.coalesce(func.sum(Trade.size), 0.0))
        .filter(Trade.settled.is_(False), Trade.trading_mode == mode)
        .scalar()
    )
    return float(result or 0.0)


async def execute_quote(
    decision: dict, strategy_name: str, mode: str, db=None
) -> dict | None:
    """Execute a QUOTE decision from market_maker — places GTC limit orders on both sides."""
    from backend.models.database import Trade as QT, BotState as QBS
    from backend.db.utils import get_db_session
    from backend.config import settings as s

    if not getattr(s, "HFT_ENABLED", False):
        logger.debug("[execute_quote] HFT_ENABLED=false, skipping quote")
        return None

    market_ticker = decision.get("market_ticker", "")
    bid_price = decision.get("bid_price")
    ask_price = decision.get("ask_price")
    bid_size = decision.get("bid_size", 0)
    ask_size = decision.get("ask_size", 0)

    if not bid_price or not ask_price or bid_size <= 0 or ask_size <= 0:
        logger.warning(
            "[execute_quote] Invalid quote: bid=%s/%s ask=%s/%s",
            bid_price,
            bid_size,
            ask_price,
            ask_size,
        )
        return None

    from contextlib import nullcontext

    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)

    with ctx as db:
        try:
            asset_key = (
                decision.get("condition_id") or decision.get("slug") or strategy_name
            )
            asset_lock = await _get_asset_lock(str(asset_key))
            async with _trade_semaphore:
                async with asset_lock:
                    state = db.query(QBS).filter_by(mode=mode).first()
                    if not state or not state.is_running:
                        return None

                    results = []
                    for side, price, size, direction in [
                        ("bid", bid_price, bid_size, "YES"),
                        ("ask", ask_price, ask_size, "NO"),
                    ]:
                        trade = QT(
                            market_ticker=market_ticker,
                            strategy=strategy_name,
                            trading_mode=mode,
                            direction=direction,
                            entry_price=price,
                            size=size,
                            role="maker",
                            status="open",
                            confidence=decision.get("confidence", 0.5),
                        )
                        db.add(trade)
                        results.append(
                            {
                                "side": side,
                                "direction": direction,
                                "price": price,
                                "size": size,
                                "role": "maker",
                            }
                        )
                        logger.info(
                            "[execute_quote] %s %s %s $%.2f @ %.3f (maker)",
                            strategy_name,
                            side,
                            direction,
                            size,
                            price,
                        )

                    db.commit()
                    return {"quote_placed": True, "orders": results}

        except Exception as e:
            logger.opt(exception=True).error("[execute_quote] Failed: %s", e)
            try:
                db.rollback()
            except Exception:
                logger.exception(
                    "[execute_quote] db.rollback failed after quote execution failure"
                )
            return None


async def execute_decisions(
    decisions: list[dict], strategy_name: str, mode: str, db=None
) -> list[dict]:
    """Execute multiple decisions, respecting per-scan limits."""
    MAX_TRADES_PER_CYCLE = 6
    results = []
    for d in decisions[:MAX_TRADES_PER_CYCLE]:
        if d.get("decision") == "QUOTE":
            result = await execute_quote(d, strategy_name, mode, db=db)
        else:
            result = await execute_decision(d, strategy_name, mode, db=db)
        if result:
            results.append(result)
    return results


class StrategyExecutor:
    """Namespace for execute_decision / execute_decisions."""

    execute_decision = staticmethod(execute_decision)
    execute_decisions = staticmethod(execute_decisions)
    execute_quote = staticmethod(execute_quote)
