"""Polymarket CLOB execution client."""

from .models import OrderResult, OrderBook, TradeRecord
from .helpers import (
    ensure_token_id,
    clob_breaker,
    CLOB_HOST,
    GAMMA_HOST,
    DATA_HOST,
    CHAIN_ID,
    _check_and_claim_idempotency,
    _release_idempotency_key,
    _inflight_keys,
    _inflight_lock,
)
from .client import PolymarketCLOB
from .factory import clob_from_settings

# Re-export for Prometheus metric used by test_maker_first.py
from backend.monitoring.hft_metrics import record_maker_fill_rate

__all__ = [
    "OrderResult",
    "OrderBook",
    "TradeRecord",
    "PolymarketCLOB",
    "clob_from_settings",
    "ensure_token_id",
    "clob_breaker",
    "CLOB_HOST",
    "GAMMA_HOST",
    "DATA_HOST",
    "CHAIN_ID",
    "_check_and_claim_idempotency",
    "_release_idempotency_key",
    "_inflight_keys",
    "_inflight_lock",
]
