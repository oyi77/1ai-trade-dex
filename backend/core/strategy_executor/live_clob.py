"""Live CLOB execution — stays on event loop for async Polymarket API calls."""

import asyncio
import json as _json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional

from loguru import logger
from sqlalchemy.exc import OperationalError

from backend.db.utils import get_db_session
from contextlib import nullcontext

from backend.config import _cfg
from backend.models.database import StrategyConfig, botstate_mutex

from backend.core.strategy_executor.helpers import (
    _first_numeric_attr,
    _is_lock_timeout_error,
    _BotStateLockRetry,
)
from backend.core.strategy_executor.preflight import _preflight_checks
from backend.core.strategy_executor.recording import (
    _record_trade,
    _update_botstate_after_trade,
    _record_unexpected_attempt_failure,
)
from backend.core.trade_attempts import TradeAttemptRecorder
from backend.core.alert_manager import AlertManager
from backend.core.trade_forensics import classify_trade_role


def _maker_config():
    """Lazy import of maker-first config constants from package (monkeypatchable)."""
    from backend.core.strategy_executor import (
        MAKER_WAIT_SECONDS,
        MAKER_POLL_INTERVAL_SECONDS,
        MAKER_FIRST_ENABLED,
    )
    return MAKER_WAIT_SECONDS, MAKER_POLL_INTERVAL_SECONDS, MAKER_FIRST_ENABLED


# ---------------------------------------------------------------------------
# 1. HFT fast path
# ---------------------------------------------------------------------------

async def _execute_hft_path(
    decision: dict, strategy_name: str, mode: str, db=None
) -> Optional[dict]:
    if mode != "live":
        return None
    if not decision.get("token_id"):
        return None
    if decision.get("market_ticker", "").startswith("KX"):
        return None

    try:
        from backend.core.hft_executor import HFTExecutor

        executor = HFTExecutor()

        from backend.strategies.types_hft import HFTSignal

        signal = HFTSignal(
            signal_id=decision.get("correlation_id") or decision.get("attempt_id", ""),
            market_id=str(decision.get("token_id", "")),
            event_slug=decision.get("slug") or decision.get("event_slug", ""),
            edge=float(decision.get("entry_price", 0.5)),
            signal_type=decision.get("hft_type", "prob_arb"),
            side=(
                "BUY"
                if decision.get("direction", "").lower() in ("up", "yes")
                else "SELL"
            ),
            trading_mode=mode,
            metadata=decision,
        )

        size = float(decision.get("size", 0.0))
        bankroll = float(decision.get("bankroll", 0.0)) or float(
            _cfg("INITIAL_BANKROLL", 1000.0)
        )

        result = await executor.execute(signal, size, bankroll)
        if result and getattr(result, "status", "") == "filled":
            return {
                "hft": True,
                "hft_execution_id": getattr(result, "execution_id", None),
                "order_id": getattr(result, "order_id", None),
                "status": "filled",
            }
        return None
    except ImportError:
        logger.warning("[strategy_executor] HFTExecutor not available, falling back to standard path")
        return None
    except Exception as e:
        logger.opt(exception=True).warning(
            f"[strategy_executor] HFT path failed for {strategy_name}: {e}, falling back"
        )
        return None


# ---------------------------------------------------------------------------
# 2. Maker-first execution with taker escalation
# ---------------------------------------------------------------------------

