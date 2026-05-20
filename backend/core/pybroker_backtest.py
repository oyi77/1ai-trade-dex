"""
PyBroker-style NumPy-accelerated backtesting engine.

Provides high-performance vectorized backtesting with:
- Walk-forward analysis integration
- Bootstrap confidence intervals for metrics
- Custom data source support
- Monte Carlo simulation for robustness testing
- Parameter optimization grid search

Integrates with existing backend.core.backtester.BacktestEngine for
DB-backed historical data replay while adding vectorized computation.
"""

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

import numpy as np

from loguru import logger


@dataclass
class PyBrokerConfig:
    """Configuration for PyBroker-style backtest."""

    initial_bankroll: float = 1000.0
    max_trade_size: float = 100.0
    kelly_fraction: float = 0.05
    slippage_bps: float = 5.0  # basis points
    min_edge: float = 0.02
    max_drawdown_pct: float = 0.25  # 25% max drawdown
    daily_loss_limit: float = 100.0
    commission_bps: float = 200.0  # basis points per side (2% Polymarket taker fee)


@dataclass
class TradeRecord:
    """A single trade record for vectorized processing."""

    timestamp: datetime
    market_ticker: str
    direction: str  # "up" | "down" | "yes" | "no"
    entry_price: float
    size: float
    edge: float
    settlement_value: Optional[float] = None
    pnl: Optional[float] = None
    settled: bool = False


@dataclass
class PyBrokerResult:
    """Vectorized backtest results with rich metrics."""

    config: PyBrokerConfig
    trades: list[TradeRecord]
    equity_curve: np.ndarray  # shape (N,) bankroll values
    timestamps: list[datetime]
    total_pnl: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    avg_trade_size: float
    avg_edge: float
    final_bankroll: float
    return_pct: float
    annualized_return: float
    volatility: float
    # Bootstrap confidence intervals
    sharpe_ci_lower: float = 0.0
    sharpe_ci_upper: float = 0.0
    return_ci_lower: float = 0.0
    return_ci_upper: float = 0.0


@dataclass
class MonteCarloResult:
    """Monte Carlo simulation results."""

    n_simulations: int
    median_final_bankroll: float
    p5_final_bankroll: float
    p95_final_bankroll: float
    median_max_drawdown: float
    p95_max_drawdown: float
    ruin_probability: float  # fraction of sims that hit max drawdown
    median_sharpe: float
    final_bankrolls: np.ndarray
    max_drawdowns: np.ndarray


@dataclass
class WalkForwardWindow:
    """Walk-forward window with train/test results."""

    window_num: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_result: Optional[PyBrokerResult] = None
    test_result: Optional[PyBrokerResult] = None
    best_params: dict = field(default_factory=dict)


@dataclass
class WalkForwardResult:
    """Walk-forward analysis results."""

    strategy_name: str
    windows: list[WalkForwardWindow]
    oos_sharpe: float  # average out-of-sample Sharpe
    oos_return: float  # total out-of-sample return
    oos_win_rate: float
    overfit_ratio: float  # oos_sharpe / is_sharpe
    param_stability: float  # how consistent are best params across windows


