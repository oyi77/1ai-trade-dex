"""Arb execution bridge.

Reads DecisionLog rows with `decision == 'ARB'` and re-dispatches them
through `execute_decision`. This is the missing link between arb detection
in `UnifiedPMArb` and trade execution.

Audit marks are intentionally omitted because `DecisionLog` does not have
an `execution_status`/`executed_at` column in the current schema.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from loguru import logger

from backend.core.strategy_executor import execute_decision
from backend.db.utils import get_db_session
from backend.models.database import DecisionLog, BotState


async def execute_arb_decisions(
    rows: list[DecisionLog],
    mode: str = "paper",
    default_max_size: float = 25.0,
    kelly_fraction: float = 0.25,
    execute_decision_factory=execute_decision,
) -> list[str]:
    if not rows:
        return []

    bot_state: BotState | None = None
    with get_db_session() as db:
        bot_state = db.query(BotState).filter_by(mode=mode).first()

    bankroll = 0.0
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

    async def _run_one(row: DecisionLog, payload: dict, strategy_name: str) -> str:
        result = await execute_decision_factory(payload, strategy_name, mode=mode)
        status = "executed" if result is not None else "skipped"
        logger.info(
            "[arb_executor] decision id={} status={}", getattr(row, "id", "?"), status
        )
        return str(getattr(row, "id", "")) or ""

    for row in rows:
        try:
            signal_data: dict = {}
            raw_signal = getattr(row, "signal_data", None)
            if isinstance(raw_signal, str) and raw_signal.strip():
                try:
                    import json as _json
                    signal_data = _json.loads(raw_signal)
                except Exception:
                    signal_data = {}
            elif isinstance(raw_signal, dict):
                signal_data = raw_signal
            else:
                signal_data = {}

            size = float(signal_data.get("size") or default_max_size)
            size = min(size, bankroll * kelly_fraction)
            price = float(
                signal_data.get("model_probability")
                or signal_data.get("price")
                or 0.5
            )
            token_id = signal_data.get("token_id") or ""
            market_ticker = getattr(row, "market_ticker", "") or ""
            strategy_name = getattr(row, "strategy", "unified_pm_arb") or "unified_pm_arb"

            payload = {
                "decision": "BUY",
                "direction": "YES",
                "condition_id": market_ticker,
                "market_ticker": market_ticker,
                "platform": signal_data.get("platform_a", ""),
                "platform_a": signal_data.get("platform_a", ""),
                "platform_b": signal_data.get("platform_b", ""),
                "price_a": signal_data.get("price_a"),
                "price_b": signal_data.get("price_b"),
                "side": "BUY",
                "size": size,
                "price": price,
                "token_id": token_id,
                "confidence": getattr(row, "confidence", None),
                "edge": signal_data.get("net_profit"),
                "model_probability": price,
                "market_type": "arb",
                "strategy": strategy_name,
            }
            processed.append(await _run_one(row, payload, strategy_name))
        except Exception as e:
            logger.warning(
                "[arb_executor] failed decision id={}: {}",
                getattr(row, "id", "?"),
                str(e),
            )
    return processed


async def fetch_pending_arb_decisions(
    mode: str = "paper",
    limit: int = 200,
) -> list[DecisionLog]:
    with get_db_session() as db:
        q = db.query(DecisionLog).filter(DecisionLog.decision == "ARB")
        rows = q.order_by(DecisionLog.created_at.asc()).limit(limit).all()
        return list(rows)


async def arb_execution_job(mode: str = "paper", limit: int = 200) -> None:
    processed: list[str] = []
    try:
        rows = await fetch_pending_arb_decisions(mode=mode, limit=limit)
        if not rows:
            return
        processed = await execute_arb_decisions(rows, mode=mode)
    except Exception as e:
        logger.error("[arb_executor] job failed: {}", str(e))
    logger.info("[arb_executor] processed {} arb decisions", len(processed))
