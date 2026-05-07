"""
BTC 5-Minute Momentum Strategy (EXPERIMENTAL — DISABLED).

WARNING: This strategy has documented negative live EV: 4W/11L, -49.5% ROI
with technical indicators on binary 5-min markets. Do NOT enable in live mode
without comprehensive re-validation.

This wrapper preserves the existing logic for paper-mode research only.
For production BTC trading, use btc_oracle strategy instead.
"""

import logging

from backend.strategies.base import (
    BaseStrategy,
    StrategyContext,
    CycleResult,
    MarketInfo,
)

logger = logging.getLogger("trading_bot")

EXPERIMENTAL_WARNING = (
    "EXPERIMENTAL — documented -49.5% live ROI on 4W/11L sample. "
    "Do not enable in live mode without re-validation."
)


class BtcMomentumStrategy(BaseStrategy):
    name = "btc_momentum"
    description = f"BTC 5-min momentum (EXPERIMENTAL). {EXPERIMENTAL_WARNING}"
    category = "experimental"
    default_params = {
        "WARNING": EXPERIMENTAL_WARNING,
        "interval_seconds": 60,
        "max_trades_per_scan": 2,
        "max_trade_fraction": 0.03,
        "_force_disabled": True,
    }

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Filter to BTC 5-min binary markets."""
        return [
            m for m in markets if "btc" in m.slug.lower() and "5m" in m.slug.lower()
        ]

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(
            decisions_recorded=0,
            trades_attempted=0,
            trades_placed=0,
        )

        # HARD DISABLE: This strategy has documented negative EV (-49.5% ROI)
        # and data analysis shows 40% win rate on 50/50 markets with
        # up-direction bias (16L/8W up, 9/9 down). The model_prob clamped
        # to [0.40, 0.60] produces near-zero edge that doesn't cover
        # transaction costs. Disabled until fundamental rework.
        logger.info(f"BtcMomentumStrategy: DISABLED — {EXPERIMENTAL_WARNING}")
        return result
