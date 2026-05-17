"""Execute strategy decisions — create trades in paper mode, place orders in live mode."""

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional
import threading

from backend.config import settings
from backend.models.database import Trade, Signal, BotState, StrategyConfig, botstate_mutex
from backend.core.risk_manager import RiskManager
from backend.core.event_bus import _broadcast_event
from backend.core.mode_context import get_context
from backend.core.alert_manager import AlertManager
from backend.core.validation import TradeValidator, SignalValidator, ValidationError, log_validation_error
from backend.core.trade_attempts import TradeAttemptRecorder
from backend.core.paper_slippage import get_simulator
from sqlalchemy import case, func, and_, text, update
from sqlalchemy.exc import OperationalError

from loguru import logger
risk_manager = RiskManager()

# Per-asset locks allow concurrent execution across different markets while
# serializing same-market orders to prevent bankroll/exposure double-counting.
# A global semaphore caps total concurrent trades.
_trade_locks: dict[str, asyncio.Lock] = {}
_trade_locks_mutex = asyncio.Lock()
MAX_CONCURRENT_TRADES = 3
_trade_semaphore = asyncio.Semaphore(MAX_CONCURRENT_TRADES)

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
    return _LOCK_RETRY_BASE_DELAY_SECONDS * (2 ** attempt)


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


def _prepare_short_botstate_transaction(db) -> None:
    """Keep best-effort BotState updates from waiting behind stale row locks.

    Uses PostgreSQL advisory lock (pg_try_advisory_xact_lock) to avoid
    blocking the thread pool worker on row-level lock contention. If the
    advisory lock is busy (another trade or flush is mid-update), returns
    False so the caller can skip this update cycle immediately — no retry,
    no thread blocked.
    """

    if db.get_bind().dialect.name != "postgresql":
        return None

    acquired = db.execute(
        text("SELECT pg_try_advisory_xact_lock(hashtext('polyedge_botstate_update'))")
    ).scalar()
    if not acquired:
        return False

    db.execute(text("SET LOCAL lock_timeout = '500ms'"))
    db.execute(text("SET LOCAL statement_timeout = '2s'"))
    return True


def _run_short_botstate_update(mode: str, adjusted_size: float) -> bool:
    """Run one isolated BotState update with caller-owned error handling.

    Returns True if the update was applied, False if it was skipped
    (advisory lock busy — non-fatal).
    """

    from backend.db.utils import get_db_session

    with get_db_session() as state_db:
        ready = _prepare_short_botstate_transaction(state_db)
        if ready is False:
            return False
        _update_botstate_after_trade(state_db, mode, adjusted_size)
        return True


def _commit_session_with_retry(db, *, label: str) -> None:
    """Commit the current SQLAlchemy session with bounded retries."""

    for attempt in range(3):
        try:
            db.commit()
            return
        except OperationalError:
            db.rollback()
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
            else:
                raise


async def _commit_session_with_retry_async(db, *, label: str) -> None:
    """Async variant of bounded SQLAlchemy commit retries."""

    for attempt in range(3):
        try:
            db.commit()
            return
        except OperationalError:
            db.rollback()
            if attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
            else:
                raise


def _apply_post_trade_botstate_update(mode: str, adjusted_size: float) -> bool:
    """Best-effort BotState counter update after trade persistence is committed.

    Uses advisory lock inside _run_short_botstate_update so the thread pool
    worker never blocks on row-level lock contention. If the lock is busy
    (another thread is mid-update), skip immediately — the trade is already
    committed and BotState is eventually consistent.
    """

    try:
        with _botstate_threading_lock:
            updated = _run_short_botstate_update(mode, adjusted_size)
        if not updated:
            logger.info(
                "[strategy_executor] BotState update skipped for mode={} adjusted_size={} (advisory lock busy)",
                mode,
                adjusted_size,
            )
        return updated
    except OperationalError as exc:
        if _is_lock_timeout_error(exc):
            logger.warning(
                "[strategy_executor] trade persisted but BotState follow-up update skipped for mode={} adjusted_size={}: {}",
                mode,
                adjusted_size,
                exc,
            )
            return False
        logger.opt(exception=exc).error(
            "[strategy_executor] post-trade BotState update failed for mode={} adjusted_size={}",
            mode,
            adjusted_size,
        )
        return False


