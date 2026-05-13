"""Market data types and generic market fetching."""
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass

from backend.data.btc_markets import BtcMarket, fetch_active_btc_markets
from backend.core.market_scanner import fetch_all_active_markets


@dataclass
class MarketData:
    """Structured market data."""
    platform: str
    ticker: str
    title: str
    category: str
    subcategory: Optional[str]

    yes_price: float  # 0-1 (Up price for BTC markets)
    no_price: float   # (Down price for BTC markets)
    volume: float
    settlement_time: Optional[datetime]

    threshold: Optional[float] = None
    direction: Optional[str] = None

    event_slug: Optional[str] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None


def btc_market_to_market_data(btc: BtcMarket) -> MarketData:
    """Convert a BtcMarket to the generic MarketData format."""
    return MarketData(
        platform="polymarket",
        ticker=btc.market_id,
        title=f"BTC Up or Down 5m - {btc.slug}",
        category="crypto",
        subcategory="btc-5m",
        yes_price=btc.up_price,
        no_price=btc.down_price,
        volume=btc.volume,
        settlement_time=btc.window_end,
        event_slug=btc.slug,
        window_start=btc.window_start,
        window_end=btc.window_end,
    )


async def fetch_all_markets(**kwargs) -> List[MarketData]:
    """Fetch active markets across the Polymarket universe.

    Falls back to the BTC helper only if broad Gamma market scanning fails.
    """
    try:
        markets = await fetch_all_active_markets(
            category=kwargs.get("category"),
            limit=kwargs.get("limit"),
        )
        results: list[MarketData] = []
        for market in markets:
            settlement_time = None
            if market.end_date:
                try:
                    settlement_time = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
                except ValueError:
                    settlement_time = None
            results.append(
                MarketData(
                    platform="polymarket",
                    ticker=market.ticker,
                    title=market.question or market.slug,
                    category=market.category or "general",
                    subcategory=None,
                    yes_price=market.yes_price,
                    no_price=market.no_price,
                    volume=market.volume,
                    settlement_time=settlement_time,
                    event_slug=market.slug,
                    window_end=settlement_time,
                )
            )
        return results
    except Exception:
        from loguru import logger

        logger.exception("fetch_all_markets broad scan failed; falling back to BTC markets")
        btc_markets = await fetch_active_btc_markets()
        return [btc_market_to_market_data(m) for m in btc_markets]
