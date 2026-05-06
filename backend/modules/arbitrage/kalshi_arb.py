"""
Kalshi <-> Polymarket Arbitrage Strategy.

Scans for crossed-book opportunities: when Polymarket YES price + Kalshi YES price < 1.0,
there is a guaranteed profit equal to (1 - sum_of_prices) minus fees.

Status: SCAFFOLD — requires KALSHI_API_KEY to activate.
Seeded as enabled=False until credentials are configured.
"""
import logging
from dataclasses import dataclass

from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult, MarketInfo
from backend.config import settings

logger = logging.getLogger("trading_bot")


def _cfg(name, default):
    return getattr(settings, name, default)


@dataclass
class ArbOpportunity:
    poly_ticker: str
    kalshi_ticker: str
    poly_yes_price: float
    kalshi_yes_price: float
    gross_edge: float
    net_edge: float


def compute_arb_edge(poly_yes: float, kalshi_yes: float) -> float:
    """
    Net edge = (1 - poly_yes - kalshi_yes) - fees.
    Positive means guaranteed profit exists.
    """
    gross = 1.0 - poly_yes - kalshi_yes
    fees = _cfg("ARB_POLYMARKET_FEE", 0.02) + _cfg("ARB_KALSHI_FEE", 0.01)
    return gross - fees


class KalshiArbStrategy(BaseStrategy):
    name = "kalshi_arb"
    description = "Kalshi <-> Polymarket arbitrage scanner. Requires KALSHI_API_KEY. Seeded disabled."
    category = "arbitrage"
    default_params = {
        "min_edge": _cfg("ARB_MIN_PROFIT", 0.02),
        "allow_live_execution": False,
        "interval_seconds": 30,
    }

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Filter to markets that have a configured Kalshi equivalent."""
        # MarketWatch rows with source='kalshi_arb' define the pairs
        return markets  # full scan — pair matching done in run_cycle

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        return CycleResult(
            decisions_recorded=0,
            trades_attempted=0,
            trades_placed=0,
            errors=["Kalshi integration not yet implemented"],
        )

