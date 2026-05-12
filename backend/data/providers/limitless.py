"""LimitlessProvider — DataProvider implementation for limitless.exchange.

limitless.exchange is a CLOB + AMM prediction market on Base blockchain.

REST API:  https://api.limitless.exchange  (Swagger: /api-v1)
WebSocket: wss://ws.limitless.exchange

Authentication:
- Public reads (markets, orderbook) require no auth.
- Order placement requires EIP-712 wallet signature via eth_account.

ENV VARS:
    LIMITLESS_API_URL  — REST base URL (default: https://api.limitless.exchange)
    LIMITLESS_WS_URL   — WebSocket URL (default: wss://ws.limitless.exchange)
    LIMITLESS_PRIVATE_KEY — EVM private key for order signing (never logged)
"""

from __future__ import annotations

import os
from typing import Optional

import httpx
from loguru import logger

from backend.data.provider import DataProvider, MarketEntry, PositionEntry, BalanceInfo

_LIMITLESS_API_DEFAULT = "https://api.limitless.exchange"


class LimitlessProvider(DataProvider):
    """DataProvider for limitless.exchange CLOB+AMM prediction market."""

    def __init__(self) -> None:
        self._base_url = os.getenv("LIMITLESS_API_URL", _LIMITLESS_API_DEFAULT).rstrip("/")

    @property
    def platform_name(self) -> str:
        return "limitless"

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}/markets", params={"limit": 1})
                return resp.status_code == 200
        except Exception:
            logger.debug("Limitless health check failed")
            return False

    async def get_markets(
        self, category: Optional[str] = None, limit: int = 100
    ) -> list[MarketEntry]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self._base_url}/markets",
                    params={"limit": limit},
                )
                resp.raise_for_status()
                raw_markets = resp.json()
        except Exception as exc:
            logger.warning("LimitlessProvider.get_markets failed: {}", exc)
            return []

        if isinstance(raw_markets, dict):
            raw_markets = raw_markets.get("markets") or raw_markets.get("data") or []

        entries: list[MarketEntry] = []
        for m in raw_markets:
            if category and m.get("category", "").lower() != category.lower():
                continue
            entries.append(
                MarketEntry(
                    ticker=m.get("id", m.get("marketId", "")),
                    question=m.get("title", m.get("question", "")),
                    market_id=m.get("id", m.get("marketId", "")),
                    platform="limitless",
                    current_price=float(m.get("price", m.get("currentPrice", 0.5))),
                    volume_24h=float(m.get("volume24h", m.get("volume", 0.0))),
                    liquidity=float(m.get("liquidity", 0.0)),
                    created_at=m.get("createdAt", m.get("created_at", "")),
                )
            )
        return entries

    async def get_orderbook(self, market_id: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self._base_url}/orderbook",
                    params={"marketId": market_id},
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("LimitlessProvider.get_orderbook failed: {}", exc)
            return {"bids": [], "asks": [], "market_id": market_id}

    async def get_positions(self) -> list[PositionEntry]:
        wallet = os.getenv("LIMITLESS_WALLET_ADDRESS", "")
        if not wallet:
            return []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{self._base_url}/portfolio/{wallet}")
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("LimitlessProvider.get_positions failed: {}", exc)
            return []

        positions = data.get("positions", []) if isinstance(data, dict) else []
        return [
            PositionEntry(
                market_id=p.get("marketId", ""),
                side=p.get("side", ""),
                size=float(p.get("size", 0.0)),
                entry_price=float(p.get("entryPrice", 0.0)),
                current_price=float(p.get("currentPrice", 0.0)),
                unrealized_pnl=float(p.get("unrealizedPnl", 0.0)),
            )
            for p in positions
        ]

    async def get_balance(self) -> BalanceInfo:
        wallet = os.getenv("LIMITLESS_WALLET_ADDRESS", "")
        if not wallet:
            return BalanceInfo(available=0.0, locked=0.0, total=0.0)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{self._base_url}/portfolio/{wallet}")
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("LimitlessProvider.get_balance failed: {}", exc)
            return BalanceInfo(available=0.0, locked=0.0, total=0.0)

        balance = data.get("balance", {}) if isinstance(data, dict) else {}
        available = float(balance.get("available", 0.0))
        locked = float(balance.get("locked", 0.0))
        return BalanceInfo(available=available, locked=locked, total=available + locked)

    async def place_order(
        self, market_id: str, side: str, size: float, price: float, **kwargs
    ) -> dict:
        """Place a limit order via EIP-712 signed payload.

        Requires LIMITLESS_PRIVATE_KEY env var or private_key kwarg.
        Full EIP-712 signing is planned in plugin-system task 26d.
        """
        private_key: str = kwargs.get("private_key", os.getenv("LIMITLESS_PRIVATE_KEY", ""))
        if not private_key:
            logger.warning("LimitlessProvider.place_order: no private key — dry-run")
            return {"orderId": "", "status": "dry_run", "platform": "limitless"}

        # TODO(task-26d): implement EIP-712 sign + POST /orders
        # Stub returns dry-run until plugin-system refactoring is merged
        logger.info(
            "LimitlessProvider.place_order dry-run: market_id={} side={} size={} price={}",
            market_id,
            side,
            size,
            price,
        )
        return {"orderId": "", "status": "dry_run", "platform": "limitless"}

    async def cancel_order(self, order_id: str) -> bool:
        private_key: str = os.getenv("LIMITLESS_PRIVATE_KEY", "")
        if not private_key:
            logger.warning("LimitlessProvider.cancel_order: no private key")
            return False

        # TODO(task-26d): implement signed DELETE /orders/{order_id}
        logger.info("LimitlessProvider.cancel_order dry-run: order_id={}", order_id)
        return False