async def _apply_post_trade_botstate_update_async(mode: str, adjusted_size: float) -> bool:
    """Async best-effort BotState counter update after trade persistence is committed.

    Uses advisory lock inside _run_short_botstate_update so the event loop
    never blocks on row-level lock contention. If the lock is busy, skip
    immediately — the trade is already committed and BotState is eventually
    consistent.
    """

    try:
        async with botstate_mutex:
            updated = await asyncio.to_thread(
                _run_short_botstate_update, mode, adjusted_size
            )
        if not updated:
            logger.info(
                "[strategy_executor] async BotState update skipped for mode={} adjusted_size={} (advisory lock busy)",
                mode,
                adjusted_size,
            )
        return updated
    except OperationalError as exc:
        if _is_lock_timeout_error(exc):
            logger.warning(
                "[strategy_executor] trade persisted but async BotState follow-up update skipped for mode={} adjusted_size={}: {}",
                mode,
                adjusted_size,
                exc,
            )
            return False
        logger.opt(exception=exc).error(
            "[strategy_executor] async post-trade BotState update failed for mode={} adjusted_size={}",
            mode,
            adjusted_size,
        )
        return False


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
            logger.exception("[strategy_executor] db.rollback failed after TradeAttempt record failure")
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
            existing = db.query(Trade).filter(*filters).first()
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

            # Rate limiter: block if >3 trades on same market in last 5 minutes
            from datetime import timedelta
            five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
            recent_count = db.query(func.count(Trade.id)).filter(
                Trade.market_ticker == market_ticker,
                Trade.timestamp >= five_min_ago,
            ).scalar() or 0
            if recent_count >= 3:
                logger.warning(
                    f"[{strategy_name}] Rate limit exceeded: {recent_count} trades on {market_ticker} in last 5min (max 3)"
                )
                attempt_recorder.record_blocked(
                    f"Rate limit exceeded: {recent_count} trades in 5min on {market_ticker}",
                    phase="preflight",
                    reason_code="BLOCKED_RATE_LIMIT",
                )
                db.commit()
                return None

            state = db.query(BotState).filter_by(mode=mode).first()
            if not state or not state.is_running:
                logger.info(
                    f"[{strategy_name}] Bot not running, skipping decision for {market_ticker}"
                )

                strategy_config = db.query(StrategyConfig).filter_by(strategy_name=strategy_name).first()
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
                    else settings.INITIAL_BANKROLL
                )

            # Bankroll reconciliation is async — skip in thread path, log warning
            if bankroll < 0:
                logger.warning(
                    "[%s] Negative bankroll ($%.2f) detected in thread-offloaded path; "
                    "skipping async reconciliation — using floor $0.00",
                    mode.upper(), bankroll,
                )
                bankroll = 0.0

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

            # --- Duplicate market guard: block if same strategy+ticker traded in last 5 min ---
            from datetime import timedelta
            _cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
            _recent_dup = (
                db.query(Trade)
                .filter(
                    Trade.strategy == strategy_name,
                    Trade.market_ticker == market_ticker,
                    Trade.direction == direction,
                    Trade.timestamp >= _cutoff,
                )
                .first()
            )
            if _recent_dup is not None:
                logger.warning(
                    f"[{strategy_name}] Duplicate blocked: already traded {market_ticker} "
                    f"{direction} within 5 min (trade #{_recent_dup.id})"
                )
                attempt_recorder.record_rejected(
                    f"Duplicate: {market_ticker} {direction} already traded in last 5 min",
                    phase="duplicate_guard",
                    reason_code="REJECTED_DUPLICATE_MARKET",
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
                simulation_result = simulator.simulate_fill(
                    entry_price=entry_price,
                    size=adjusted_size,
                    direction=direction,
                    market_ticker=market_ticker,
                    db=db
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
                    pass

            slippage = abs(fill_price - entry_price) / entry_price if entry_price > 0 else 0.0
            fee = None

            if mode == "paper":
                if 'simulation_result' in dir() and simulation_result and not simulation_result.get("rejected", True):
                    fee = simulation_result.get("fee_usd", 0.0)

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
                log_validation_error(e, context=f"execute_decision:signal:{strategy_name}")
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

            _commit_session_with_retry(
                db,
                label=f"trade+signal persistence {market_ticker} ({mode})",
            )

            _apply_post_trade_botstate_update(mode, adjusted_size)

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
    asset_lock = await _get_asset_lock(str(asset_key))
    async with _trade_semaphore:
        async with asset_lock:
            # Paper/testnet/Kalshi: no async CLOB calls — offload entirely to thread
            is_live_clob = (
                mode == "live"
                and not (decision.get("market_ticker", "").startswith("KX") or decision.get("platform") == "kalshi")
                and decision.get("token_id") is not None
            )
            for lock_attempt in range(_MAX_LOCK_RETRY_ATTEMPTS):
                try:
                    if not is_live_clob:
                        if db is not None:
                            # db was provided (e.g. in tests) — run synchronously to
                            # avoid crossing thread boundaries with a caller-owned session
                            return _execute_decision_paper_or_kalshi(
                                decision, strategy_name, mode, db,
                            )
                        return await asyncio.to_thread(
                            _execute_decision_paper_or_kalshi,
                            decision, strategy_name, mode,
                        )

                    # Live mode with CLOB: must stay on event loop for async HTTP calls
                    # but still wrap DB ops where possible
                    return await _execute_decision_live_clob(
                        decision, strategy_name, mode, db,
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
            existing = db.query(Trade).filter(*filters).first()
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

            # Rate limiter: block if >3 trades on same market in last 5 minutes
            from datetime import timedelta
            five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
            recent_count = db.query(func.count(Trade.id)).filter(
                Trade.market_ticker == market_ticker,
                Trade.timestamp >= five_min_ago,
            ).scalar() or 0
            if recent_count >= 3:
                logger.warning(
                    f"[{strategy_name}] Rate limit exceeded: {recent_count} trades on {market_ticker} in last 5min (max 3)"
                )
                attempt_recorder.record_blocked(
                    f"Rate limit exceeded: {recent_count} trades in 5min on {market_ticker}",
                    phase="preflight",
                    reason_code="BLOCKED_RATE_LIMIT",
                )
                db.commit()
                return None

            state = db.query(BotState).filter_by(mode=mode).first()
            if not state or not state.is_running:
                logger.info(
                    f"[{strategy_name}] Bot not running, skipping decision for {market_ticker}"
                )

                strategy_config = db.query(StrategyConfig).filter_by(strategy_name=strategy_name).first()
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
                    else settings.INITIAL_BANKROLL
                )

            # Skip async bankroll reconciliation in this path —
            # floor negative bankroll to $0 to avoid blocking event loop
            if bankroll < 0:
                logger.warning(
                    "[%s] Negative bankroll ($%.2f) detected; flooring to $0.00",
                    mode.upper(), bankroll,
                )
                bankroll = 0.0

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

            clob_order_id = None
            fill_price = entry_price
            filled_size = None
            alert_manager = AlertManager(db)

            if mode == "paper":
                simulator = get_simulator()
                simulation_result = simulator.simulate_fill(
                    entry_price=entry_price,
                    size=adjusted_size,
                    direction=direction,
                    market_ticker=market_ticker,
                    db=db
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
                for clob_attempt in range(2):
                    try:
                        async with context.clob_client as clob:
                            await asyncio.wait_for(clob.create_or_derive_api_key(), timeout=30.0)
                            result = await asyncio.wait_for(
                                clob.place_limit_order(
                                    token_id=token_id,
                                    side="BUY",
                                    price=entry_price,
                                    size=adjusted_size,
                                ),
                                timeout=30.0,
                            )
                        if result.success:
                            clob_order_id = result.order_id
                            fill_price = result.fill_price or fill_price
                            if hasattr(result, "filled_size") and result.filled_size is not None:
                                filled_size = result.fill_size
                            logger.info(f"[{mode.upper()}][{strategy_name}] Order placed: {clob_order_id}")
                            break
                        err_msg = result.error or "CLOB order rejected"
                        logger.warning(f"[{mode.upper()}][{strategy_name}] Order rejected for {market_ticker}: {err_msg}")
                        if clob_attempt == 0 and "order_version_mismatch" in err_msg.lower():
                            try:
                                fresh_mid = await asyncio.wait_for(
                                    context.clob_client.get_mid_price(token_id),
                                    timeout=15.0,
                                )
                                entry_price = fresh_mid
                                logger.warning(
                                    f"[{mode.upper()}][{strategy_name}] Retrying with refreshed mid price {entry_price:.4f}"
                                )
                                continue
                            except Exception as refresh_err:
                                logger.warning(f"Failed to refresh mid price: {refresh_err}")
                        attempt_recorder.record_rejected(
                            err_msg, phase="execution", reason_code="REJECTED_BROKER_ORDER",
                            adjusted_size=adjusted_size, order_id=getattr(result, "order_id", None),
                        )
                        db.commit()
                        return None
                    except Exception as clob_err:
                        err_str = f"{type(clob_err).__name__}: {clob_err}"
                        if isinstance(clob_err, KeyError) and str(clob_err) == "'error'":
                            err_str = "CLOB order rejected by broker response"
                            logger.warning(f"[{mode.upper()}][{strategy_name}] Order rejected for {market_ticker}: {err_str}")
                            attempt_recorder.record_rejected(
                                err_str,
                                phase="execution",
                                reason_code="REJECTED_BROKER_ORDER",
                                adjusted_size=adjusted_size,
                            )
                            db.commit()
                            return None
                        logger.opt(exception=True).error(f"[strategy_executor.execute_decision] {err_str} for {market_ticker}")
                        if clob_attempt == 0 and "order_version_mismatch" in str(clob_err).lower():
                            try:
                                fresh_mid = await asyncio.wait_for(
                                    context.clob_client.get_mid_price(token_id),
                                    timeout=15.0,
                                )
                                entry_price = fresh_mid
                                logger.warning(
                                    f"[{mode.upper()}][{strategy_name}] Retrying after exception with refreshed mid price {entry_price:.4f}"
                                )
                                continue
                            except Exception as refresh_err:
                                logger.warning(f"Failed to refresh mid price: {refresh_err}")
                        attempt_recorder.record_failed(
                            f"CLOB execution error: {err_str}", phase="execution", adjusted_size=adjusted_size,
                        )
                        db.commit()
                        return None
                if clob_order_id is None:
                    attempt_recorder.record_failed(
                        "CLOB execution produced no order id",
                        phase="execution",
                        adjusted_size=adjusted_size,
                    )
                    db.commit()
                    return None
                alert_manager.check_high_slippage(
                    trade_id=0, expected_price=entry_price, actual_price=fill_price,
                    position_value=adjusted_size, mode=mode,
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
                    pass

            slippage = abs(fill_price - entry_price) / entry_price if entry_price > 0 else 0.0
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
                log_validation_error(e, context=f"execute_decision:signal:{strategy_name}")
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

            await _commit_session_with_retry_async(
                db,
                label=f"trade+signal persistence {market_ticker} ({mode})",
            )

            await _apply_post_trade_botstate_update_async(mode, adjusted_size)

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


def _get_current_exposure(db, trading_mode: str = None) -> float:
    """Sum of open (unsettled) trade sizes for current trading mode."""
    from sqlalchemy import func

    mode = trading_mode or settings.TRADING_MODE

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

    if not getattr(s, 'HFT_ENABLED', False):
        logger.debug("[execute_quote] HFT_ENABLED=false, skipping quote")
        return None

    market_ticker = decision.get("market_ticker", "")
    bid_price = decision.get("bid_price")
    ask_price = decision.get("ask_price")
    bid_size = decision.get("bid_size", 0)
    ask_size = decision.get("ask_size", 0)

    if not bid_price or not ask_price or bid_size <= 0 or ask_size <= 0:
        logger.warning("[execute_quote] Invalid quote: bid=%s/%s ask=%s/%s", bid_price, bid_size, ask_price, ask_size)
        return None

    from contextlib import nullcontext
    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)

    with ctx as db:
        try:
            asset_key = decision.get("condition_id") or decision.get("slug") or strategy_name
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
                        results.append({
                            "side": side,
                            "direction": direction,
                            "price": price,
                            "size": size,
                            "role": "maker",
                        })
                        logger.info(
                            "[execute_quote] %s %s %s $%.2f @ %.3f (maker)",
                            strategy_name, side, direction, size, price,
                        )

                    db.commit()
                    return {"quote_placed": True, "orders": results}

        except Exception as e:
            logger.opt(exception=True).error("[execute_quote] Failed: %s", e)
            try:
                db.rollback()
            except Exception:
                logger.exception("[execute_quote] db.rollback failed after quote execution failure")
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
