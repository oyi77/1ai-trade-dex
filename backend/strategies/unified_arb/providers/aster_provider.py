"""Aster DEX provider — detection only (execution deferred)."""

import logging
from typing import List, Union

from backend.strategies.unified_arb.types import DEXProvider, FeeSchedule, SpotMarket

logger = logging.getLogger(__name__)


class AsterProvider(DEXProvider):
    venue_name = "aster"

    async def fetch_markets(self, limit: int = 500) -> List[SpotMarket]:
        """Fetch Aster prices via ccxt."""
        try:
            from backend.clients.aster_client import AsterClient

            client = AsterClient()
            tickers = await client.fetch_tickers()
            quotes = []
            for symbol, ticker in (tickers or {}).items():
                if not isinstance(ticker, dict):
                    continue
                bid = float(ticker.get("bid", 0) or 0)
                ask = float(ticker.get("ask", 0) or 0)
                mid = float(ticker.get("last", 0) or 0)
                if bid <= 0 or ask <= 0 or mid <= 0:
                    continue
                spread_pct = (ask - bid) / mid
                if spread_pct > 0.02:
                    continue
                base = symbol.split("/")[0] if "/" in symbol else symbol
                quotes.append(SpotMarket(
                    exchange="aster",
                    base=base,
                    bid=bid,
                    ask=ask,
                    mid=mid,
                    fee_pct=0.00035,
                ))
            return quotes[:limit]
        except Exception as e:
            logger.warning(f"[aster_provider] fetch failed: {e}")
            return []

    def get_fee_schedule(self) -> FeeSchedule:
        return FeeSchedule(taker_fee_pct=0.00035, maker_fee_pct=0.0, slippage_bps=5)