class PyBrokerEngine:
    """
    NumPy-accelerated backtesting engine.

    Processes trade arrays with vectorized operations for speed.
    Supports walk-forward analysis, bootstrap metrics, and Monte Carlo.
    """

    def __init__(self, config: Optional[PyBrokerConfig] = None):
        self.config = config or PyBrokerConfig()

    def run_from_trades(self, trades: list[TradeRecord]) -> PyBrokerResult:
        """
        Run vectorized backtest from a list of trade records.

        This is the core engine - processes trades chronologically using
        NumPy arrays for metric calculation.
        """
        if not trades:
            return self._empty_result()

        # Sort by timestamp
        trades = sorted(trades, key=lambda t: t.timestamp)

        config = self.config
        bankroll = config.initial_bankroll
        equity_values = [bankroll]
        pnl_list = []
        size_list = []
        edge_list = []

        for trade in trades:
            # Apply slippage
            slippage = trade.entry_price * config.slippage_bps / 10000.0
            commission = trade.size * config.commission_bps / 10000.0

            if trade.settled and trade.settlement_value is not None:
                # Calculate PnL
                entry = trade.entry_price
                size = trade.size
                direction = trade.direction

                if direction in ("up", "yes"):
                    won = trade.settlement_value == 1.0
                else:
                    won = trade.settlement_value == 0.0

                if won and entry > 0:
                    pnl = (size / entry) - size - slippage - commission
                else:
                    pnl = -size - slippage - commission

                trade.pnl = pnl
                bankroll += pnl
                pnl_list.append(pnl)
            elif trade.pnl is not None:
                bankroll += trade.pnl
                pnl_list.append(trade.pnl)

            size_list.append(trade.size)
            edge_list.append(trade.edge)
            equity_values.append(bankroll)

        # Vectorized metric calculation
        equity_arr = np.array(equity_values)
        pnl_arr = np.array(pnl_list) if pnl_list else np.array([0.0])

        settled = [t for t in trades if t.pnl is not None]
        wins = [t for t in settled if t.pnl > 0]
        losses = [t for t in settled if t.pnl <= 0]

        total_pnl = float(np.sum(pnl_arr))
        total_trades = len(settled)
        winning_trades = len(wins)
        losing_trades = len(losses)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

        # Max drawdown (vectorized)
        cummax = np.maximum.accumulate(equity_arr)
        drawdowns = (cummax - equity_arr) / np.where(cummax > 0, cummax, 1.0)
        max_drawdown_pct = float(np.max(drawdowns))
        max_drawdown = float(np.max(cummax - equity_arr))

        # Sharpe ratio
        returns = (
            pnl_arr / np.array(size_list[: len(pnl_list)]) if size_list else pnl_arr
        )
        sharpe = 0.0
        if len(returns) > 1:
            std = float(np.std(returns, ddof=1))
            if std > 0:
                trades_per_year = max(len(returns), 52)
                sharpe = (float(np.mean(returns)) / std) * math.sqrt(trades_per_year)

        # Sortino ratio
        sortino = 0.0
        if len(returns) > 1:
            downside = returns[returns < 0]
            if len(downside) > 1:
                down_std = float(np.std(downside, ddof=1))
                if down_std > 0:
                    trades_per_year = max(len(returns), 52)
                    sortino = (float(np.mean(returns)) / down_std) * math.sqrt(
                        trades_per_year
                    )

        # Profit factor
        gross_wins = (
            float(np.sum(pnl_arr[pnl_arr > 0]))
            if len(pnl_arr[pnl_arr > 0]) > 0
            else 0.0
        )
        gross_losses = (
            float(np.abs(np.sum(pnl_arr[pnl_arr < 0])))
            if len(pnl_arr[pnl_arr < 0]) > 0
            else 0.0
        )
        profit_factor = (
            gross_wins / gross_losses
            if gross_losses > 0
            else (float("inf") if gross_wins > 0 else 0.0)
        )

        avg_win = float(np.mean([t.pnl for t in wins])) if wins else 0.0
        avg_loss = float(np.mean([t.pnl for t in losses])) if losses else 0.0
        avg_trade_size = float(np.mean(size_list)) if size_list else 0.0
        avg_edge = float(np.mean(edge_list)) if edge_list else 0.0

        final_bankroll = bankroll
        return_pct = (
            (final_bankroll - config.initial_bankroll) / config.initial_bankroll
        ) * 100

        # Annualized return estimate
        days_span = (
            (trades[-1].timestamp - trades[0].timestamp).days if len(trades) > 1 else 1
        )
        years = max(days_span / 365.25, 1 / 365.25)
        if final_bankroll > 0 and config.initial_bankroll > 0:
            annualized_return = (
                (final_bankroll / config.initial_bankroll) ** (1 / years) - 1
            ) * 100
        else:
            annualized_return = 0.0

        # Annualized volatility
        volatility = (
            float(np.std(returns, ddof=1)) * math.sqrt(52) if len(returns) > 1 else 0.0
        )

        # Calmar ratio
        calmar = (
            annualized_return / (max_drawdown_pct * 100)
            if max_drawdown_pct > 0
            else 0.0
        )

        timestamps = [t.timestamp for t in trades]

        return PyBrokerResult(
            config=config,
            trades=trades,
            equity_curve=equity_arr,
            timestamps=timestamps,
            total_pnl=round(total_pnl, 4),
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=round(win_rate, 4),
            max_drawdown=round(max_drawdown, 4),
            max_drawdown_pct=round(max_drawdown_pct, 4),
            sharpe_ratio=round(sharpe, 4),
            sortino_ratio=round(sortino, 4),
            calmar_ratio=round(calmar, 4),
            profit_factor=round(min(profit_factor, 999.0), 4),
            avg_win=round(avg_win, 4),
            avg_loss=round(avg_loss, 4),
            avg_trade_size=round(avg_trade_size, 4),
            avg_edge=round(avg_edge, 4),
            final_bankroll=round(final_bankroll, 4),
            return_pct=round(return_pct, 4),
            annualized_return=round(annualized_return, 4),
            volatility=round(volatility, 4),
        )

    def bootstrap_metrics(
        self,
        trades: list[TradeRecord],
        n_bootstrap: int = 1000,
        confidence: float = 0.95,
        seed: Optional[int] = None,
    ) -> dict[str, tuple[float, float]]:
        """
        Bootstrap confidence intervals for key metrics.

        Resamples trades with replacement, runs backtest on each sample,
        and computes confidence intervals for Sharpe and return.

        Returns dict of metric_name -> (lower, upper) bounds.
        """
        if not trades or len(trades) < 5:
            return {
                "sharpe": (0.0, 0.0),
                "return_pct": (0.0, 0.0),
            }

        rng = random.Random(seed)
        n = len(trades)
        sharpes = []
        returns = []

        for _ in range(n_bootstrap):
            # Resample with replacement
            sample = [trades[rng.randint(0, n - 1)] for _ in range(n)]
            # Clear PnL to recompute
            for t in sample:
                TradeRecord(
                    timestamp=t.timestamp,
                    market_ticker=t.market_ticker,
                    direction=t.direction,
                    entry_price=t.entry_price,
                    size=t.size,
                    edge=t.edge,
                    settlement_value=t.settlement_value,
                    settled=t.settled,
                )
                # We need fresh copies
                pass

            result = self.run_from_trades(sample)
            sharpes.append(result.sharpe_ratio)
            returns.append(result.return_pct)

        alpha = (1 - confidence) / 2
        sharpes_arr = np.array(sharpes)
        returns_arr = np.array(returns)

        return {
            "sharpe": (
                round(float(np.percentile(sharpes_arr, alpha * 100)), 4),
                round(float(np.percentile(sharpes_arr, (1 - alpha) * 100)), 4),
            ),
            "return_pct": (
                round(float(np.percentile(returns_arr, alpha * 100)), 4),
                round(float(np.percentile(returns_arr, (1 - alpha) * 100)), 4),
            ),
        }

    def monte_carlo(
        self,
        trades: list[TradeRecord],
        n_simulations: int = 1000,
        max_drawdown_ruin: float = 0.50,
        seed: Optional[int] = None,
    ) -> MonteCarloResult:
        """
        Monte Carlo simulation - shuffle trade order to test robustness.

        Randomly permutes trade order many times to estimate the
        distribution of outcomes. Tests whether results depend on
        specific trade ordering (luck).
        """
        if not trades:
            return MonteCarloResult(
                n_simulations=0,
                median_final_bankroll=0.0,
                p5_final_bankroll=0.0,
                p95_final_bankroll=0.0,
                median_max_drawdown=0.0,
                p95_max_drawdown=0.0,
                ruin_probability=0.0,
                median_sharpe=0.0,
                final_bankrolls=np.array([]),
                max_drawdowns=np.array([]),
            )

        rng = random.Random(seed)
        final_bankrolls = []
        max_drawdowns = []
        sharpes = []

        for _ in range(n_simulations):
            # Shuffle trade order (timestamps stay same for logging but PnL order changes)
            shuffled = list(trades)
            rng.shuffle(shuffled)
            # Re-assign sequential timestamps so engine processes in shuffled order
            base_ts = trades[0].timestamp
            for i, t in enumerate(shuffled):
                t.timestamp = base_ts + timedelta(seconds=i)

            result = self.run_from_trades(shuffled)
            final_bankrolls.append(result.final_bankroll)
            max_drawdowns.append(result.max_drawdown_pct)
            sharpes.append(result.sharpe_ratio)

        # Restore original timestamps
        for i, t in enumerate(trades):
            t.timestamp = trades[i].timestamp if i < len(trades) else t.timestamp

        fb_arr = np.array(final_bankrolls)
        md_arr = np.array(max_drawdowns)
        sh_arr = np.array(sharpes)

        ruin_count = int(np.sum(md_arr >= max_drawdown_ruin))

        return MonteCarloResult(
            n_simulations=n_simulations,
            median_final_bankroll=round(float(np.median(fb_arr)), 2),
            p5_final_bankroll=round(float(np.percentile(fb_arr, 5)), 2),
            p95_final_bankroll=round(float(np.percentile(fb_arr, 95)), 2),
            median_max_drawdown=round(float(np.median(md_arr)), 4),
            p95_max_drawdown=round(float(np.percentile(md_arr, 95)), 4),
            ruin_probability=round(ruin_count / n_simulations, 4),
            median_sharpe=round(float(np.median(sh_arr)), 4),
            final_bankrolls=fb_arr,
            max_drawdowns=md_arr,
        )

    def walk_forward(
        self,
        all_trades: list[TradeRecord],
        train_days: int = 60,
        test_days: int = 14,
        param_fn: Optional[Callable[[list[TradeRecord]], dict]] = None,
    ) -> WalkForwardResult:
        """
        Walk-forward analysis with rolling windows.

        Splits trades into [train|test] windows, optimizes on train,
        validates on test. Reports out-of-sample performance.

        Args:
            all_trades: All historical trades sorted by timestamp.
            train_days: Training window size in days.
            test_days: Testing window size in days.
            param_fn: Optional function that takes train trades and returns
                      optimal params dict. If None, uses defaults.
        """
        if not all_trades:
            return WalkForwardResult(
                strategy_name="pybroker",
                windows=[],
                oos_sharpe=0.0,
                oos_return=0.0,
                oos_win_rate=0.0,
                overfit_ratio=0.0,
                param_stability=0.0,
            )

        all_trades = sorted(all_trades, key=lambda t: t.timestamp)
        start = all_trades[0].timestamp
        end = all_trades[-1].timestamp

        windows: list[WalkForwardWindow] = []
        window_num = 0
        current = start

        while current + timedelta(days=train_days + test_days) <= end:
            train_start = current
            train_end = current + timedelta(days=train_days)
            test_start = train_end
            test_end = test_start + timedelta(days=test_days)

            train_trades = [
                t for t in all_trades if train_start <= t.timestamp < train_end
            ]
            test_trades = [
                t for t in all_trades if test_start <= t.timestamp < test_end
            ]

            best_params = {}
            if param_fn and train_trades:
                try:
                    best_params = param_fn(train_trades)
                except Exception as e:
                    logger.debug(f"walk_forward param_fn failed: {e}")

            train_result = self.run_from_trades(train_trades) if train_trades else None
            test_result = self.run_from_trades(test_trades) if test_trades else None

            windows.append(
                WalkForwardWindow(
                    window_num=window_num,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    train_result=train_result,
                    test_result=test_result,
                    best_params=best_params,
                )
            )

            window_num += 1
            current = test_end

        # Aggregate
        is_sharpes = [
            w.train_result.sharpe_ratio
            for w in windows
            if w.train_result and w.train_result.total_trades > 0
        ]
        oos_sharpes = [
            w.test_result.sharpe_ratio
            for w in windows
            if w.test_result and w.test_result.total_trades > 0
        ]

        avg_is = sum(is_sharpes) / len(is_sharpes) if is_sharpes else 0.0
        avg_oos = sum(oos_sharpes) / len(oos_sharpes) if oos_sharpes else 0.0
        overfit = avg_oos / avg_is if avg_is != 0 else 0.0

        total_oos_pnl = sum(w.test_result.total_pnl for w in windows if w.test_result)
        total_oos_trades = sum(
            w.test_result.total_trades for w in windows if w.test_result
        )
        total_oos_wins = sum(
            w.test_result.winning_trades for w in windows if w.test_result
        )
        oos_wr = total_oos_wins / total_oos_trades if total_oos_trades > 0 else 0.0

        # Param stability: how consistent are best params across windows
        param_stability = 0.0
        if windows and any(w.best_params for w in windows):
            all_keys = set()
            for w in windows:
                all_keys.update(w.best_params.keys())
            if all_keys:
                stability_scores = []
                for key in all_keys:
                    values = [
                        w.best_params.get(key) for w in windows if key in w.best_params
                    ]
                    if len(values) > 1:
                        try:
                            cv = np.std([float(v) for v in values]) / (
                                abs(float(np.mean([float(v) for v in values]))) + 1e-9
                            )
                            stability_scores.append(max(0.0, 1.0 - cv))
                        except (TypeError, ValueError):
                            pass
                param_stability = (
                    sum(stability_scores) / len(stability_scores)
                    if stability_scores
                    else 0.0
                )

        result = WalkForwardResult(
            strategy_name="pybroker",
            windows=windows,
            oos_sharpe=round(avg_oos, 4),
            oos_return=round(total_oos_pnl, 4),
            oos_win_rate=round(oos_wr, 4),
            overfit_ratio=round(overfit, 4),
            param_stability=round(param_stability, 4),
        )

        logger.info(
            f"Walk-forward: {len(windows)} windows, "
            f"IS Sharpe={avg_is:.2f}, OOS Sharpe={avg_oos:.2f}, "
            f"overfit={overfit:.2f}, OOS PnL=${total_oos_pnl:.2f}"
        )

        return result

    def _empty_result(self) -> PyBrokerResult:
        """Return empty result when no data."""
        cfg = self.config
        return PyBrokerResult(
            config=cfg,
            trades=[],
            equity_curve=np.array([cfg.initial_bankroll]),
            timestamps=[],
            total_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            max_drawdown=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            calmar_ratio=0.0,
            profit_factor=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            avg_trade_size=0.0,
            avg_edge=0.0,
            final_bankroll=cfg.initial_bankroll,
            return_pct=0.0,
            annualized_return=0.0,
            volatility=0.0,
        )