async def _maker_first_execute(
    clob, token_id: str, side: str, price: float, size: float,
    strategy_name: str, mode: str, market_ticker: str,
    force_maker_only: bool = False,
) -> SimpleNamespace:
    maker_wait, maker_poll_interval, _ = _maker_config()

    result = await clob.place_limit_order(
        token_id=token_id, side=side, price=price, size=size, order_type="GTC",
    )
    if not result.success:
        logger.warning(
            f"[{mode.upper()}][{strategy_name}] Maker-first GTC placement failed "
            f"for {market_ticker}: {result.error}"
        )
        if not force_maker_only:
            return await _taker_escalation(clob, token_id, side, size, strategy_name, mode, market_ticker)
        return result

    maker_order_id = result.order_id
    logger.info(
        f"[{mode.upper()}][{strategy_name}] Maker GTC placed: "
        f"order_id={maker_order_id} for {market_ticker} @ {price} x {size}"
    )

    if force_maker_only:
        return result

    maker_filled = False
    poll_start = datetime.now(timezone.utc)
    while (datetime.now(timezone.utc) - poll_start).total_seconds() < maker_wait:
        await asyncio.sleep(maker_poll_interval)
        try:
            open_orders = await clob.get_open_orders()
            maker_still_open = any(
                (isinstance(o, dict) and o.get("id") == maker_order_id)
                for o in (open_orders or [])
            )
            if not maker_still_open:
                maker_filled = True
                logger.info(f"[{mode.upper()}][{strategy_name}] Maker GTC filled for {market_ticker}")
                result.fill_price = price
                result.fill_size = size
                result.maker_filled = True
                break
        except Exception as poll_err:
            logger.debug(f"[{mode.upper()}][{strategy_name}] Poll error for {market_ticker}: {poll_err}")
            continue

    if not maker_filled:
        if maker_order_id:
            try:
                await clob.cancel_order(maker_order_id)
                logger.info(f"[{mode.upper()}][{strategy_name}] Cancelled unfilled maker GTC for {market_ticker}")
            except Exception as cancel_err:
                logger.warning(f"[{mode.upper()}][{strategy_name}] Cancel failed on unfilled maker GTC: {cancel_err}")

        if not force_maker_only:
            logger.info(f"[{mode.upper()}][{strategy_name}] Escalating to taker order for {market_ticker}")
            result = await _taker_escalation(clob, token_id, side, size, strategy_name, mode, market_ticker)

    return result


async def _taker_escalation(
    clob, token_id: str, side: str, size: float,
    strategy_name: str, mode: str, market_ticker: str,
) -> SimpleNamespace:
    try:
        book = await clob.get_order_book(token_id)
    except Exception:
        book = None

    side_u = side.upper()
    if book and side_u == "BUY" and book.best_ask:
        taker_price = float(book.best_ask)
    elif book and side_u == "SELL" and book.best_bid:
        taker_price = float(book.best_bid)
    else:
        try:
            taker_price = await clob.get_mid_price(token_id)
        except Exception:
            taker_price = 0.5

    taker_price = max(0.01, min(0.99, taker_price))

    logger.info(f"[{mode.upper()}][{strategy_name}] Taker escalation: {side} {size} @ {taker_price:.4f} for {market_ticker}")

    taker_result = await clob.place_limit_order(
        token_id=token_id, side=side_u, price=taker_price, size=size,
    )
    if getattr(taker_result, "success", False):
        taker_result.maker_filled = False
    return taker_result


# ---------------------------------------------------------------------------
# 3. Process a successful CLOB order result
# ---------------------------------------------------------------------------

async def _process_order_result(
    result, decision: dict, clob, token_id: str, entry_price: float,
    adjusted_size: float, platform: str, mode: str, strategy_name: str,
    direction: str, market_ticker: str, fill_price: float, db,
) -> tuple:
    clob_order_id = getattr(result, "order_id", None)
    normalized_fill_price = _first_numeric_attr(
        result, ("fill_price", "filled_avg_price", "avg_price"),
    )
    if normalized_fill_price is not None:
        fill_price = normalized_fill_price

    filled_size = _first_numeric_attr(
        result, ("filled_size", "fill_size", "filled", "size_matched"),
    )
    fee = _first_numeric_attr(
        result, ("fee", "fees_paid", "fees", "fee_paid"),
    )

    best_ask = None
    best_bid = None
    try:
        book = await clob.get_order_book(token_id)
        if book:
            best_ask = book.best_ask
            best_bid = book.best_bid
    except Exception:
        logger.debug(
            f"[{mode.upper()}][{strategy_name}] get_order_book failed "
            f"for {market_ticker} — skipping book-based role classification"
        )

    execution_decision = dict(decision)
    if best_ask is not None:
        execution_decision["best_ask"] = best_ask
    if best_bid is not None:
        execution_decision["best_bid"] = best_bid

    base_size = filled_size if (filled_size is not None and filled_size > 0) else adjusted_size

    role, maker_size, taker_size = await classify_trade_role(
        platform=platform, mode=mode, clob_order_id=clob_order_id,
        price=fill_price, size=base_size, direction=direction,
        decision=execution_decision, db_session=db,
    )

    logger.info(
        f"[{mode.upper()}][{strategy_name}] Order placed: {clob_order_id} "
        f"(role={role}, maker_size={maker_size}, taker_size={taker_size})"
    )

    return clob_order_id, fill_price, filled_size, fee, role, maker_size, taker_size


