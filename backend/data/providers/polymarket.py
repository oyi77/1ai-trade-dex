from __future__ import annotations
from typing import List, Optional

from backend.data.provider import DataProvider, MarketEntry, PositionEntry, BalanceInfo
from backend.data.gamma import fetch_markets
from backend.data.polymarket_clob import PolymarketCLOB

class PolymarketProvider(DataProvider):
    @property
    def platform_name(self) -> str:
        return "polymarket"

    async def health_check(self) -> bool:
        try:
            markets = await fetch_markets(limit=1)
            return bool(markets)
        except Exception:
            return False

    async def get_markets(self, category: Optional[str] = None, limit: int = 100) -> List[MarketEntry]:
        market_dicts = await fetch_markets(limit=limit)
        if category:
            market_dicts = [m for m in market_dicts if m.get("category") == category]
        return [
            MarketEntry(
                ticker=m.get("ticker", m.get("market_id", "")),
                question=m.get("question", m.get("title", "")),
                market_id=m.get("market_id", m.get("id", "")),
                platform="polymarket",
                current_price=float(m.get("current_price", 0.0)),
                volume_24h=float(m.get("volume_24h", 0.0)),
                liquidity=float(m.get("liquidity", 0.0)),
                created_at=m.get("created_at", m.get("creation_time", "")),
            )
            for m in market_dicts
        ]

    async def get_orderbook(self, market_id: str) -> dict:
        async with PolymarketCLOB() as clob:
            book = await clob.get_order_book(market_id)
            return book.__dict__ if hasattr(book, "__dict__") else book

    async def get_positions(self) -> List[PositionEntry]:
        async with PolymarketCLOB() as clob:
            wallet = getattr(clob, "builder_address", None)
            if not wallet:
                return []
            return [
                PositionEntry(
                    market_id=p.get("market_id", ""),
                    side=p.get("side", ""),
                    size=float(p.get("size", 0)),
                    entry_price=float(p.get("entry_price", 0)),
                    current_price=float(p.get("current_price", 0)),
                    unrealized_pnl=float(p.get("unrealized_pnl", 0)),
                )
                for p in await clob.get_trader_positions(wallet)
            ]

    async def get_balance(self) -> BalanceInfo:
        async with PolymarketCLOB() as clob:
            b = await clob.get_wallet_balance()
            usdc = float(b.get("usdc_balance", 0.0))
            return BalanceInfo(available=usdc, locked=0.0, total=usdc)

    async def place_order(self, market_id: str, side: str, size: float, price: float, **kwargs) -> dict:
        async with PolymarketCLOB() as clob:
            result = await clob.place_limit_order(market_id, side, price, size)
            return result.__dict__ if hasattr(result, "__dict__") else result

    async def cancel_order(self, order_id: str) -> bool:
        async with PolymarketCLOB() as clob:
            return await clob.cancel_order(order_id)
