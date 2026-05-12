from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
@dataclass
class ShadowTrade:
    market_ticker: str
    direction: str
    entry_price: float
    size: float
    model_probability: float
    timestamp: datetime
    strategy: str
    settled: bool = False
    settlement_value: Optional[float] = None
    pnl: Optional[float] = None


@dataclass
class ShadowPerformance:
    total_trades: int
    settled_trades: int
    total_pnl: float
    win_rate: float
    avg_edge: float
    strategy_breakdown: dict[str, float]  # strategy -> pnl


class ShadowRunner:
    def __init__(self):
        self._trades: list[ShadowTrade] = []

    def record_signal(
        self,
        market_ticker: str,
        direction: str,
        entry_price: float,
        size: float,
        model_prob: float,
        strategy: str,
    ) -> ShadowTrade:
        """Record a shadow trade (no execution)."""
        trade = ShadowTrade(
            market_ticker=market_ticker,
            direction=direction,
            entry_price=entry_price,
            size=size,
            model_probability=model_prob,
            timestamp=datetime.now(timezone.utc),
            strategy=strategy,
        )
        self._trades.append(trade)
        logger.info(
            "Shadow trade recorded: %s %s @ %.4f size=%.2f strategy=%s",
            direction,
            market_ticker,
            entry_price,
            size,
            strategy,
        )
        return trade

    def settle(self, market_ticker: str, settlement_value: float) -> None:
        """Settle all unsettled shadow trades for this ticker, calculating P&L."""
        for trade in self._trades:
            if trade.market_ticker != market_ticker or trade.settled:
                continue
            trade.settlement_value = settlement_value
            trade.settled = True
            # P&L: if direction=up and settlement=1.0 (up won), we win (1 - entry_price) * size
            # if direction=down and settlement=0.0 (down won), we win (1 - entry_price) * size
            direction_won = (
                (trade.direction == "up" and settlement_value == 1.0)
                or (trade.direction == "down" and settlement_value == 0.0)
            )
            if direction_won:
                trade.pnl = (1.0 - trade.entry_price) * trade.size
            else:
                trade.pnl = -trade.entry_price * trade.size
            logger.info(
                "Shadow trade settled: %s %s pnl=%.4f",
                trade.market_ticker,
                trade.direction,
                trade.pnl,
            )

    def get_performance(self) -> ShadowPerformance:
        """Compute aggregate performance metrics."""
        settled = [t for t in self._trades if t.settled and t.pnl is not None]
        total_pnl = sum(t.pnl for t in settled)
        wins = sum(1 for t in settled if t.pnl > 0)
        win_rate = wins / len(settled) if settled else 0.0

        # avg_edge: average of (model_probability - entry_price) across all trades
        all_trades = self._trades
        avg_edge = (
            sum(t.model_probability - t.entry_price for t in all_trades) / len(all_trades)
            if all_trades
            else 0.0
        )

        strategy_breakdown: dict[str, float] = {}
        for t in settled:
            strategy_breakdown[t.strategy] = strategy_breakdown.get(t.strategy, 0.0) + t.pnl

        return ShadowPerformance(
            total_trades=len(self._trades),
            settled_trades=len(settled),
            total_pnl=total_pnl,
            win_rate=win_rate,
            avg_edge=avg_edge,
            strategy_breakdown=strategy_breakdown,
        )

    def compare_with_live(self, live_pnl: float) -> dict:
        """Compare shadow vs live performance."""
        perf = self.get_performance()
        shadow_pnl = perf.total_pnl
        return {
            "shadow_pnl": shadow_pnl,
            "live_pnl": live_pnl,
            "difference": shadow_pnl - live_pnl,
            "shadow_better": shadow_pnl > live_pnl,
        }
