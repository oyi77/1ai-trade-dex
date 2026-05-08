"""KalshiProvider — DataProvider implementation for Kalshi exchange."""

from __future__ import annotations
from typing import List, Optional

from backend.data.provider import DataProvider, MarketEntry, PositionEntry, BalanceInfo
from backend.data.kalshi_client import KalshiClient
from backend.data.kalshi_markets import fetch_kalshi_markets


class KalshiProvider(DataProvider):
    @property
    def platform_name(self) -> str:
        return "kalshi"

    async def health_check(self) -> bool:
        try:
            markets = await fetch_kalshi_markets(limit=1)
            return bool(markets)
        except Exception:
            return False

    async def get_markets(self, category: Optional[str] = None, limit: int = 100) -> List[MarketEntry]:
        market_dicts = await fetch_kalshi_markets(limit=limit)
        if category:
            market_dicts = [m for m in market_dicts if m.get("category") == category]
        return [
            MarketEntry(
                ticker=m.get("ticker", m.get("market_id", "")),
                question=m.get("question", m.get("title", "")),
                market_id=m.get("market_id", m.get("id", "")),
                platform="kalshi",
                current_price=float(m.get("last_price", m.get("current_price", 0.0))),
                volume_24h=float(m.get("volume_24h", m.get("volume", 0.0))),
                liquidity=float(m.get("liquidity", 0.0)),
                created_at=m.get("created_at", m.get("open_time", "")),
            )
            for m in market_dicts
        ]

    async def get_orderbook(self, market_id: str) -> dict:
        client = KalshiClient()
        book = await client.get_orderbook(market_id)
        return book if isinstance(book, dict) else {}

    async def get_positions(self) -> List[PositionEntry]:
        client = KalshiClient()
        positions = await client.get_positions()
        if not positions:
            return []
        return [
            PositionEntry(
                market_id=p.get("market_id", p.get("ticker", "")),
                side=p.get("side", ""),
                size=float(p.get("size", p.get("count", 0))),
                entry_price=float(p.get("entry_price", p.get("avg_price", 0))),
                current_price=float(p.get("current_price", p.get("last_price", 0))),
                unrealized_pnl=float(p.get("unrealized_pnl", 0)),
            )
            for p in positions
        ]

    async def get_balance(self) -> BalanceInfo:
        client = KalshiClient()
        balance = await client.get_balance()
        available = float(balance.get("available", balance.get("cash_balance", 0.0)))
        locked = float(balance.get("locked", balance.get("exposure", 0.0)))
        return BalanceInfo(available=available, locked=locked, total=available + locked)

    async def place_order(self, market_id: str, side: str, size: float, price: float, **kwargs) -> dict:
        client = KalshiClient()
        result = await client.place_order(market_id, side, int(size), price)
        return result if isinstance(result, dict) else {"status": "submitted"}

    async def cancel_order(self, order_id: str) -> bool:
        client = KalshiClient()
        return await client.cancel_order(order_id)
