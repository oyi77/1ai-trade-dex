"""Helpers for recording trade execution attempts for operator observability."""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.models.database import TradeAttempt
from backend.db.utils import utcnow


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, default=str, sort_keys=True)
    except (TypeError, ValueError):
        return json.dumps({"unserializable": str(value)}, sort_keys=True)


def make_reason_code(reason: str | None, prefix: str = "REJECTED") -> str:
    """Convert arbitrary operator text into a stable machine-readable code."""

    text_value = (reason or "unknown").strip().lower()
    if "duplicate" in text_value:
        suffix = "DUPLICATE_OPEN_POSITION"
    elif "bot not running" in text_value or "not running" in text_value:
        suffix = "BOT_NOT_RUNNING"
    elif "no execution context" in text_value:
        suffix = "NO_EXECUTION_CONTEXT"
    elif "confidence" in text_value:
        suffix = "LOW_CONFIDENCE"
    elif "daily loss" in text_value or "drawdown" in text_value:
        suffix = "DRAWDOWN_BREAKER"
    elif "max exposure" in text_value:
        suffix = "MAX_EXPOSURE"
    elif "slippage" in text_value:
        suffix = "SLIPPAGE_LIMIT"
    elif "below minimum" in text_value or "minimum" in text_value:
        suffix = "ORDER_TOO_SMALL"
    elif "token" in text_value:
        suffix = "MISSING_TOKEN_ID"
    elif "clob" in text_value or "broker" in text_value or "order" in text_value:
        suffix = "BROKER_REJECTED"
    elif "validation" in text_value:
        suffix = "VALIDATION_FAILED"
    else:
        cleaned = "".join(ch if ch.isalnum() else "_" for ch in text_value.upper())
        suffix = "_".join(part for part in cleaned.split("_") if part)[:64] or "UNKNOWN"
    return f"{prefix}_{suffix}"


class TradeAttemptRecorder:
    """Records one mutable attempt row, finalized as execution progresses."""

    def __init__(
        self, db: Session, decision: dict[str, Any], strategy_name: str, mode: str
    ):
        self.db = db
        self.started_at = time.perf_counter()
        self.attempt = TradeAttempt(
            attempt_id=str(uuid4()),
            correlation_id=str(
                decision.get("correlation_id") or decision.get("attempt_id") or uuid4()
            ),
            strategy=strategy_name,
            mode=mode,
            market_ticker=str(decision.get("market_ticker") or "unknown"),
            platform=decision.get("platform", "polymarket"),
            direction=decision.get("direction"),
            decision=decision.get("decision", "BUY"),
            status="STARTED",
            phase="created",
            reason_code="ATTEMPT_STARTED",
            reason="Execution attempt created",
            confidence=_safe_float(decision.get("confidence")),
            edge=_safe_float(decision.get("edge")),
            requested_size=_safe_float(decision.get("size")),
            entry_price=_safe_float(decision.get("entry_price")),
            decision_data=_json_dumps(decision),
            signal_data=_json_dumps(
                {
                    "reasoning": decision.get("reasoning"),
                    "model_probability": decision.get("model_probability"),
                    "market_type": decision.get("market_type"),
                    "token_id_present": bool(decision.get("token_id")),
                }
            ),
        )
        self.db.add(self.attempt)
        self.db.flush()

    def update(self, **fields: Any) -> None:
        for key, value in fields.items():
            if key in {
                "factors_json",
                "decision_data",
                "signal_data",
            } and not isinstance(value, (str, type(None))):
                value = _json_dumps(value)
            setattr(self.attempt, key, value)
        self.attempt.updated_at = utcnow()
        self.db.flush()

    def record_blocked(
        self, reason: str, *, phase: str, reason_code: str | None = None, **fields: Any
    ) -> None:
        self.update(
            status="BLOCKED",
            phase=phase,
            reason=reason,
            reason_code=reason_code or make_reason_code(reason, "BLOCKED"),
            latency_ms=self.elapsed_ms,
            **fields,
        )

    def record_rejected(
        self, reason: str, *, phase: str, reason_code: str | None = None, **fields: Any
    ) -> None:
        self.update(
            status="REJECTED",
            phase=phase,
            reason=reason,
            reason_code=reason_code or make_reason_code(reason, "REJECTED"),
            latency_ms=self.elapsed_ms,
            **fields,
        )

    def record_executed(
        self, trade_id: int, reason: str = "Trade opened", **fields: Any
    ) -> None:
        self.update(
            status="EXECUTED",
            phase="completed",
            reason=reason,
            reason_code="EXECUTED_TRADE_OPENED",
            trade_id=trade_id,
            latency_ms=self.elapsed_ms,
            **fields,
        )

    def record_failed(
        self, reason: str, *, phase: str = "error", **fields: Any
    ) -> None:
        self.update(
            status="FAILED",
            phase=phase,
            reason=reason,
            reason_code=make_reason_code(reason, "FAILED"),
            latency_ms=self.elapsed_ms,
            **fields,
        )

    @property
    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.started_at) * 1000, 3)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