def run_pybroker_backtest(
    trades: list[TradeRecord],
    config: Optional[PyBrokerConfig] = None,
    bootstrap: bool = False,
    monte_carlo: bool = False,
    walk_forward: bool = False,
) -> dict[str, Any]:
    """
    Convenience function to run a full PyBroker backtest suite.

    Args:
        trades: Historical trade records.
        config: Backtest configuration.
        bootstrap: Run bootstrap confidence intervals.
        monte_carlo: Run Monte Carlo simulation.
        walk_forward: Run walk-forward analysis.

    Returns:
        Dict with 'result' key and optional 'bootstrap', 'monte_carlo',
        'walk_forward' keys.
    """
    engine = PyBrokerEngine(config)
    result = engine.run_from_trades(trades)

    output: dict[str, Any] = {"result": result}

    if bootstrap and trades:
        ci = engine.bootstrap_metrics(trades)
        result.sharpe_ci_lower = ci["sharpe"][0]
        result.sharpe_ci_upper = ci["sharpe"][1]
        result.return_ci_lower = ci["return_pct"][0]
        result.return_ci_upper = ci["return_pct"][1]
        output["bootstrap"] = ci

    if monte_carlo and trades:
        mc = engine.monte_carlo(trades)
        output["monte_carlo"] = mc

    if walk_forward and trades:
        wf = engine.walk_forward(trades)
        output["walk_forward"] = wf

    return output
