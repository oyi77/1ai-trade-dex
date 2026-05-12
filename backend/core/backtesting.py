"""
Backtesting engine for PolyEdge strategies.

DEPRECATED: Use backend.core.backtester instead.
This module uses random.random() for unexecuted signals, producing
non-deterministic results. The backtester module only replays actual
DB records (signals + trades) and computes all metrics deterministically.

The run_backtest_engine() helper in backend.api.backtest still exists
for any code that directly imports it, but the /api/backtest/run
endpoint now uses backend.core.backtester.BacktestEngine exclusively.
"""

import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from sqlalchemy.orm import Session

from loguru import logger

from backend.models.database import Trade, Signal

warnings.warn(
    "backend.core.backtesting is deprecated — use backend.core.backtester instead. "
    "This module uses random.random() for unexecuted signals, producing non-deterministic results.",
    DeprecationWarning,
    stacklevel=2,
)


@dataclass
class BacktestConfig:
    """Configuration for backtest run."""

    initial_bankroll: float = 1000.0
    max_trade_size: float = 100.0
    min_edge_threshold: float = 0.02
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    market_types: List[str] = field(
        default_factory=lambda: ["BTC", "Weather", "CopyTrader"]
    )
    slippage_bps: int = 5  # 5 basis points slippage simulation


@dataclass
class BacktestResult:
    """Results from backtest run."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    final_bankroll: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    trades_per_day: float = 0.0
    roi: float = 0.0


class BacktestEngine:
    """
    Replay historical signals and trades to measure strategy performance.

    Example:
        config = BacktestConfig(initial_bankroll=1000)
        engine = BacktestEngine(config)
        result = engine.run(db_session)

        print(f"ROI: {result.roi:.2%}")
        print(f"Win Rate: {result.win_rate:.2%}")
        print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.bankroll = config.initial_bankroll
        self.max_drawdown = 0.0
        self.peak_bankroll = config.initial_bankroll
        self.pnl_history: List[float] = []
        self.equity_curve: List[tuple[datetime, float]] = []

    def run(self, db: Session) -> BacktestResult:
        """
        Run backtest against historical signals in database.

        Args:
            db: Database session

        Returns:
            BacktestResult with performance metrics
        """
        logger.info(
            f"Starting backtest with ${self.config.initial_bankroll:,.2f} initial bankroll"
        )

        # Fetch historical signals
        signals = self._fetch_signals(db)

        if not signals:
            logger.warning("No signals found for backtesting period")
            return self._empty_result()

        logger.info(f"Replaying {len(signals)} historical signals")

        # Replay each signal
        for signal in signals:
            self._replay_signal(signal, db)

        # Calculate metrics
        result = self._calculate_results(signals, db)
        return result

    def _fetch_signals(self, db: Session) -> List[Signal]:
        """Fetch historical signals for backtesting period."""
        query = db.query(Signal).order_by(Signal.timestamp.asc())

        if self.config.start_date:
            query = query.filter(Signal.timestamp >= self.config.start_date)
        if self.config.end_date:
            query = query.filter(Signal.timestamp <= self.config.end_date)

        # Filter by market type if specified
        if self.config.market_types:
            type_filters = []
            for mtype in self.config.market_types:
                if mtype == "BTC":
                    type_filters.append(Signal.market_ticker.like("BTC%"))
                elif mtype == "Weather":
                    type_filters.append(Signal.market_ticker.like("WT-%"))
                elif mtype == "CopyTrader":
                    type_filters.append(Signal.market_ticker.like("CT-%"))

            from sqlalchemy import or_

            query = query.filter(or_(*type_filters))

        return query.all()

    def _replay_signal(self, signal: Signal, db: Session) -> None:
        """
        Replay a single signal through simulated execution.

        Args:
            signal: Historical signal to replay
            db: Database session
        """
        # Check if signal passes edge threshold
        if abs(signal.edge) < self.config.min_edge_threshold:
            return

        # Calculate position size
        position_size = min(
            self.config.max_trade_size,
            self.bankroll * abs(signal.edge) * 2,  # Kelly criterion approximation
        )

        if position_size < 10:  # Minimum trade size
            return

        # Simulate slippage
        slippage = self.config.slippage_bps / 10000.0
        _entry_price = signal.market_price * (1 + slippage)

        # Find matching trade in history
        historical_trade = (
            db.query(Trade)
            .filter(
                Trade.market_ticker == signal.market_ticker,
                Trade.timestamp >= signal.timestamp,
                Trade.timestamp <= signal.timestamp + timedelta(hours=1),
            )
            .first()
        )

        if not historical_trade:
            # No trade was executed — skip signal entirely to avoid
            # non-deterministic (random) P&L simulation.  Only replay
            # signals that have a matching historical trade outcome.
            return

        pnl = historical_trade.pnl

        # Update bankroll
        self.bankroll += pnl
        self.pnl_history.append(pnl)

        # Track equity curve
        self.equity_curve.append((signal.timestamp, self.bankroll))

        # Update peak and drawdown
        if self.bankroll > self.peak_bankroll:
            self.peak_bankroll = self.bankroll

        drawdown = (self.peak_bankroll - self.bankroll) / self.peak_bankroll
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

    def _calculate_results(self, signals: List[Signal], db: Session) -> BacktestResult:
        """Calculate performance metrics from backtest run."""

        # Count wins/losses
        winning_trades = sum(1 for pnl in self.pnl_history if pnl > 0)
        losing_trades = sum(1 for pnl in self.pnl_history if pnl < 0)
        total_trades = len(self.pnl_history)

        if total_trades == 0:
            return self._empty_result()

        total_pnl = sum(self.pnl_history)
        final_bankroll = self.config.initial_bankroll + total_pnl

        # Calculate averages
        wins = [pnl for pnl in self.pnl_history if pnl > 0]
        losses = [pnl for pnl in self.pnl_history if pnl < 0]
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        # Calculate win rate
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

        # Calculate ROI
        roi = (
            final_bankroll - self.config.initial_bankroll
        ) / self.config.initial_bankroll

        # Calculate Sharpe Ratio (simplified)
        if len(self.pnl_history) > 1:
            import statistics

            avg_return = statistics.mean(self.pnl_history)
            std_return = statistics.stdev(self.pnl_history)
            sharpe_ratio = (avg_return / std_return) if std_return > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        # Calculate trades per day
        if signals and len(signals) > 1:
            time_span = (signals[-1].timestamp - signals[0].timestamp).days
            trades_per_day = total_trades / time_span if time_span > 0 else 0.0
        else:
            trades_per_day = 0.0

        return BacktestResult(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            total_pnl=total_pnl,
            final_bankroll=final_bankroll,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            max_drawdown=self.max_drawdown,
            sharpe_ratio=sharpe_ratio,
            trades_per_day=trades_per_day,
            roi=roi,
        )

    def _empty_result(self) -> BacktestResult:
        """Return empty result when no data available."""
        return BacktestResult(
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            total_pnl=0.0,
            final_bankroll=self.config.initial_bankroll,
            win_rate=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            trades_per_day=0.0,
            roi=0.0,
        )


def run_quick_backtest(
    db: Session,
    days_back: int = 30,
    initial_bankroll: float = 1000.0,
) -> BacktestResult:
    """
    Quick backtest for recent N days.

    Args:
        db: Database session
        days_back: Number of days to look back
        initial_bankroll: Starting capital

    Returns:
        BacktestResult with performance metrics
    """
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days_back)

    config = BacktestConfig(
        initial_bankroll=initial_bankroll,
        start_date=start_date,
        end_date=end_date,
    )

    engine = BacktestEngine(config)
    return engine.run(db)