# ---------------------------------------------------------------------------
# 4. Live CLOB execution decision
# ---------------------------------------------------------------------------

async def _execute_decision_live_clob(
    decision: dict, strategy_name: str, mode: str, db=None
) -> Optional[dict]:
    from backend.data.polymarket_clob import clob_from_settings
    from backend.core.strategy_executor import MAKER_FIRST_ENABLED

    market_ticker = decision.get("market_ticker", "")
    direction = decision.get("direction", "")
    order_side = str(decision.get("side") or decision.get("decision") or "BUY").upper()
    entry_price = float(decision.get("entry_price", 0.5))
    token_id = decision.get("token_id")
    platform = decision.get("platform", "polymarket")
    force_maker_only_init = decision.get("force_maker_only", False)

    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)

    with ctx as db:
        attempt_recorder = TradeAttemptRecorder(db, decision, strategy_name, mode)
        attempt_recorder.update(status="STARTED", phase="preflight")

        try:
            pf = _preflight_checks(db, decision, strategy_name, mode, attempt_recorder)
            if pf is None:
                return None

            adjusted_size = pf.adjusted_size

            strategy_cfg = (
                db.query(StrategyConfig)
                .filter_by(strategy_name=strategy_name)
                .first()
            )
            if strategy_cfg is not None:
                live_override = getattr(strategy_cfg, "live_enabled", None)
                if live_override is not None and live_override is False:
                    logger.warning(f"[{strategy_name}] StrategyGate: live_enabled=False, blocking")
                    attempt_recorder.record_blocked(
                        "StrategyGate: live_enabled=False", phase="strategy_gate",
                        reason_code="BLOCKED_LIVE_DISABLED",
                    )
                    db.commit()
                    return None

            live_order_kwargs = {}
            if strategy_cfg is not None:
                live_params = getattr(strategy_cfg, "live_order_params", {}) or {}
                live_order_kwargs = (
                    _json.loads(live_params) if isinstance(live_params, str) else live_params
                )

            clob_order_id = None
            fill_price = entry_price
            filled_size = adjusted_size
            fee = None
            role = "unknown"
            maker_size = None
            taker_size = None

            force_maker_only = force_maker_only_init or bool(
                getattr(strategy_cfg, "force_maker_only", False)
            )

            async with botstate_mutex:
                async with pf.context.clob_client as clob:
                    await clob.create_or_derive_api_key()

                    for clob_attempt in range(2):
                        try:
                            if MAKER_FIRST_ENABLED or force_maker_only:
                                result = await _maker_first_execute(
                                    clob, token_id=token_id, side=order_side,
                                    price=entry_price, size=adjusted_size,
                                    strategy_name=strategy_name, mode=mode,
                                    market_ticker=market_ticker,
                                    force_maker_only=force_maker_only,
                                )
                            else:
                                result = await clob.place_limit_order(
                                    token_id=token_id, side=order_side,
                                    price=entry_price, size=adjusted_size,
                                )

                            logger.info(
                                f"[LIVE][{strategy_name}] CLOB result: "
                                f"success={result.success} "
                                f"order_id={getattr(result, 'order_id', None)} "
                                f"error={getattr(result, 'error', None)}"
                            )

                            if result.success:
                                clob_order_id, fill_price, filled_size, fee, role, maker_size, taker_size = (
                                    await _process_order_result(
                                        result, decision, clob, token_id, entry_price,
                                        adjusted_size, platform, mode, strategy_name,
                                        direction, market_ticker, fill_price, db,
                                    )
                                )
                                break

                            err_msg = str(getattr(result, "error", "") or "CLOB order rejected")
                            logger.warning(
                                f"[{mode.upper()}][{strategy_name}] Order rejected for "
                                f"{market_ticker}: {err_msg}"
                            )
                            if (
                                clob_attempt == 0
                                and "order_version_mismatch" in err_msg.lower()
                            ):
                                try:
                                    fresh_mid = await clob.get_mid_price(token_id)
                                    entry_price = fresh_mid
                                    logger.warning(
                                        f"[{mode.upper()}][{strategy_name}] Retrying with refreshed mid price {entry_price:.4f}"
                                    )
                                    continue
                                except Exception:
                                    logger.exception("Failed to refresh mid price")

                            attempt_recorder.record_rejected(
                                err_msg, phase="execution",
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
                                    fresh_mid = await clob.get_mid_price(token_id)
                                    entry_price = fresh_mid
                                    logger.warning(
                                        f"[{mode.upper()}][{strategy_name}] Retrying after exception with refreshed mid price {entry_price:.4f}"
                                    )
                                    continue
                                except Exception as refresh_err:
                                    logger.warning(f"Failed to refresh mid price: {refresh_err}")

                            attempt_recorder.record_failed(
                                f"CLOB execution error: {err_str}", phase="execution",
                                adjusted_size=adjusted_size,
                            )
                            db.commit()
                            return None

                    if clob_order_id is None:
                        return None

                    if filled_size is not None and filled_size <= 0:
                        logger.warning(
                            f"[{mode.upper()}][{strategy_name}] Order {clob_order_id} "
                            f"placed but NOT FILLED (filled_size=0). Skipping trade record."
                        )
                        attempt_recorder.record_rejected(
                            "Order placed but not filled (filled_size=0)",
                            phase="execution", reason_code="UNFILLED_LIMIT_ORDER",
                            adjusted_size=adjusted_size, order_id=clob_order_id,
                        )
                        db.commit()
                        try:
                            async with pf.context.clob_client as cancel_clob:
                                await cancel_clob.cancel_order(clob_order_id)
                        except Exception as cancel_err:
                            logger.warning(f"[{mode.upper()}][{strategy_name}] Failed to cancel unfilled order: {cancel_err}")
                        return None

                    try:
                        AlertManager.check_high_slippage(
                            trade_id=0, expected_price=entry_price,
                            actual_price=fill_price, position_value=adjusted_size, mode=mode,
                        )
                    except Exception:
                        pass

                    if mode in ("testnet", "live") and not token_id:
                        logger.warning(f"[{mode.upper()}][{strategy_name}] No token_id for {market_ticker}, skipping order")
                        attempt_recorder.record_blocked(
                            "No token_id for CLOB order", phase="execution",
                            reason_code="BLOCKED_MISSING_TOKEN_ID", adjusted_size=adjusted_size,
                        )
                        db.commit()
                        return None

                    # ---------- BotState update (inside outer mutex — no deadlock) ----------
                    _update_botstate_after_trade(db, mode, adjusted_size)
                    db.commit()

                    trade = _record_trade(
                        db, decision, strategy_name, mode, pf,
                        clob_order_id, fill_price, entry_price, filled_size,
                        fee, role, maker_size, taker_size, attempt_recorder,
                    )
                    if trade is None:
                        return None
                    return {
                        "status": "executed",
                        "trade_id": trade.id if trade else None,
                        "clob_order_id": clob_order_id,
                        "fill_price": fill_price,
                        "entry_price": entry_price,
                        "direction": direction,
                        "market_ticker": market_ticker,
                        "size": filled_size or adjusted_size,
                        "fee": fee,
                        "role": role,
                        "mode": mode,
                    }

        except OperationalError as exc:
            logger.opt(exception=True).error(
                f"[strategy_executor.execute_decision] OperationalError for {market_ticker}: {exc}"
            )
            try:
                db.rollback()
            except Exception as e:
                logger.opt(exception=True).warning(f"[strategy_executor] db.rollback failed after OperationalError : {e}")
            if _is_lock_timeout_error(exc):
                raise _BotStateLockRetry(str(exc)) from exc
            return None

        except Exception as exc:
            logger.exception(
                f"[strategy_executor.execute_decision] {type(exc).__name__} for {market_ticker}: {exc}"
            )
            try:
                db.rollback()
            except Exception as e:
                logger.opt(exception=True).warning(f"[strategy_executor] db.rollback failed: {e}")
            if attempt_recorder is not None:
                _record_unexpected_attempt_failure(
                    db, decision, strategy_name, mode,
                    f"Unexpected execution error: {type(exc).__name__}: {exc}",
                    attempt_id=getattr(attempt_recorder.attempt, "attempt_id", None),
                )
