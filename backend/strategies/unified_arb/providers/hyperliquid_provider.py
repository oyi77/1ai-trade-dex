"""Hyperliquid DEX provider — detection only (execution deferred)."""

import asyncio
import logging
from typing import List, Union

from backend.strategies.unified_arb.types import DEXProvider, FeeSchedule, SpotMarket

logger = logging.getLogger(__name__)


class HyperliquidProvider(DEXProvider):
    venue_name = "hyperliquid"

    async def fetch_markets(self, limit: int = 500) -> List[SpotMarket]:
        """Fetch Hyperliquid prices via L2 orderbook snapshots."""

        def _sync_fetch():
            from hyperliquid.info import Info
            from hyperliquid.utils import constants as hl_constants

            info = Info(hl_constants.MAINNET_API_URL, skip_ws=True)
            mids = info.all_mids()
            books = {}
            for name in list(mids.keys())[:limit]:
                if name.startswith("#"):
                    continue
                try:
                    l2 = info.l2_snapshot(name)
                    if l2 and "levels" in l2:
                        levels = l2["levels"]
                        bids = levels[0] if len(levels) > 0 else []
                        asks = levels[1] if len(levels) > 1 else []
                        best_bid = float(bids[0]["px"]) if bids else 0
                        best_ask = float(asks[0]["px"]) if asks else 0
                        if best_bid > 0 and best_ask > 0 and best_bid < best_ask:
                            books[name] = (best_bid, best_ask)
                except Exception:
                    pass
            return mids, books

        try:
            mids, books = await asyncio.to_thread(_sync_fetch)
            quotes = []
            for name, mid in mids.items():
                if name.startswith("#"):
                    continue
                if name in books:
                    bid, ask = books[name]
                    spread_pct = (ask - bid) / mid if mid > 0 else 0
                    if spread_pct > 0.02:
                        continue
                    quotes.append(SpotMarket(
                        exchange="hyperliquid",
                        base=name,
                        bid=bid,
                        ask=ask,
                        mid=mid,
                        fee_pct=0.0005,
                    ))
            return quotes[:limit]
        except Exception as e:
            logger.warning(f"[hyperliquid_provider] fetch failed: {e}")
            return []

    def get_fee_schedule(self) -> FeeSchedule:
        return FeeSchedule(taker_fee_pct=0.0005, maker_fee_pct=0.0, slippage_bps=5)
