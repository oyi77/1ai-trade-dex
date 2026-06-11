"""Arb execution bridge.

Reads DecisionLog rows with `decision == 'ARB'` and re-dispatches them
through `execute_decision`. This is the missing link between arb detection
in `UnifiedPMArb` and trade execution.

Each decision is handled at most once: after processing, rows are marked
via `DecisionLog.execution_status` (EXECUTED / SKIPPED / FAILED) and the
fetch query only returns rows where it is still NULL. Arb decisions are
time-sensitive — a stale or invalid one is marked and dropped; the scanner
emits a fresh decision if the edge reappears.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from loguru import logger

from backend.core.strategy_executor import execute_decision
from backend.db.utils import get_db_session
from backend.models.database import DecisionLog, BotState


async def _default_live_quote_provider(leg: dict) -> dict:
    from backend.data.polymarket_clob import clob_from_settings

    token_id = str(leg.get("token_id") or "").strip()
    if not token_id:
        return {}
    async with clob_from_settings("live") as clob:
        book = await clob.get_order_book(token_id)
    if book.best_ask is None:
        return {}
    ask_size = 0.0
    if book.asks:
        ask_size = _positive_float(book.asks[0].get("size"), 0.0)
    return {"price": float(book.best_ask), "available_size": ask_size}


def _load_signal_data(row: DecisionLog) -> dict:
    raw_signal = getattr(row, "signal_data", None)
    if isinstance(raw_signal, str) and raw_signal.strip():
        try:
            import json as _json

            parsed = _json.loads(raw_signal)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    if isinstance(raw_signal, dict):
        return raw_signal
    return {}


def _mark_execution_status(row_ids: list[str], status: str) -> None:
    ids = [int(rid) for rid in row_ids if str(rid).isdigit()]
    if not ids:
        return
    try:
        with get_db_session() as db:
            db.query(DecisionLog).filter(DecisionLog.id.in_(ids)).update(
                {"execution_status": status}, synchronize_session=False
            )
            db.commit()
    except Exception as exc:
        logger.warning(
            "[arb_executor] failed to mark decisions {} as {}: {}", ids, status, exc
        )


def _positive_float(value, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _normalize_direction(value: str) -> str:
    direction = str(value or "").strip().upper()
    if direction in {"UP", "BUY"}:
        return "YES"
    if direction in {"DOWN", "SELL"}:
        return "NO"
    return direction


def _validated_arb_legs(
    row: DecisionLog,
    signal_data: dict,
    bankroll: float,
    kelly_fraction: float,
    mode: str,
) -> list[dict]:
    kind = str(signal_data.get("kind") or signal_data.get("arb_kind") or "").strip()
    if kind != "yes_no_sum":
        logger.warning(
            "[arb_executor] decision id={} skipped: unsupported arb kind {}",
            getattr(row, "id", "?"),
            kind or "<missing>",
        )
        return []

    raw_legs = signal_data.get("legs")
    if not isinstance(raw_legs, list) or len(raw_legs) != 2:
        logger.warning(
            "[arb_executor] decision id={} skipped: verified two-leg arb payload required",
            getattr(row, "id", "?"),
        )
        return []

    legs: list[dict] = []
    for idx, raw_leg in enumerate(raw_legs):
        if not isinstance(raw_leg, dict):
            return []
        direction = _normalize_direction(raw_leg.get("direction"))
        price = _positive_float(raw_leg.get("price"))
        size = _positive_float(raw_leg.get("size"))
        token_id = str(raw_leg.get("token_id") or "").strip()
        if direction not in {"YES", "NO"} or not (0 < price < 1) or size <= 0:
            logger.warning(
                "[arb_executor] decision id={} skipped: invalid arb leg {}",
                getattr(row, "id", "?"),
                idx,
            )
            return []
        if mode == "live" and not token_id:
            logger.warning(
                "[arb_executor] decision id={} skipped: live arb leg missing token_id",
                getattr(row, "id", "?"),
            )
            return []
        legs.append({**raw_leg, "direction": direction, "price": price, "size": size, "token_id": token_id})

    if {leg["direction"] for leg in legs} != {"YES", "NO"}:
        logger.warning(
            "[arb_executor] decision id={} skipped: yes/no hedge pair required",
            getattr(row, "id", "?"),
        )
        return []

    sizes = [leg["size"] for leg in legs]
    hedge_size = min(sizes)
    if max(sizes) - hedge_size > 1e-9:
        logger.warning(
            "[arb_executor] decision id={} clipped unequal leg sizes to hedge size {}",
            getattr(row, "id", "?"),
            hedge_size,
        )

    max_notional = bankroll * kelly_fraction if bankroll > 0 else 0.0
    if max_notional <= 0:
        return []
    per_share_cost = sum(leg["price"] for leg in legs)
    max_hedge_size = max_notional / per_share_cost if per_share_cost > 0 else 0.0
    hedge_size = min(hedge_size, max_hedge_size)
    if hedge_size <= 0:
        return []

    fee_pct = _positive_float(signal_data.get("fee_pct"), 0.0)
    slippage_cost = _positive_float(signal_data.get("slippage_cost"), 0.0)
    computed_net = 1.0 - per_share_cost - fee_pct - slippage_cost
    declared_net = signal_data.get("net_profit")
    net_profit = _positive_float(declared_net, computed_net) if declared_net is not None else computed_net
    if computed_net <= 0 or net_profit <= 0:
        logger.warning(
            "[arb_executor] decision id={} skipped: non-positive executable net profit computed={} declared={}",
            getattr(row, "id", "?"),
            computed_net,
            declared_net,
        )
        return []

    return [{**leg, "size": hedge_size} for leg in legs]


async def _refresh_live_quotes(row: DecisionLog, legs: list[dict], quote_provider) -> list[dict]:
    if quote_provider is None:
        logger.warning(
            "[arb_executor] decision id={} skipped: live arb requires fresh quote provider",
            getattr(row, "id", "?"),
        )
        return []

    refreshed: list[dict] = []
    for leg in legs:
        quote = await quote_provider(leg)
        if not isinstance(quote, dict):
            return []
        price = _positive_float(quote.get("price"))
        available_size = _positive_float(quote.get("available_size"))
        if not (0 < price < 1) or available_size <= 0:
            logger.warning(
                "[arb_executor] decision id={} skipped: invalid live quote for {}",
                getattr(row, "id", "?"),
                leg.get("direction"),
            )
            return []
        refreshed.append({**leg, "price": price, "size": min(leg["size"], available_size)})
    return refreshed


def _profitable_legs(row: DecisionLog, signal_data: dict, legs: list[dict]) -> bool:
    fee_pct = _positive_float(signal_data.get("fee_pct"), 0.0)
    slippage_cost = _positive_float(signal_data.get("slippage_cost"), 0.0)
    per_share_cost = sum(leg["price"] for leg in legs)
    computed_net = 1.0 - per_share_cost - fee_pct - slippage_cost
    if computed_net <= 0:
        logger.warning(
            "[arb_executor] decision id={} skipped: fresh executable net is non-positive {}",
            getattr(row, "id", "?"),
            computed_net,
        )
        return False
    return True


async def _unwind_filled_legs(
    filled_payloads: list[dict],
    strategy_name: str,
    mode: str,
    execute_decision_factory,
) -> None:
    for payload in reversed(filled_payloads):
        unwind_payload = {
            **payload,
            "decision": "SELL",
            "side": "SELL",
            "force_unwind": True,
            "reasoning": "ARB bundle incomplete; unwind filled hedge leg",
        }
        try:
            await execute_decision_factory(unwind_payload, strategy_name, mode=mode)
        except Exception as exc:
            logger.error(
                "[arb_executor] unwind failed for bundle {} leg {}: {}",
                payload.get("arb_bundle_id"),
                payload.get("arb_leg_index"),
                exc,
            )


async def execute_arb_decisions(
    rows: list[DecisionLog],
    mode: str = "paper",
    default_max_size: float = 25.0,
    kelly_fraction: float = 0.25,
    execute_decision_factory=execute_decision,
    quote_provider=None,
) -> list[str]:
    if not rows:
        return []

    bankroll = 0.0
    with get_db_session() as db:
        bot_state = db.query(BotState).filter_by(mode=mode).first()
        if bot_state is not None:
            if hasattr(bot_state, "paper_bankroll") and mode == "paper":
                bankroll = float(bot_state.paper_bankroll or 0.0)
            elif hasattr(bot_state, "bankroll") and mode == "live":
                bankroll = float(bot_state.bankroll or 0.0)
            else:
                bankroll = float(getattr(bot_state, "bankroll", 0.0) or 0.0)

    if not bankroll:
        from backend.config import settings as _settings

        bankroll = float(getattr(_settings, "INITIAL_BANKROLL", 50.0))

    processed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    if mode == "live":
        with get_db_session() as arb_db:
            from backend.core.bundle_reconciliation import count_open_incomplete_bundles

            incomplete = count_open_incomplete_bundles(arb_db, mode=mode)
            if incomplete > 0:
                logger.error(
                    "[arb_executor] BLOCKED: {} open incomplete arb bundles exist in {} mode; "
                    "resolve them before placing new arb trades",
                    incomplete,
                    mode,
                )
                # Leave rows unmarked so they are retried once bundles resolve.
                return []

    for row in rows:
        row_id = str(getattr(row, "id", "")) or "unknown"
        try:
            signal_data = _load_signal_data(row)
            legs = _validated_arb_legs(
                row, signal_data, bankroll, kelly_fraction, mode
            )
            if not legs:
                skipped.append(row_id)
                continue
            if mode == "live":
                legs = await _refresh_live_quotes(row, legs, quote_provider)
                if not legs:
                    skipped.append(row_id)
                    continue
                legs = _validated_arb_legs(
                    row,
                    {**signal_data, "legs": legs},
                    bankroll,
                    kelly_fraction,
                    mode,
                )
                if not legs or not _profitable_legs(row, signal_data, legs):
                    skipped.append(row_id)
                    continue

            market_ticker = getattr(row, "market_ticker", "") or signal_data.get("event_id", "")
            strategy_name = getattr(row, "strategy", "unified_pm_arb") or "unified_pm_arb"
            platform = signal_data.get("platform") or signal_data.get("platform_a") or "polymarket"
            bundle_id = f"arb-{row_id}-{market_ticker}"
            results = []
            filled_payloads: list[dict] = []
            for index, leg in enumerate(legs, start=1):
                leg_ticker = leg.get("market_ticker") or f"{market_ticker}:{leg['direction']}"
                payload = {
                    "decision": "BUY",
                    "direction": leg["direction"],
                    "condition_id": market_ticker,
                    "market_ticker": leg_ticker,
                    "platform": leg.get("platform") or platform,
                    "side": "BUY",
                    "size": leg["size"],
                    "price": leg["price"],
                    "entry_price": leg["price"],
                    "token_id": leg.get("token_id", ""),
                    "confidence": getattr(row, "confidence", None),
                    "edge": signal_data.get("net_profit"),
                    "model_probability": 1.0 - leg["price"],
                    "market_type": "arb",
                    "strategy": strategy_name,
                    "arb_bundle_id": bundle_id,
                    "arb_leg_index": index,
                    "arb_leg_count": len(legs),
                    "arb_kind": signal_data.get("kind"),
                }
                result = await execute_decision_factory(
                    payload, strategy_name, mode=mode
                )
                if result is None:
                    logger.error(
                        "[arb_executor] bundle {} leg {} failed; bundle is incomplete",
                        bundle_id,
                        index,
                    )
                    await _unwind_filled_legs(
                        filled_payloads,
                        strategy_name,
                        mode,
                        execute_decision_factory,
                    )
                    results = []
                    break
                results.append(result)
                filled_payloads.append(payload)

            if len(results) == len(legs):
                processed.append(row_id)
                logger.info(
                    "[arb_executor] decision id={} executed as {}-leg bundle {}",
                    row_id,
                    len(legs),
                    bundle_id,
                )
            else:
                failed.append(row_id)
        except Exception as e:
            failed.append(row_id)
            logger.warning(
                "[arb_executor] failed decision id={}: {}",
                getattr(row, "id", "?"),
                str(e),
            )

    _mark_execution_status(processed, "EXECUTED")
    _mark_execution_status(skipped, "SKIPPED")
    _mark_execution_status(failed, "FAILED")
    return processed


async def fetch_pending_arb_decisions(
    mode: str = "paper",
    limit: int = 200,
) -> list[DecisionLog]:
    with get_db_session() as db:
        q = db.query(DecisionLog).filter(
            DecisionLog.decision == "ARB",
            DecisionLog.execution_status.is_(None),
        )
        rows = q.order_by(DecisionLog.created_at.asc()).limit(limit).all()
        # Expunge to avoid detached-instance errors after session closes
        for r in rows:
            db.expunge(r)
        return list(rows)


async def arb_execution_job(
    mode: str = "paper", limit: int = 200, quote_provider=None
) -> None:
    processed: list[str] = []
    try:
        rows = await fetch_pending_arb_decisions(mode=mode, limit=limit)
        if not rows:
            return
        live_quote_provider = quote_provider
        if mode == "live" and live_quote_provider is None:
            live_quote_provider = _default_live_quote_provider
        processed = await execute_arb_decisions(
            rows, mode=mode, quote_provider=live_quote_provider
        )
    except Exception as e:
        logger.error("[arb_executor] job failed: {}", str(e))
    logger.info("[arb_executor] processed {} arb decisions", len(processed))
