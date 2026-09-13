"""
Polymarket CLOB execution client.

Uses httpx.AsyncClient for read-only queries (shared connection pool).
Delegates order creation/placement/cancellation to py_clob_client_v2.ClobClient,
which handles EIP-712 signing, L2 HMAC auth, and tick-size resolution internally.

Auth: EIP-712 L1 (derive API keys) + HMAC-SHA256 L2 (per-request headers).
All order sizes in USDC. All prices in [0.01, 0.99].
"""

import asyncio
import hashlib
import time
from typing import Optional

import httpx
from eth_account import Account
from eth_account.signers.local import LocalAccount

from py_clob_client_v2 import (
    ClobClient,
    ApiCreds,
    BuilderConfig,
    OrderArgs,
    BalanceAllowanceParams,
    AssetType,
    OrderPayload,
)

from backend.core.risk.circuit_breaker_pybreaker import polymarket_breaker
from backend.config import settings, _cfg
from backend.data.shared_client import get_shared_client

from loguru import logger
from backend.monitoring.hft_metrics import record_maker_fill_rate

from .models import OrderResult, OrderBook, TradeRecord
from .helpers import (
    ensure_token_id,
    _check_and_claim_idempotency,
    _release_idempotency_key,
    clob_breaker,
    CLOB_HOST,
    GAMMA_HOST,
    DATA_HOST,
    CHAIN_ID,
    _inflight_lock,
)

from ._client_get_wallet_balance import (
    PolymarketCLOBMixin3,
)

from ._client_place_limit_order import (
    PolymarketCLOBMixin2,
)

from ._client_simulation import (
    PolymarketCLOBMixin,
)

class PolymarketCLOB(PolymarketCLOBMixin, PolymarketCLOBMixin2, PolymarketCLOBMixin3):
    """
    Async Polymarket CLOB client with shared httpx connection pool.

    Usage (paper mode — no keys needed):
        async with PolymarketCLOB() as clob:
            book = await clob.get_order_book(token_id)
            mid = book.mid_price

    Usage (live mode):
        async with PolymarketCLOB(private_key=pk, api_key=k, api_secret=s, api_passphrase=p) as clob:
            result = await clob.place_limit_order(token_id, side="BUY", price=0.65, size=50.0)
    """


__all__ = [
    "Account",
    "ApiCreds",
    "AssetType",
    "BalanceAllowanceParams",
    "BuilderConfig",
    "CHAIN_ID",
    "CLOB_HOST",
    "ClobClient",
    "DATA_HOST",
    "GAMMA_HOST",
    "LocalAccount",
    "Optional",
    "OrderArgs",
    "OrderBook",
    "OrderPayload",
    "OrderResult",
    "PolymarketCLOBMixin",
    "PolymarketCLOBMixin2",
    "PolymarketCLOBMixin3",
    "TradeRecord",
    "_cfg",
    "_check_and_claim_idempotency",
    "_inflight_lock",
    "_release_idempotency_key",
    "asyncio",
    "clob_breaker",
    "ensure_token_id",
    "get_shared_client",
    "hashlib",
    "httpx",
    "logger",
    "polymarket_breaker",
    "record_maker_fill_rate",
    "settings",
    "time",
]
