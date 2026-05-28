"""Ostium DEX provider — detection only (execution deferred)."""

import logging
from typing import List, Union

from backend.strategies.unified_arb.types import DEXProvider, FeeSchedule, SpotMarket

logger = logging.getLogger(__name__)


class OstiumProvider(DEXProvider):
    venue_name = "ostium"

    async def fetch_markets(self, limit: int = 500) -> List[SpotMarket]:
        """Fetch Ostium prices via subgraph — real bid/ask only."""
        try:
            from backend.clients.ostium_client import OstiumClient

            client = OstiumClient()
            markets = await client.get_markets()
            quotes = []
            for m in markets:
                if hasattr(m, "__dict__") and not isinstance(m, dict):
                    m = m.__dict__
                if not isinstance(m, dict):
                    continue
                base = m.get("base_symbol") or m.get("from") or m.get("name") or m.get("pair", "")
                if not base:
                    continue
                bid_val = 0.0
                ask_val = 0.0
                for key in ("best_bid", "bid", "bid_price"):
                    val = m.get(key)
                    if val is not None:
                        try:
                            bid_val = float(val)
                            if bid_val > 0:
                                break
                        except (ValueError, TypeError):
                            pass
                for key in ("best_ask", "ask", "ask_price"):
                    val = m.get(key)
                    if val is not None:
                        try:
                            ask_val = float(val)
                            if ask_val > 0:
                                break
                        except (ValueError, TypeError):
                            pass
                if bid_val > 0 and ask_val > 0 and bid_val < ask_val:
                    spread_pct = (ask_val - bid_val) / ((bid_val + ask_val) / 2)
                    if spread_pct > 0.02:
                        continue
                    quotes.append(SpotMarket(
                        exchange="ostium",
                        base=str(base).split("/")[0].split("-")[0],
                        bid=bid_val,
                        ask=ask_val,
                        mid=(bid_val + ask_val) / 2,
                        fee_pct=0.005,
                    ))
                # Skip assets without real bid/ask (no fake spreads)
            return quotes[:limit]
        except Exception as e:
            logger.warning(f"[ostium_provider] fetch failed: {e}")
            return []

    def get_fee_schedule(self) -> FeeSchedule:
        return FeeSchedule(taker_fee_pct=0.005, maker_fee_pct=0.0, slippage_bps=10)
