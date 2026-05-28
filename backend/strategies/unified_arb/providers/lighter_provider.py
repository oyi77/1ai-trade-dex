"""Lighter DEX provider — detection only (execution deferred)."""

import logging
from typing import List, Union

from backend.strategies.unified_arb.types import DEXProvider, FeeSchedule, SpotMarket

logger = logging.getLogger(__name__)


class LighterProvider(DEXProvider):
    venue_name = "lighter"

    async def fetch_markets(self, limit: int = 500) -> List[SpotMarket]:
        """Fetch Lighter prices via LighterClient."""
        try:
            from backend.clients.lighter_client import LighterClient

            client = LighterClient()
            orderbooks = await client.get_orderbooks()
            quotes = []
            for ob in (orderbooks or []):
                if not isinstance(ob, dict):
                    continue
                base = ob.get("symbol", "")
                bids = ob.get("bids", [])
                asks = ob.get("asks", [])
                if not bids or not asks:
                    continue
                best_bid = float(bids[0].get("price", 0) if isinstance(bids[0], dict) else bids[0][0])
                best_ask = float(asks[0].get("price", 0) if isinstance(asks[0], dict) else asks[0][0])
                if best_bid <= 0 or best_ask <= 0:
                    continue
                mid = (best_bid + best_ask) / 2
                spread_pct = (best_ask - best_bid) / mid
                if spread_pct > 0.02:
                    continue
                quotes.append(SpotMarket(
                    exchange="lighter",
                    base=base,
                    bid=best_bid,
                    ask=best_ask,
                    mid=mid,
                    fee_pct=0.0,
                ))
            return quotes[:limit]
        except Exception as e:
            logger.warning(f"[lighter_provider] fetch failed: {e}")
            return []

    def get_fee_schedule(self) -> FeeSchedule:
        return FeeSchedule(taker_fee_pct=0.0, maker_fee_pct=0.0, slippage_bps=5)
