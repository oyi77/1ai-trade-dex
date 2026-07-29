"""Paper/Kalshi execution path — sync execution for paper, testnet, and Kalshi modes.

Called from main.py when the decision is NOT a live CLOB order (i.e. paper/testnet
mode, or Kalshi platform).  Handles simulated fills via PaperSlippageSimulator for
paper/testnet, and Kalshi provider lookup for Kalshi.  OperationalError lock
contention is surfaced so the caller can retry.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Optional

from loguru import logger
from sqlalchemy.exc import OperationalError

from backend.core.paper_slippage import get_simulator
from backend.core.trade_attempts import TradeAttemptRecorder
from backend.core.trade_forensics import classify_trade_role_sync
from backend.core.strategy_executor.helpers import (
    _BotStateLockRetry,
    _first_numeric_attr,
    _is_lock_timeout_error,
)
from backend.core.strategy_executor.locks import _botstate_threading_lock
from backend.core.strategy_executor.preflight import _preflight_checks
from backend.core.strategy_executor.recording import (
    _record_trade,
    _record_unexpected_attempt_failure,
    _update_botstate_after_trade,
)


def _execute_decision_paper_or_kalshi(
    decision: dict,
    strategy_name: str,
    mode: str,
    db=None,
) -> Optional[dict]:
    """Execute a trade decision via paper simulation or Kalshi path.

    Sync function — called from a thread pool by the async executor
    (:func:`~backend.core.strategy_executor.main.execute_decision`).

    Handles ``OperationalError`` (PostgreSQL lock timeout) by raising
    ``_BotStateLockRetry`` so the caller can retry with backoff.

    Args:
        decision: Trade decision dict with ``market_ticker``, ``direction``,
            ``entry_price``, ``token_id``, ``platform``, ``size``, etc.
        strategy_name: Name of the strategy that generated the decision.
        mode: Trading mode — ``"paper"``, ``"testnet"``, or ``"live"`` (for Kalshi).
        db: Optional shared DB session.  When ``None`` a new session is obtained
            from :func:`backend.db.utils.get_db_session`.

    Returns:
        Result dict on success, or ``None`` if blocked/rejected/failed.
    """
    market_ticker = str(decision.get("market_ticker", ""))
    direction = str(decision.get("direction", ""))
    entry_price = _first_numeric_attr(decision, ("entry_price", "fill_price")) or 0.5
    token_id = decision.get("token_id")
    platform = str(decision.get("platform", "polymarket"))
    size = float(decision.get("size", 0.0))

    is_kalshi = platform == "kalshi" or market_ticker.startswith("KX")

    # --- DB session management ---
    from backend.db.utils import get_db_session

    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)

    with ctx as db:
        try:
            # --- TradeAttemptRecorder ---
            attempt_recorder = TradeAttemptRecorder(db, decision, strategy_name, mode)

            # --- Preflight checks (shared with live CLOB path) ---
            pf = _preflight_checks(db, decision, strategy_name, mode, attempt_recorder)
            if pf is None:
                return None

            adjusted_size = pf.adjusted_size

            # --- Mode-specific execution ---
            fill_price = entry_price
            fee = 0.0
            slippage_bps = 0.0
            effective_size = adjusted_size
            clob_order_id = None

            if is_kalshi:
                # Kalshi path: obtain the provider from the registry and record intent.
                from backend.markets.provider_registry import market_registry

                try:
                    provider = market_registry.get("kalshi")
                    if provider is None:
                        logger.warning(
                            "[%s][%s] Kalshi provider not available for %s, "
                            "recording as paper",
                            mode.upper(), strategy_name, market_ticker,
                        )
                except Exception:
                    logger.exception(
                        "[%s][%s] Failed to get Kalshi provider for %s",
                        mode.upper(), strategy_name, market_ticker,
                    )
                fill_price = entry_price
                effective_size = adjusted_size
            else:
                # Paper / testnet path: simulate fill with realistic slippage.
                simulator = get_simulator()
                fill_result = simulator.simulate_fill(
                    entry_price=entry_price,
                    size=adjusted_size,
                    direction=direction.upper() if direction else "BUY",
                    market_ticker=market_ticker,
                    orderbook_depth_usd=0.0,
                    db=db,
                )

                if fill_result.get("rejected", False):
                    rejection_reason = fill_result.get(
                        "rejection_reason", "SIMULATED_REJECTION"
                    )
                    logger.info(
                        "[%s][%s] Paper fill rejected for %s: %s",
                        mode.upper(), strategy_name, market_ticker, rejection_reason,
                    )
                    attempt_recorder.record_rejected(
                        rejection_reason,
                        phase="slippage_simulator",
                        reason_code="REJECTED_SLIPPAGE",
                        adjusted_size=adjusted_size,
                        fill_price=fill_result.get("fill_price", entry_price),
                        slippage_bps=fill_result.get("slippage_bps", 0.0),
                    )
                    db.commit()
                    return None

                fill_price = fill_result.get("fill_price", entry_price)
                fee = fill_result.get("fee_usd", 0.0)
                slippage_bps = fill_result.get("slippage_bps", 0.0)
                effective_size = fill_result.get("effective_size", adjusted_size)

            # --- Classify trade role ---
            platform_for_forensics = "kalshi" if is_kalshi else "paper"
            role, maker_size, taker_size = classify_trade_role_sync(
                platform=platform_for_forensics,
                mode=mode,
                clob_order_id=clob_order_id,
                price=fill_price,
                size=effective_size,
                direction=direction,
                decision=decision,
                db_session=db,
            )

            # --- Record trade in DB (positional signature, shared with live_clob) ---
            trade = _record_trade(
                db,
                decision,
                strategy_name,
                mode,
                pf,
                clob_order_id,
                fill_price,
                entry_price,
                effective_size,
                fee,
                role,
                maker_size,
                taker_size,
                attempt_recorder,
            )
            if trade is None:
                db.commit()
                return None

            # --- Update BotState (protected by threading lock) ---
            with _botstate_threading_lock:
                _update_botstate_after_trade(
                    db=db,
                    mode=mode,
                    fill_price=fill_price,
                    size=effective_size,
                    role=role,
                )

            db.commit()

            result = {
                "status": "executed",
                "trade_id": trade.id if trade else None,
                "market_ticker": market_ticker,
                "direction": direction,
                "fill_price": fill_price,
                "size": effective_size,
                "fee": fee,
                "slippage_bps": slippage_bps,
                "role": role,
                "mode": mode,
                "platform": "kalshi" if is_kalshi else "paper",
            }
            logger.info(
                "[%s][%s] Trade executed: %s %s %.4f x %.2f "
                "(fee=%.4f, slippage=%.1f bps, role=%s, trade_id=%s)",
                mode.upper(), strategy_name, market_ticker, direction,
                fill_price, effective_size, fee, slippage_bps, role,
                trade.id if trade else "?",
            )
            return result

        except OperationalError as e:
            if _is_lock_timeout_error(e):
                logger.warning(
                    "[%s][%s] BotState lock timeout for %s, signalling retry",
                    mode.upper(), strategy_name, market_ticker,
                )
                raise _BotStateLockRetry() from e

            logger.opt(exception=True).error(
                "[%s][%s] OperationalError executing %s: %s",
                mode.upper(), strategy_name, market_ticker, e,
            )
            _record_unexpected_attempt_failure(
                db, decision, strategy_name, mode,
                f"OperationalError: {type(e).__name__}: {e}",
                attempt_id=getattr(attempt_recorder.attempt, "attempt_id", None),
            )
            return None

        except Exception as _exec_exc:
            logger.opt(exception=True).error(
                "[%s][%s] Unexpected error executing %s: %s",
                mode.upper(), strategy_name, market_ticker, _exec_exc,
            )
            import traceback as _tb
            _tb.print_exc()
            _record_unexpected_attempt_failure(
                db, decision, strategy_name, mode,
                f"Unexpected paper/kalshi execution error",
                attempt_id=getattr(attempt_recorder.attempt, "attempt_id", None),
            )
            return None